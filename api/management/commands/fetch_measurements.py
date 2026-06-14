import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

import requests
from django.conf import settings
from django.db import models
from django.core.management.base import BaseCommand
from django.utils import timezone as django_timezone

from api.models import IngestRun, IngestRunStatus, Measurement, Well, WellStatus

GLD_BASE_URL = "https://publiek.broservices.nl/gm/gld/v1/objects/{gld_bro_id}"
OBSERVATIONS_SUMMARY_URL = GLD_BASE_URL + "/observationsSummary"
OBSERVATION_URL = GLD_BASE_URL + "/observations/{observation_id}"

WATERML_NS = "http://www.opengis.net/waterml/2.0"
SWE_NS = "http://www.opengis.net/swe/2.0"
XLINK_NS = "http://www.w3.org/1999/xlink"


class TokenBucket:
    def __init__(self, rate: float) -> None:
        self._rate = rate
        self._tokens = rate
        self._last = time.monotonic()

    def acquire(self) -> None:
        now = time.monotonic()
        self._tokens = min(self._rate, self._tokens + (now - self._last) * self._rate)
        self._last = now
        if self._tokens < 1:
            time.sleep((1 - self._tokens) / self._rate)
            self._tokens = 0
        else:
            self._tokens -= 1


def _get(
    url: str, bucket: TokenBucket, params: dict | None = None, timeout: int = 60
) -> requests.Response:
    for attempt in range(4):
        bucket.acquire()
        try:
            resp = requests.get(url, params=params or {}, timeout=timeout)
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(2**attempt)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2**attempt)
    raise RuntimeError(f"Failed to GET {url} after 4 attempts")


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
        bucket = TokenBucket(rate)
        stale_days = getattr(settings, "STALE_THRESHOLD_DAYS", 35)
        now = django_timezone.now()
        processed = 0
        limit = options["limit"]

        inactive_days = getattr(settings, "INACTIVE_WELL_DAYS", 365)
        cutoff = (
            django_timezone.now() - django_timezone.timedelta(days=inactive_days)
        ).date()

        wells = (
            Well.objects.filter(gld_bro_id__gt="")
            .filter(
                models.Q(research_last_date__isnull=True)
                | models.Q(research_last_date__gte=cutoff)
            )
            .order_by("id")
        )
        if limit:
            wells = wells[:limit]

        total = wells.count()
        self.stdout.write(
            f"Fetching measurements for {total} active wells at {rate} req/s..."
        )

        for well in wells.iterator(chunk_size=200):
            status, _ = WellStatus.objects.get_or_create(well=well)
            try:
                observations = _fetch_gld(
                    well.gld_bro_id, status.last_fetched_at, bucket
                )
                _upsert_measurements(well, observations)

                status.last_fetched_at = now
                if observations:
                    latest_ts, latest_val, _ = max(observations, key=lambda x: x[0])
                    if (
                        status.latest_measured_at is None
                        or latest_ts > status.latest_measured_at
                    ):
                        status.latest_measured_at = latest_ts
                        status.latest_value_m_nap = latest_val

                if status.latest_measured_at:
                    age = now - status.latest_measured_at
                    status.is_stale = age.days > stale_days
                else:
                    status.is_stale = True

                status.save()
                processed += 1

                if processed % 100 == 0:
                    self.stdout.write(f"  {processed}/{total}")

            except Exception as exc:
                errors.append(f"{well.bro_id}: {exc}")
                self.stderr.write(f"  Error {well.bro_id}: {exc}")

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
