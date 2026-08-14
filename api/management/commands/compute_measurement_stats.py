from typing import Any

from django.core.management.base import BaseCommand

from api.measurement_summary import refresh_well_measurement_stats


class Command(BaseCommand):
    help = "Store first/last measurement date and count on each well."

    def handle(self, *args: Any, **options: Any) -> None:
        count = refresh_well_measurement_stats()
        self.stdout.write(f"Stored measurement stats for {count} wells.")
