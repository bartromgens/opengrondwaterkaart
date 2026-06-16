import logging
from datetime import date
from typing import Any

import numpy as np
from django.conf import settings
from django.db import models
from django.core.management.base import BaseCommand
from django.utils import timezone as django_timezone

from api.management.dev_bbox import filter_wells_by_dev_bbox, write_dev_bbox_notice
from api.models import (
    IngestRun,
    IngestRunStatus,
    Measurement,
    PeriodType,
    Well,
    WellBaseline,
)

PERCENTILES = [5, 10, 25, 50, 75, 90, 95]
logger = logging.getLogger(__name__)


def _load_observations_from_db(well: Well) -> list[tuple[date, float]]:
    return list(
        Measurement.objects.filter(well=well)
        .order_by("measured_on")
        .values_list("measured_on", "value_m_nap")
    )


def _compute_and_save_baselines(
    well: Well,
    observations: list[tuple[date, float]],
    period_type: str,
    min_years: int,
) -> int:
    if not observations:
        return 0

    all_dates = [d for d, _ in observations]
    values = [v for _, v in observations]

    baseline_start = min(all_dates)
    baseline_end = max(all_dates)

    # Group raw measurements by (period_index, year) to get one representative
    # value per year per period.  This ensures the baseline captures inter-annual
    # variation rather than intra-period noise from high-frequency wells.
    if period_type == PeriodType.WEEK:
        year_groups: dict[int, dict[int, list[float]]] = {}
        for d, v in zip(all_dates, values):
            week = d.isocalendar()[1]
            year_groups.setdefault(week, {}).setdefault(d.isocalendar()[0], []).append(
                v
            )
        period_range = range(1, 54)
    else:
        year_groups = {}
        for d, v in zip(all_dates, values):
            year_groups.setdefault(d.month, {}).setdefault(d.year, []).append(v)
        period_range = range(1, 13)

    saved = 0
    to_upsert = []
    for idx in period_range:
        by_year = year_groups.get(idx, {})
        if len(by_year) < min_years:
            continue
        vals = [float(np.mean(readings)) for readings in by_year.values()]

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
        "Compute per-well seasonal baseline percentiles from stored measurements. "
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
        min_years = getattr(settings, "SGI_MIN_YEARS", 8)
        period_type = options["period_type"]
        limit = options["limit"]
        skip_existing = options["skip_existing"]
        processed = 0

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
        if skip_existing:
            wells_with_baselines = (
                WellBaseline.objects.filter(period_type=period_type)
                .values_list("well_id", flat=True)
                .distinct()
            )
            wells = wells.exclude(id__in=wells_with_baselines)
        wells = wells.filter(measurements__isnull=False).distinct()
        if limit:
            wells = wells[:limit]

        total = wells.count()
        logger.info(
            "Computing %s baselines for %d wells (min %d samples/period)...",
            period_type,
            total,
            min_years,
        )

        for well in wells.iterator(chunk_size=100):
            if not well.gld_bro_id:
                continue
            try:
                observations = _load_observations_from_db(well)
                saved = _compute_and_save_baselines(
                    well, observations, period_type, min_years
                )
                processed += 1

                if processed % 50 == 0:
                    logger.info(
                        "  %d/%d (last: %s, %d periods)",
                        processed,
                        total,
                        well.bro_id,
                        saved,
                    )

            except Exception as exc:
                errors.append(f"{well.bro_id}: {exc}")
                logger.error("Error %s: %s", well.bro_id, exc)

        run.wells_processed = processed
        run.finished_at = django_timezone.now()
        run.errors_json = errors
        run.status = IngestRunStatus.SUCCESS if not errors else IngestRunStatus.FAILED
        run.save()

        logger.info(
            "Done. %d wells processed, %d errors.", processed, len(errors)
        )
