import logging
import threading
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterator

import requests
from django.conf import settings
from django.db import models
from django.core.management.base import BaseCommand
from django.utils import timezone as django_timezone

from api.management.dev_bbox import filter_wells_by_dev_bbox, write_dev_bbox_notice
from api.models import IngestRun, IngestRunStatus, Measurement, Well

GLD_BASE_URL = "https://publiek.broservices.nl/gm/gld/v1/objects/{gld_bro_id}"
OBSERVATIONS_SUMMARY_URL = GLD_BASE_URL + "/observationsSummary"
OBSERVATION_URL = GLD_BASE_URL + "/observations/{observation_id}"

WATERML_NS = "http://www.opengis.net/waterml/2.0"
SWE_NS = "http://www.opengis.net/swe/2.0"
XLINK_NS = "http://www.w3.org/1999/xlink"

CHUNK_SIZE = 200
GLD_OBJECT_TIMEOUT = 120
logger = logging.getLogger(__name__)


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    minutes, sec = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s" if sec else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


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
_thread_local = threading.local()


def _http_session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        _thread_local.session = session
    return session


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
            resp = _http_session().get(url, params=params or {}, timeout=timeout)
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
    last_measured_at: datetime | None, retention_cutoff: datetime
) -> datetime:
    if last_measured_at is None or last_measured_at < retention_cutoff:
        return retention_cutoff
    return last_measured_at


def _filter_since(
    observations: list[tuple[datetime, float, str]], since: datetime | None
) -> list[tuple[datetime, float, str]]:
    if since is None:
        return observations
    return [(ts, val, quality) for ts, val, quality in observations if ts >= since]


def _should_bulk_fetch(since: datetime | None) -> bool:
    if since is None:
        return True
    threshold = getattr(settings, "BRO_BULK_FETCH_DAYS", 14)
    age_days = (django_timezone.now() - since).days
    return age_days > threshold


def _fetch_gld_object_bulk(
    gld_bro_id: str, since: datetime | None, bucket: TokenBucket
) -> list[tuple[datetime, float, str]]:
    url = GLD_BASE_URL.format(gld_bro_id=gld_bro_id)
    resp = _get(url, bucket, timeout=GLD_OBJECT_TIMEOUT)
    return _filter_since(_parse_tvp_xml(resp.content), since)


def _fetch_gld_per_observation(
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
    return _filter_since(all_results, since)


def _fetch_gld(
    gld_bro_id: str, since: datetime | None, bucket: TokenBucket
) -> list[tuple[datetime, float, str]]:
    if _should_bulk_fetch(since):
        return _fetch_gld_object_bulk(gld_bro_id, since, bucket)
    return _fetch_gld_per_observation(gld_bro_id, since, bucket)


def _aggregate_daily(
    observations: list[tuple[datetime, float, str]],
) -> list[tuple[date, float]]:
    day_values: dict[date, list[float]] = defaultdict(list)
    for ts, val, quality in observations:
        if quality != "goedgekeurd":
            continue
        day_values[ts.date()].append(val)
    return sorted([(d, sum(vals) / len(vals)) for d, vals in day_values.items()])


def _upsert_measurements(well: Well, daily_obs: list[tuple[date, float]]) -> None:
    if not daily_obs:
        return
    dates = [d for d, _ in daily_obs]
    existing_dates = set(
        Measurement.objects.filter(
            well=well,
            measured_on__gte=min(dates),
            measured_on__lte=max(dates),
        ).values_list("measured_on", flat=True)
    )
    new_rows = [
        Measurement(well=well, measured_on=d, value_m_nap=val)
        for d, val in daily_obs
        if d not in existing_dates
    ]
    if new_rows:
        Measurement.objects.bulk_create(new_rows, ignore_conflicts=True)


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


def _last_measured_for_wells(wells: list[Well]) -> dict[int, datetime]:
    """Return {well_id: last measured_on as datetime} for a list of wells."""
    from django.db.models import Max

    well_ids = [w.id for w in wells]
    rows = (
        Measurement.objects.filter(well_id__in=well_ids)
        .values("well_id")
        .annotate(last_date=Max("measured_on"))
    )
    tz = django_timezone.get_current_timezone()
    return {
        row["well_id"]: datetime(
            row["last_date"].year,
            row["last_date"].month,
            row["last_date"].day,
            tzinfo=tz,
        )
        for row in rows
        if row["last_date"] is not None
    }


def _fetch_well_measurements(
    well: Well,
    last_measured_at: datetime | None,
    retention_cutoff: datetime,
    bucket: TokenBucket,
) -> FetchResult:
    try:
        since = _fetch_since(last_measured_at, retention_cutoff)
        observations = _fetch_gld(well.gld_bro_id, since, bucket)
        return FetchResult(well=well, observations=observations)
    except Exception as exc:
        return FetchResult(well=well, observations=[], error=str(exc))


def _fetch_wells_parallel(
    wells: list[Well],
    last_measured: dict[int, datetime],
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
                last_measured.get(well.id),
                retention_cutoff,
                bucket,
            )
            for well in wells
        ]
        for future in as_completed(futures):
            yield future.result()


