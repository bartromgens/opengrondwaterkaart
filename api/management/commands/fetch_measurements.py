import logging
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterator

import requests
from django.conf import settings
from django.db import models
from django.core.management.base import BaseCommand
from django.utils import timezone as django_timezone

from api.management.dev_bbox import filter_wells_by_dev_bbox, write_dev_bbox_notice
from api.models import IngestRun, IngestRunStatus, Measurement, Well, WellStatus

GLD_BASE_URL = "https://publiek.broservices.nl/gm/gld/v1/objects/{gld_bro_id}"
OBSERVATIONS_SUMMARY_URL = GLD_BASE_URL + "/observationsSummary"
OBSERVATION_URL = GLD_BASE_URL + "/observations/{observation_id}"

WATERML_NS = "http://www.opengis.net/waterml/2.0"
SWE_NS = "http://www.opengis.net/swe/2.0"
XLINK_NS = "http://www.w3.org/1999/xlink"

CHUNK_SIZE = 200
logger = logging.getLogger(__name__)
STATUS_UPDATE_FIELDS = [
    "last_fetched_at",
    "latest_measured_at",
    "latest_value_m_nap",
    "is_stale",
]


class TokenBucket:
    """Strict interval-based rate limiter shared across worker threads."""

    def __init__(self, rate: float) -> None:
        self._interval = 1.0 / rate
        self._lock = threading.Lock()
        self._next_slot = time.monotonic()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next_slot:
                time.sleep(self._next_slot - now)
                now = time.monotonic()
            self._next_slot = now + self._interval


_MAX_GET_ATTEMPTS = 8


def _retry_delay(attempt: int, status_code: int | None) -> float:
    if status_code == 429:
        return min(30.0, 2.0**attempt)
    return float(2**attempt)


def _warn_rate_limited(url: str, attempt: int, delay: float) -> None:
    logger.warning(
        "BRO API rate limited (429) for %s; retry %d/%d in %.1fs",
        url,
        attempt + 1,
        _MAX_GET_ATTEMPTS,
        delay,
    )


def _get(
    url: str, bucket: TokenBucket, params: dict | None = None, timeout: int = 60
) -> requests.Response:
    last_status: int | None = None
    for attempt in range(_MAX_GET_ATTEMPTS):
        bucket.acquire()
        try:
            resp = requests.get(url, params=params or {}, timeout=timeout)
            last_status = resp.status_code
            if resp.status_code == 429 or resp.status_code >= 500:
                delay = _retry_delay(attempt, resp.status_code)
                if resp.status_code == 429:
                    _warn_rate_limited(url, attempt, delay)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException:
            if attempt == _MAX_GET_ATTEMPTS - 1:
                raise
            time.sleep(_retry_delay(attempt, last_status))
    detail = f" (last status {last_status})" if last_status else ""
    raise RuntimeError(
        f"Failed to GET {url} after {_MAX_GET_ATTEMPTS} attempts{detail}"
    )


def _observations_since(
    gld_bro_id: str, since: datetime | None, bucket: TokenBucket
) -> list[dict]:
    """Return observation summaries that overlap the desired time window."""
    resp = _get(OBSERVATIONS_SUMMARY_URL.format(gld_bro_id=gld_bro_id), bucket)
    summaries = resp.json()
    if not isinstance(summaries, list):
        return []
    if since is None:
        return summaries

    since_date = since.date()
    relevant = []
    for obs in summaries:
        end_str = obs.get("endDate", "")
        try:
            # Format from API: "31-12-2019"
            end_date = datetime.strptime(end_str, "%d-%m-%Y").date()
            if end_date >= since_date:
                relevant.append(obs)
        except ValueError:
            relevant.append(obs)
    return relevant


