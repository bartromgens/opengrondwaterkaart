from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone as django_timezone

from api.management.dev_bbox import filter_by_well_dev_bbox, write_dev_bbox_notice
from api.models import IngestRun, IngestRunStatus, Measurement


class Command(BaseCommand):
    help = "Delete measurements older than MEASUREMENT_RETENTION_DAYS."

    def handle(self, *args: Any, **options: Any) -> None:
        run = IngestRun.objects.create(kind="purge_old_measurements")
        retention_days = getattr(settings, "MEASUREMENT_RETENTION_DAYS", 365)
        cutoff = django_timezone.now() - timedelta(days=retention_days)

        measurements = filter_by_well_dev_bbox(
            Measurement.objects.filter(measured_at__lt=cutoff)
        )
        write_dev_bbox_notice(self.stdout)

        deleted, _ = measurements.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted} measurements older than {cutoff.date()}."
            )
        )

        run.wells_processed = deleted
        run.finished_at = django_timezone.now()
        run.status = IngestRunStatus.SUCCESS
        run.save()
