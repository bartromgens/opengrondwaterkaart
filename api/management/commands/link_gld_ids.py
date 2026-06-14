import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterator

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone as django_timezone

from api.management.commands.fetch_measurements import (
    TokenBucket,
    _MAX_GET_ATTEMPTS,
    _retry_delay,
    _warn_rate_limited,
)
from api.management.dev_bbox import filter_wells_by_dev_bbox, write_dev_bbox_notice
from api.models import IngestRun, IngestRunStatus, Well

GMW_RELATIONS_URL = "https://publiek.broservices.nl/gm/v1/gmw-relations/{gmw_bro_id}"
GLD_OBJECT_URL = "https://publiek.broservices.nl/gm/gld/v1/objects/{gld_bro_id}"

DSGLD_NS = "http://www.broservices.nl/xsd/dsgld/1.0"

UPDATE_FIELDS = ["gld_bro_id", "research_last_date", "gld_link_checked_at"]
CHUNK_SIZE = 200


def _pending_wells_filter(qs: Any, cutoff: Any) -> Any:
    return qs.filter(
        Q(gld_bro_id__gt="", research_last_date__isnull=True)
        | Q(gld_bro_id="", gld_link_checked_at__isnull=True)
        | Q(gld_bro_id="", gld_link_checked_at__lt=cutoff)
    )


def _get(
    url: str, bucket: TokenBucket, timeout: int = 15
) -> tuple[requests.Response | None, float]:
    elapsed = 0.0
    last_status: int | None = None
    for attempt in range(_MAX_GET_ATTEMPTS):
        bucket.acquire()
        try:
            start = time.perf_counter()
            resp = requests.get(url, timeout=timeout)
            elapsed += time.perf_counter() - start
            last_status = resp.status_code
            if resp.status_code == 404:
                return None, elapsed
            if resp.status_code == 429 or resp.status_code >= 500:
                delay = _retry_delay(attempt, resp.status_code)
                if resp.status_code == 429:
                    _warn_rate_limited(url, attempt, delay)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp, elapsed
        except requests.RequestException:
            if attempt == _MAX_GET_ATTEMPTS - 1:
                raise
            time.sleep(_retry_delay(attempt, last_status))
    return None, elapsed


def _fetch_gld_id_and_last_date(
    gmw_bro_id: str,
    bucket: TokenBucket,
    *,
    known_gld_id: str | None = None,
) -> tuple[str | None, date | None, list[float]]:
    req_times: list[float] = []
    gld_id = known_gld_id

    if not gld_id:
        resp, elapsed = _get(GMW_RELATIONS_URL.format(gmw_bro_id=gmw_bro_id), bucket)
        req_times.append(elapsed)
        if resp is None:
            return None, None, req_times

        for tube in resp.json().get("monitoringTubeReferences", []):
            gld_refs = tube.get("gldReferences", [])
            if gld_refs:
                gld_id = gld_refs[0]["broId"]
                break

        if not gld_id:
            return None, None, req_times

    resp2, elapsed2 = _get(GLD_OBJECT_URL.format(gld_bro_id=gld_id), bucket)
    req_times.append(elapsed2)
    if resp2 is None:
        return gld_id, None, req_times

    last_date = _parse_research_last_date(resp2.content)
    return gld_id, last_date, req_times


def _parse_research_last_date(content: bytes) -> date | None:
    try:
        root = ET.fromstring(content)
        el = root.find(f".//{{{DSGLD_NS}}}researchLastDate")
        if el is not None and el.text:
            return date.fromisoformat(el.text.strip())
    except (ET.ParseError, ValueError):
        pass
    return None


@dataclass
class LinkResult:
    well: Well
    gld_id: str | None
    last_date: date | None
    req_times: list[float]
    error: str | None = None


def _link_well(
    well: Well,
    bucket: TokenBucket,
    *,
    known_gld_id: str | None,
) -> LinkResult:
    try:
        gld_id, last_date, req_times = _fetch_gld_id_and_last_date(
            well.bro_id, bucket, known_gld_id=known_gld_id
        )
        return LinkResult(
            well=well,
            gld_id=gld_id,
            last_date=last_date,
            req_times=req_times,
        )
    except Exception as exc:
        return LinkResult(
            well=well,
            gld_id=None,
            last_date=None,
            req_times=[],
            error=str(exc),
        )