def _parse_tvp_xml(content: bytes) -> list[tuple[datetime, float, str]]:
    results: list[tuple[datetime, float, str]] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return results

    for tvp in root.iter(f"{{{WATERML_NS}}}MeasurementTVP"):
        time_el = tvp.find(f"{{{WATERML_NS}}}time")
        value_el = tvp.find(f"{{{WATERML_NS}}}value")
        if time_el is None or value_el is None:
            continue
        try:
            ts = datetime.fromisoformat(
                (time_el.text or "").strip().replace("Z", "+00:00")
            )
            val = float(value_el.text or "")
            # Quality is in the TVPMeasurementMetadata qualifier
            quality = ""
            qual_el = tvp.find(
                f".//{{{WATERML_NS}}}TVPMeasurementMetadata"
                f"/{{{WATERML_NS}}}qualifier"
                f"/{{{SWE_NS}}}Category"
                f"/{{{SWE_NS}}}value"
            )
            if qual_el is not None and qual_el.text:
                quality = qual_el.text.strip()
            results.append((ts, val, quality))
        except (ValueError, TypeError):
            continue
    return results


def _fetch_since(
    last_fetched_at: datetime | None, retention_cutoff: datetime
) -> datetime:
    if last_fetched_at is None or last_fetched_at < retention_cutoff:
        return retention_cutoff
    return last_fetched_at


def _fetch_gld(
    gld_bro_id: str, since: datetime | None, bucket: TokenBucket
) -> list[tuple[datetime, float, str]]:
    obs_list = _observations_since(gld_bro_id, since, bucket)
    all_results: list[tuple[datetime, float, str]] = []
    for obs in obs_list:
        obs_id = obs.get("observationId")
        if not obs_id:
            continue
        params: dict[str, str] = {}
        if since:
            params["startTVPTime"] = since.strftime("%Y-%m-%d")
        url = OBSERVATION_URL.format(gld_bro_id=gld_bro_id, observation_id=obs_id)
        resp = _get(url, bucket, params=params)
        all_results.extend(_parse_tvp_xml(resp.content))
    if since:
        return [(ts, val, quality) for ts, val, quality in all_results if ts >= since]
    return all_results


def _upsert_measurements(
    well: Well, observations: list[tuple[datetime, float, str]]
) -> None:
    if not observations:
        return
    existing_times = set(
        Measurement.objects.filter(well=well).values_list("measured_at", flat=True)
    )
    new_obs = [
        Measurement(well=well, measured_at=ts, value_m_nap=val, quality=quality)
        for ts, val, quality in observations
        if ts not in existing_times
    ]
    if new_obs:
        Measurement.objects.bulk_create(new_obs, ignore_conflicts=True)


@dataclass
class FetchResult:
    well: Well
    observations: list[tuple[datetime, float, str]]
    error: str | None = None


def _well_chunks(qs: Any, chunk_size: int) -> Iterator[list[Well]]:
    chunk: list[Well] = []
    for well in qs.iterator(chunk_size=chunk_size):
        chunk.append(well)
        if len(chunk) >= chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _statuses_for_wells(wells: list[Well]) -> dict[int, WellStatus]:
    well_ids = [well.id for well in wells]
    statuses = {
        status.well_id: status
        for status in WellStatus.objects.filter(well_id__in=well_ids)
    }
    for well in wells:
        if well.id not in statuses:
            status, _ = WellStatus.objects.get_or_create(well=well)
            statuses[well.id] = status
    return statuses


def _fetch_well_measurements(
    well: Well,
    last_fetched_at: datetime | None,
    retention_cutoff: datetime,
    bucket: TokenBucket,
) -> FetchResult:
    try:
        since = _fetch_since(last_fetched_at, retention_cutoff)
        observations = _fetch_gld(well.gld_bro_id, since, bucket)
        return FetchResult(well=well, observations=observations)
    except Exception as exc:
        return FetchResult(well=well, observations=[], error=str(exc))


