from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0003_add_research_last_date"),
    ]

    operations = [
        migrations.AddField(
            model_name="well",
            name="gld_link_checked_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
