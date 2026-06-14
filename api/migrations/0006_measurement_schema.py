from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0005_measurement_daily_average"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="measurement",
            name="unique_well_measured_at",
        ),
        migrations.RemoveIndex(
            model_name="measurement",
            name="api_measure_well_id_13086f_idx",
        ),
        migrations.RemoveField(
            model_name="measurement",
            name="quality",
        ),
        migrations.RenameField(
            model_name="measurement",
            old_name="measured_at",
            new_name="measured_on",
        ),
        migrations.AlterField(
            model_name="measurement",
            name="measured_on",
            field=models.DateField(db_index=True),
        ),
        migrations.AddConstraint(
            model_name="measurement",
            constraint=models.UniqueConstraint(
                fields=["well", "measured_on"], name="unique_well_measured_on"
            ),
        ),
        migrations.AddIndex(
            model_name="measurement",
            index=models.Index(
                fields=["well", "measured_on"],
                name="api_measur_well_id_measured_on_idx",
            ),
        ),
    ]