def _well_chunks(qs: Any, chunk_size: int) -> Iterator[list[Well]]:
    chunk: list[Well] = []
    for well in qs.iterator(chunk_size=chunk_size):
        chunk.append(well)
        if len(chunk) >= chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _link_wells_parallel(
    wells: list[Well],
    bucket: TokenBucket,
    *,
    skip_existing: bool,
    workers: int,
) -> list[LinkResult]:
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                _link_well,
                well,
                bucket,
                known_gld_id=(
                    well.gld_bro_id if skip_existing and well.gld_bro_id else None
                ),
            )
            for well in wells
        ]
        return [future.result() for future in as_completed(futures)]


class Command(BaseCommand):
    help = (
        "Populate gld_bro_id and research_last_date on Wells. "
        "Makes up to 2 requests per well (gmw-relations + GLD object metadata)."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--limit", type=int, default=0, help="Only process N wells (0 = all)."
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-fetch all wells, including those already linked.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        run = IngestRun.objects.create(kind="link_gld_ids")
        errors: list[str] = []
        rate = getattr(settings, "BRO_RATE_LIMIT_RPS", 3)
        workers = getattr(settings, "BRO_PARALLEL_WORKERS", max(3, int(rate * 2)))
        bucket = TokenBucket(rate=rate)
        limit = options["limit"]
        skip_existing = not options["force"]
        processed = 0
        linked = 0
        no_link = 0
        request_times: list[float] = []
        retry_days = getattr(settings, "GLD_LINK_RETRY_DAYS", 183)

        qs = filter_wells_by_dev_bbox(Well.objects.all().order_by("id"))
        write_dev_bbox_notice(self.stdout)
        if skip_existing:
            cutoff = django_timezone.now() - django_timezone.timedelta(days=retry_days)
            pending_qs = _pending_wells_filter(qs, cutoff)
            fully_linked = qs.filter(
                gld_bro_id__gt="", research_last_date__isnull=False
            ).count()
            no_link_recent = qs.filter(
                gld_bro_id="", gld_link_checked_at__gte=cutoff
            ).count()
            if fully_linked:
                self.stdout.write(f"Skipping {fully_linked} already linked wells")
            if no_link_recent:
                self.stdout.write(
                    f"Skipping {no_link_recent} wells with no GLD link "
                    f"(checked within {retry_days} days)"
                )
            if fully_linked or no_link_recent:
                self.stdout.write("(use --force to reprocess all)")
            qs = pending_qs
        if limit:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(
            f"Linking GLD IDs for {total} wells "
            f"(up to 2 req/well, {workers} workers @ {rate} req/s)..."
        )

        for chunk in _well_chunks(qs, CHUNK_SIZE):
            results = _link_wells_parallel(
                chunk, bucket, skip_existing=skip_existing, workers=workers
            )
            to_update: list[Well] = []
            chunk_req_times: list[float] = []

            for result in results:
                well = result.well
                if result.error:
                    errors.append(f"{well.bro_id}: {result.error}")
                    processed += 1
                    continue

                chunk_req_times.extend(result.req_times)
                request_times.extend(result.req_times)
                if result.gld_id:
                    well.gld_bro_id = result.gld_id
                    well.research_last_date = result.last_date
                    well.gld_link_checked_at = None
                    linked += 1
                else:
                    well.gld_link_checked_at = django_timezone.now()
                    no_link += 1
                to_update.append(well)
                processed += 1

            if to_update:
                Well.objects.bulk_update(to_update, UPDATE_FIELDS)

            chunk_avg = (
                sum(chunk_req_times) / len(chunk_req_times) if chunk_req_times else 0
            )
            avg = sum(request_times) / len(request_times) if request_times else 0
            self.stdout.write(
                f"  {processed}/{total} ({linked} linked, "
                f"chunk avg: {chunk_avg:.2f}s, overall avg: {avg:.2f}s)"
            )

        run.wells_processed = processed
        run.errors_json = errors
        run.status = IngestRunStatus.SUCCESS if not errors else IngestRunStatus.FAILED
        run.finished_at = django_timezone.now()
        run.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {linked}/{processed} wells linked, "
                f"{no_link} marked no link, {len(errors)} errors."
            )
        )
