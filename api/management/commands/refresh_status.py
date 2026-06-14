from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone as django_timezone

from api.models import (
    Classification,
    IngestRun,
    IngestRunStatus,
    PeriodType,
    WellBaseline,
    WellStatus,
)


def _interpolate_percentile(value: float, baseline: WellBaseline) -> float:
    """Linear interpolation of value's percentile rank within stored baseline percentile points."""
    pts = [
        (baseline.p5, 0.05),
        (baseline.p10, 0.10),
        (baseline.p25, 0.25),
        (baseline.p50, 0.50),
        (baseline.p75, 0.75),
        (baseline.p90, 0.90),
        (baseline.p95, 0.95),
    ]
    if value <= pts[0][0]:
        return 0.0
    if value >= pts[-1][0]:
        return 1.0
    for i in range(len(pts) - 1):
        lo_val, lo_pct = pts[i]
        hi_val, hi_pct = pts[i + 1]
        if lo_val <= value <= hi_val:
            if hi_val == lo_val:
                return lo_pct
            return lo_pct + (hi_pct - lo_pct) * (value - lo_val) / (hi_val - lo_val)
    return 0.5


def _classify(percentile: float, thresholds: dict) -> str:
    if percentile < thresholds["very_low"]:
        return Classification.VERY_LOW
    if percentile < thresholds["low"]:
        return Classification.LOW
    if percentile < thresholds["normal"]:
        return Classification.NORMAL
    if percentile < thresholds["high"]:
        return Classification.HIGH
    return Classification.VERY_HIGH


class Command(BaseCommand):
    help = "Recompute classification and staleness for all wells from cached baselines."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--period-type",
            choices=["week", "month"],
            default="week",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        run = IngestRun.objects.create(kind="refresh_status")
        errors: list[str] = []
        stale_days = getattr(settings, "STALE_THRESHOLD_DAYS", 35)
        thresholds = getattr(
            settings,
            "SGI_THRESHOLDS",
            {
                "very_low": 0.10,
                "low": 0.25,
                "normal": 0.75,
                "high": 0.90,
            },
        )
        period_type = options["period_type"]
        now = django_timezone.now()
        processed = 0

        statuses = (
            WellStatus.objects.select_related("well")
            .filter(latest_value_m_nap__isnull=False)
            .iterator(chunk_size=500)
        )

        to_update: list[WellStatus] = []

        for status in statuses:
            try:
                if not status.latest_measured_at:
                    continue

                if period_type == PeriodType.WEEK:
                    period_index = status.latest_measured_at.isocalendar()[1]
                else:
                    period_index = status.latest_measured_at.month

                try:
                    baseline = WellBaseline.objects.get(
                        well=status.well,
                        period_type=period_type,
                        period_index=period_index,
                    )
                except WellBaseline.DoesNotExist:
                    status.classification = Classification.UNKNOWN
                    status.percentile = None
                    age = now - status.latest_measured_at
                    status.is_stale = age.days > stale_days
                    to_update.append(status)
                    continue

                pct = _interpolate_percentile(status.latest_value_m_nap, baseline)
                status.percentile = pct
                status.classification = _classify(pct, thresholds)
                age = now - status.latest_measured_at
                status.is_stale = age.days > stale_days
                to_update.append(status)
                processed += 1

                if len(to_update) >= 500:
                    WellStatus.objects.bulk_update(
                        to_update,
                        ["classification", "percentile", "is_stale"],
                    )
                    to_update = []

            except Exception as exc:
                errors.append(f"{status.well_id}: {exc}")

        if to_update:
            WellStatus.objects.bulk_update(
                to_update,
                ["classification", "percentile", "is_stale"],
            )

        run.wells_processed = processed
        run.finished_at = django_timezone.now()
        run.errors_json = errors
        run.status = IngestRunStatus.SUCCESS if not errors else IngestRunStatus.FAILED
        run.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {processed} wells refreshed, {len(errors)} errors."
            )
        )
