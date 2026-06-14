from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0006_measurement_schema"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="well",
            name="gld_link_checked_at",
        ),
    ]
