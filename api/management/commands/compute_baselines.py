from datetime import datetime
from typing import Any

import numpy as np
from django.conf import settings
from django.db import models
from django.core.management.base import BaseCommand
from django.utils import timezone as django_timezone

from api.models import IngestRun, IngestRunStatus, PeriodType, Well, WellBaseline
from api.management.commands.fetch_measurements import (
    TokenBucket,
    _fetch_gld,
)  # noqa: E402

GLD_BASE_URL = "https://publiek.broservices.nl/gm/gld/v1/objects"
PERCENTILES = [5, 10, 25, 50, 75, 90, 95]


def _compute_and_save_baselines(
    well: Well,
    observations: list[tuple[datetime, float, str]],
    period_type: str,
    min_years: int,
) -> int:
    """Compute per-period percentile baselines for one well. Returns number saved."""
    if not observations:
        return 0

    all_dates = [ts.date() for ts, _, _ in observations]
    values = [v for _, v, _ in observations]

    baseline_start = min(all_dates)
    baseline_end = max(all_dates)

    if period_type == PeriodType.WEEK:
        groups: dict[int, list[float]] = {}
        for d, v in zip(all_dates, values):
            week = d.isocalendar()[1]
            groups.setdefault(week, []).append(v)
        period_range = range(1, 54)
    else:
        groups = {}
        for d, v in zip(all_dates, values):
            groups.setdefault(d.month, []).append(v)
        period_range = range(1, 13)

    saved = 0
    to_upsert = []
    for idx in period_range:
        vals = groups.get(idx, [])
        if len(vals) < min_years:
            continue

        arr = np.array(vals, dtype=float)
        pcts = np.percentile(arr, PERCENTILES)

        to_upsert.append(
            WellBaseline(
                well=well,
                period_type=period_type,
                period_index=idx,
                p5=float(pcts[0]),
                p10=float(pcts[1]),
                p25=float(pcts[2]),
                p50=float(pcts[3]),
                p75=float(pcts[4]),
                p90=float(pcts[5]),
                p95=float(pcts[6]),
                mean=float(arr.mean()),
                std=float(arr.std()),
                sample_count=len(vals),
                baseline_start=baseline_start,
                baseline_end=baseline_end,
            )
        )
        saved += 1

    if to_upsert:
        WellBaseline.objects.bulk_create(
            to_upsert,
            update_conflicts=True,
            unique_fields=["well", "period_type", "period_index"],
            update_fields=[
                "p5",
                "p10",
                "p25",
                "p50",
                "p75",
                "p90",
                "p95",
                "mean",
                "std",
                "sample_count",
                "baseline_start",
                "baseline_end",
            ],
        )

    return saved


class Command(BaseCommand):
    help = (
        "Compute per-well seasonal baseline percentiles from full BRO history. "
        "Run once initially, then monthly."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--period-type",
            choices=["week", "month"],
            default="week",
            help="Granularity for the seasonal baseline.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Only process N wells (0 = all, for testing).",
        )
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            help="Skip wells that already have baselines.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        run = IngestRun.objects.create(kind="compute_baselines")
        errors: list[str] = []
        rate = getattr(settings, "BRO_RATE_LIMIT_RPS", 3)
        min_years = getattr(settings, "SGI_MIN_YEARS", 8)
        bucket = TokenBucket(rate)
        period_type = options["period_type"]
        limit = options["limit"]
        skip_existing = options["skip_existing"]
        processed = 0

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
        if skip_existing:
            wells_with_baselines = (
                WellBaseline.objects.filter(period_type=period_type)
                .values_list("well_id", flat=True)
                .distinct()
            )
            wells = wells.exclude(id__in=wells_with_baselines)
        if limit:
            wells = wells[:limit]

        total = wells.count()
        self.stdout.write(
            f"Computing {period_type} baselines for {total} wells "
            f"(min {min_years} samples/period)..."
        )

        for well in wells.iterator(chunk_size=100):
            if not well.gld_bro_id:
                continue
            try:
                # Fetch full history (no date filter) to compute the baseline
                observations = _fetch_gld(well.gld_bro_id, since=None, bucket=bucket)
                saved = _compute_and_save_baselines(
                    well, observations, period_type, min_years
                )
                processed += 1

                if processed % 50 == 0:
                    self.stdout.write(
                        f"  {processed}/{total} (last: {well.bro_id}, {saved} periods)"
                    )

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
                f"Done. {processed} wells processed, {len(errors)} errors."
            )
        )
