from collections import defaultdict
from datetime import datetime, timezone

from django.db import migrations


def _migrate_to_daily_averages(apps, schema_editor):
    Measurement = apps.get_model("api", "Measurement")

    day_values: dict[tuple[int, object], list[float]] = defaultdict(list)
    for m in Measurement.objects.exclude(quality="afgekeurd").values(
        "well_id", "measured_at", "value_m_nap"
    ):
        d = m["measured_at"].astimezone(timezone.utc).date()
        day_values[(m["well_id"], d)].append(m["value_m_nap"])

    Measurement.objects.all().delete()

    new_rows = [
        Measurement(
            well_id=well_id,
            measured_at=datetime(d.year, d.month, d.day, tzinfo=timezone.utc),
            value_m_nap=sum(vals) / len(vals),
            quality="",
        )
        for (well_id, d), vals in day_values.items()
    ]
    Measurement.objects.bulk_create(new_rows, batch_size=1000)


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0004_add_gld_link_checked_at"),
    ]

    operations = [
        migrations.RunPython(
            _migrate_to_daily_averages,
            migrations.RunPython.noop,
        ),
    ]
