from typing import Any

from django.core.management.base import BaseCommand

from api.frequency import refresh_well_frequencies


class Command(BaseCommand):
    help = "Store measurement frequency on each well from consecutive date gaps."

    def handle(self, *args: Any, **options: Any) -> None:
        count = refresh_well_frequencies()
        self.stdout.write(f"Stored frequency for {count} wells.")