def _apply_fetch_result(result: FetchResult) -> None:
    daily_obs = _aggregate_daily(result.observations)
    _upsert_measurements(result.well, daily_obs)


class Command(BaseCommand):
    help = "Incrementally fetch GLD measurements per well from the BRO REST API."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Only process N wells (0 = all, for testing).",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help=(
                "Force full re-fetch from MEASUREMENT_RETENTION_DAYS ago, "
                "ignoring the latest stored measurement date."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        run = IngestRun.objects.create(kind="fetch_measurements")
        errors: list[str] = []
        processed = 0

        try:
            processed = self._fetch_all_measurements(options, errors)
            run.wells_processed = processed
            run.status = (
                IngestRunStatus.SUCCESS if not errors else IngestRunStatus.FAILED
            )
            logger.info("Done. Processed %d wells, %d errors.", processed, len(errors))
        except Exception as exc:
            errors.append(str(exc))
            run.wells_processed = processed
            run.status = IngestRunStatus.FAILED
            logger.exception("fetch_measurements failed: %s", exc)

        run.finished_at = django_timezone.now()
        run.errors_json = errors
        run.save()

    def _fetch_all_measurements(
        self, options: dict[str, Any], errors: list[str]
    ) -> int:
        rate = getattr(settings, "BRO_RATE_LIMIT_RPS", 3)
        workers = getattr(settings, "BRO_PARALLEL_WORKERS", max(3, int(rate * 2)))
        bucket = TokenBucket(rate)
        retention_days = getattr(settings, "MEASUREMENT_RETENTION_DAYS", 365)
        now = django_timezone.now()
        retention_cutoff = now - timedelta(days=retention_days)
        limit = options["limit"]
        processed = 0
        completed = 0

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
        write_dev_bbox_notice()
        if limit:
            wells = wells[:limit]

        total = wells.count()
        logger.info(
            "Fetching measurements for %d active wells (%d workers @ %s req/s)...",
            total,
            workers,
            rate,
        )

        last_logged_pct = 0
        started_at = time.monotonic()

        def log_progress() -> None:
            nonlocal last_logged_pct
            if total == 0:
                return
            new_pct = completed * 100 // total
            while last_logged_pct < new_pct:
                last_logged_pct += 1
                eta = ""
                if completed > 0:
                    elapsed = time.monotonic() - started_at
                    remaining = (total - completed) * elapsed / completed
                    eta = f", ETA {_format_duration(remaining)}"
                logger.info("  %d/%d (%d%%)%s", completed, total, last_logged_pct, eta)

        for chunk in _well_chunks(wells, CHUNK_SIZE):
            last_measured = {} if options["reset"] else _last_measured_for_wells(chunk)

            for result in _fetch_wells_parallel(
                chunk, last_measured, retention_cutoff, bucket, workers=workers
            ):
                well = result.well
                completed += 1
                if result.error:
                    errors.append(f"{well.bro_id}: {result.error}")
                    logger.error("Error %s: %s", well.bro_id, result.error)
                    log_progress()
                    continue

                try:
                    _apply_fetch_result(result)
                    processed += 1
                except Exception as exc:
                    errors.append(f"{well.bro_id}: db write: {exc}")
                    logger.error("DB write error %s: %s", well.bro_id, exc)
                log_progress()

        return processed
