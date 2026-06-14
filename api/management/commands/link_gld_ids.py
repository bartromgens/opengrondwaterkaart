import time
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any

import requests
from django.core.management.base import BaseCommand
from django.utils import timezone as django_timezone

from api.management.commands.fetch_measurements import TokenBucket
from api.models import IngestRun, IngestRunStatus, Well

GMW_RELATIONS_URL = "https://publiek.broservices.nl/gm/v1/gmw-relations/{gmw_bro_id}"
GLD_OBJECT_URL = "https://publiek.broservices.nl/gm/gld/v1/objects/{gld_bro_id}"

DSGLD_NS = "http://www.broservices.nl/xsd/dsgld/1.0"


def _get(url: str, bucket: TokenBucket, timeout: int = 15) -> requests.Response | None:
    for attempt in range(4):
        bucket.acquire()
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 404:
                return None
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(2**attempt)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2**attempt)
    return None


def _fetch_gld_id_and_last_date(
    gmw_bro_id: str, bucket: TokenBucket
) -> tuple[str | None, date | None]:
    """
    Two requests per well:
      1. gmw-relations → GLD BRO-ID
      2. GLD object (tiny metadata-only response) → researchLastDate
    """
    resp = _get(GMW_RELATIONS_URL.format(gmw_bro_id=gmw_bro_id), bucket)
    if resp is None:
        return None, None

    gld_id = None
    for tube in resp.json().get("monitoringTubeReferences", []):
        gld_refs = tube.get("gldReferences", [])
        if gld_refs:
            gld_id = gld_refs[0]["broId"]
            break

    if not gld_id:
        return None, None

    # Fetch the GLD object metadata only (no date filter = tiny response with just metadata).
    # The response includes <researchLastDate> without any observation payload.
    resp2 = _get(GLD_OBJECT_URL.format(gld_bro_id=gld_id), bucket)
    if resp2 is None:
        return gld_id, None

    last_date = _parse_research_last_date(resp2.content)
    return gld_id, last_date


def _parse_research_last_date(content: bytes) -> date | None:
    try:
        root = ET.fromstring(content)
        el = root.find(f".//{{{DSGLD_NS}}}researchLastDate")
        if el is not None and el.text:
            return date.fromisoformat(el.text.strip())
    except (ET.ParseError, ValueError):
        pass
    return None


class Command(BaseCommand):
    help = (
        "Populate gld_bro_id and research_last_date on Wells. "
        "Makes 2 requests per well (gmw-relations + GLD object metadata)."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--limit", type=int, default=0, help="Only process N wells (0 = all)."
        )
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            help="Skip wells that already have a gld_bro_id.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        run = IngestRun.objects.create(kind="link_gld_ids")
        errors: list[str] = []
        bucket = TokenBucket(rate=3)
        limit = options["limit"]
        skip_existing = options["skip_existing"]
        processed = 0
        linked = 0

        qs = Well.objects.all().order_by("id")
        if skip_existing:
            qs = qs.filter(gld_bro_id="")
        if limit:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(f"Linking GLD IDs for {total} wells (2 req/well)...")

        to_update: list[Well] = []
        for well in qs.iterator(chunk_size=200):
            try:
                gld_id, last_date = _fetch_gld_id_and_last_date(well.bro_id, bucket)
                if gld_id:
                    well.gld_bro_id = gld_id
                    well.research_last_date = last_date
                    to_update.append(well)
                    linked += 1
                processed += 1

                if len(to_update) >= 200:
                    Well.objects.bulk_update(
                        to_update, ["gld_bro_id", "research_last_date"]
                    )
                    to_update = []

                if processed % 500 == 0:
                    self.stdout.write(f"  {processed}/{total} ({linked} linked)")

            except Exception as exc:
                errors.append(f"{well.bro_id}: {exc}")

        if to_update:
            Well.objects.bulk_update(to_update, ["gld_bro_id", "research_last_date"])

        run.wells_processed = processed
        run.errors_json = errors
        run.status = IngestRunStatus.SUCCESS if not errors else IngestRunStatus.FAILED
        run.finished_at = django_timezone.now()
        run.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {linked}/{processed} wells linked, {len(errors)} errors."
            )
        )
