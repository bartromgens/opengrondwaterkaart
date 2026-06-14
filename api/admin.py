from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import IngestRun, Measurement, Well, WellBaseline, WellStatus


@admin.register(Well)
class WellAdmin(GISModelAdmin):
    list_display = ("bro_id", "tube_number", "nitg_code", "pdok_updated_at")
    search_fields = ("bro_id", "nitg_code")


@admin.register(WellStatus)
class WellStatusAdmin(admin.ModelAdmin):
    list_display = (
        "well",
        "classification",
        "percentile",
        "latest_measured_at",
        "is_stale",
    )
    list_filter = ("classification", "is_stale")


@admin.register(Measurement)
class MeasurementAdmin(admin.ModelAdmin):
    list_display = ("well", "measured_at", "value_m_nap", "quality")
    list_filter = ("quality",)


@admin.register(WellBaseline)
class WellBaselineAdmin(admin.ModelAdmin):
    list_display = ("well", "period_type", "period_index", "sample_count", "p50")


@admin.register(IngestRun)
class IngestRunAdmin(admin.ModelAdmin):
    list_display = ("kind", "started_at", "finished_at", "wells_processed", "status")
    list_filter = ("kind", "status")