def _fetch_wells_parallel(
    wells: list[Well],
    statuses: dict[int, WellStatus],
    retention_cutoff: datetime,
    bucket: TokenBucket,
    *,
    workers: int,
) -> Iterator[FetchResult]:
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                _fetch_well_measurements,
                well,
                statuses[well.id].last_fetched_at,
                retention_cutoff,
                bucket,
            )
            for well in wells
        ]
        for future in as_completed(futures):
            yield future.result()


def _apply_fetch_result(
    result: FetchResult,
    status: WellStatus,
    *,
    now: datetime,
    stale_days: int,
) -> None:
    _upsert_measurements(result.well, result.observations)
    status.last_fetched_at = now
    if result.observations:
        latest_ts, latest_val, _ = max(result.observations, key=lambda x: x[0])
        if status.latest_measured_at is None or latest_ts > status.latest_measured_at:
            status.latest_measured_at = latest_ts
            status.latest_value_m_nap = latest_val

    if status.latest_measured_at:
        age = now - status.latest_measured_at
        status.is_stale = age.days > stale_days
    else:
        status.is_stale = True


class Command(BaseCommand):
    help = "Incrementally fetch GLD measurements per well from the BRO REST API."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Only process N wells (0 = all, for testing).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        run = IngestRun.objects.create(kind="fetch_measurements")
        errors: list[str] = []
        rate = getattr(settings, "BRO_RATE_LIMIT_RPS", 3)
        workers = getattr(settings, "BRO_PARALLEL_WORKERS", max(3, int(rate * 2)))
        bucket = TokenBucket(rate)
        stale_days = getattr(settings, "STALE_THRESHOLD_DAYS", 35)
        retention_days = getattr(settings, "MEASUREMENT_RETENTION_DAYS", 365)
        now = django_timezone.now()
        retention_cutoff = now - timedelta(days=retention_days)
        processed = 0
        completed = 0
        limit = options["limit"]

        inactive_days = getattr(settings, "INACTIVE_WELL_DAYS", 365)
        cutoff = (
            django_timezone.now() - django_timezone.timedelta(days=inactive_days)
        ).date()

        wells = filter_wells_by_dev_bbox(
            Well.objects.filter(gld_bro_id__gt="")
            .filter(
                models.Q(research_last_date__isnull=True)
                | models.Q(research_last_date__gte=cutoff)
            )
            .order_by("id")
        )
        write_dev_bbox_notice(self.stdout)
        if limit:
            wells = wells[:limit]

        total = wells.count()
        self.stdout.write(
            f"Fetching measurements for {total} active wells "
            f"({workers} workers @ {rate} req/s)..."
        )

        last_logged_pct = 0

        def log_progress() -> None:
            nonlocal last_logged_pct
            if total == 0:
                return
            new_pct = completed * 100 // total
            while last_logged_pct < new_pct:
                last_logged_pct += 1
                self.stdout.write(f"  {completed}/{total} ({last_logged_pct}%)")
                self.stdout.flush()

        for chunk in _well_chunks(wells, CHUNK_SIZE):
            statuses = _statuses_for_wells(chunk)
            statuses_to_update: list[WellStatus] = []

            for result in _fetch_wells_parallel(
                chunk, statuses, retention_cutoff, bucket, workers=workers
            ):
                well = result.well
                completed += 1
                if result.error:
                    errors.append(f"{well.bro_id}: {result.error}")
                    self.stderr.write(f"  Error {well.bro_id}: {result.error}")
                    log_progress()
                    continue

                status = statuses[well.id]
                _apply_fetch_result(result, status, now=now, stale_days=stale_days)
                statuses_to_update.append(status)
                processed += 1
                log_progress()

            if statuses_to_update:
                WellStatus.objects.bulk_update(statuses_to_update, STATUS_UPDATE_FIELDS)

        run.wells_processed = processed
        run.finished_at = django_timezone.now()
        run.errors_json = errors
        run.status = IngestRunStatus.SUCCESS if not errors else IngestRunStatus.FAILED
        run.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Processed {processed} wells, {len(errors)} errors."
            )
        )
