from django.contrib.gis.db import models
from django.db.models import UniqueConstraint


class Well(models.Model):
    bro_id = models.CharField(max_length=40, unique=True, db_index=True)
    gld_bro_id = models.CharField(max_length=40, blank=True, db_index=True)
    research_last_date = models.DateField(null=True, blank=True, db_index=True)
    tube_number = models.PositiveSmallIntegerField(default=1)
    nitg_code = models.CharField(max_length=20, blank=True)
    name = models.CharField(max_length=120, blank=True)
    location = models.PointField(srid=4326)
    ground_level_m = models.FloatField(null=True, blank=True)
    tube_top_m = models.FloatField(null=True, blank=True)
    screen_top_m = models.FloatField(null=True, blank=True)
    screen_bottom_m = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    pdok_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["bro_id"])]

    def __str__(self) -> str:
        return self.bro_id


class Measurement(models.Model):
    well = models.ForeignKey(
        Well, on_delete=models.CASCADE, related_name="measurements", db_index=True
    )
    measured_at = models.DateTimeField(db_index=True)
    value_m_nap = models.FloatField()
    quality = models.CharField(max_length=40, blank=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["well", "measured_at"], name="unique_well_measured_at"
            )
        ]
        indexes = [models.Index(fields=["well", "measured_at"])]

    def __str__(self) -> str:
        return f"{self.well_id} @ {self.measured_at}"


class PeriodType(models.TextChoices):
    WEEK = "week", "Week"
    MONTH = "month", "Month"


class WellBaseline(models.Model):
    well = models.ForeignKey(
        Well, on_delete=models.CASCADE, related_name="baselines", db_index=True
    )
    period_type = models.CharField(
        max_length=5, choices=PeriodType.choices, default=PeriodType.WEEK
    )
    period_index = models.PositiveSmallIntegerField()
    p5 = models.FloatField()
    p10 = models.FloatField()
    p25 = models.FloatField()
    p50 = models.FloatField()
    p75 = models.FloatField()
    p90 = models.FloatField()
    p95 = models.FloatField()
    mean = models.FloatField()
    std = models.FloatField()
    sample_count = models.PositiveIntegerField()
    baseline_start = models.DateField()
    baseline_end = models.DateField()

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["well", "period_type", "period_index"],
                name="unique_well_period",
            )
        ]
        indexes = [models.Index(fields=["well", "period_type", "period_index"])]

    def __str__(self) -> str:
        return f"{self.well_id} {self.period_type} {self.period_index}"


class Classification(models.TextChoices):
    VERY_LOW = "very_low", "Very low"
    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"
    VERY_HIGH = "very_high", "Very high"
    UNKNOWN = "unknown", "Unknown"


class WellStatus(models.Model):
    well = models.OneToOneField(
        Well, on_delete=models.CASCADE, related_name="status", primary_key=True
    )
    latest_value_m_nap = models.FloatField(null=True, blank=True)
    latest_measured_at = models.DateTimeField(null=True, blank=True)
    percentile = models.FloatField(null=True, blank=True)
    classification = models.CharField(
        max_length=10,
        choices=Classification.choices,
        default=Classification.UNKNOWN,
    )
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    is_stale = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"{self.well_id}: {self.classification}"


class IngestRunStatus(models.TextChoices):
    RUNNING = "running", "Running"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"


class IngestRun(models.Model):
    kind = models.CharField(max_length=40)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    wells_processed = models.PositiveIntegerField(default=0)
    errors_json = models.JSONField(default=list)
    status = models.CharField(
        max_length=10,
        choices=IngestRunStatus.choices,
        default=IngestRunStatus.RUNNING,
    )

    class Meta:
        indexes = [models.Index(fields=["kind", "started_at"])]

    def __str__(self) -> str:
        return f"{self.kind} {self.started_at} ({self.status})"
