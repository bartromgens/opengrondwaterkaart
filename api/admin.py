from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import (
    IngestRun,
    Measurement,
    Organization,
    MonitoringNetwork,
    Well,
    WellBaseline,
)


@admin.register(Well)
class WellAdmin(GISModelAdmin):
    list_display = (
        "bro_id",
        "gld_bro_id",
        "name",
        "tube_number",
        "nitg_code",
        "research_first_date",
        "research_last_date",
        "measurement_frequency",
        "well_construction_date",
        "initial_function",
        "number_of_monitoring_tubes",
        "location_coords",
        "ground_level_m",
        "tube_top_m",
        "screen_top_m",
        "screen_bottom_m",
        "owner_kvk",
        "bronhouder_kvk",
        "created_at",
        "pdok_updated_at",
    )
    search_fields = ("bro_id", "gld_bro_id", "nitg_code", "name")
    list_filter = ("tube_number", "initial_function", "measurement_frequency")
    filter_horizontal = ("monitoring_networks",)

    @admin.display(description="Location")
    def location_coords(self, obj: Well) -> str:
        if obj.location is None:
            return ""
        return f"{obj.location.y:.5f}, {obj.location.x:.5f}"


@admin.register(Measurement)
class MeasurementAdmin(admin.ModelAdmin):
    list_display = ("well", "measured_on", "value_m_nap")
    search_fields = ("well__bro_id",)


@admin.register(WellBaseline)
class WellBaselineAdmin(admin.ModelAdmin):
    list_display = (
        "well",
        "period_type",
        "period_index",
        "p5",
        "p10",
        "p25",
        "p50",
        "p75",
        "p90",
        "p95",
        "mean",
        "std",
        "sample_count",
        "baseline_start",
        "baseline_end",
    )
    list_filter = ("period_type",)
    search_fields = ("well__bro_id",)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("kvk_number", "name", "resolved_at")
    search_fields = ("kvk_number", "name")


@admin.register(MonitoringNetwork)
class MonitoringNetworkAdmin(admin.ModelAdmin):
    list_display = (
        "bro_id",
        "name",
        "monitoring_purpose",
        "groundwater_aspect",
        "start_date",
        "end_date",
    )
    search_fields = ("bro_id", "name")
    list_filter = ("groundwater_aspect", "monitoring_purpose")


@admin.register(IngestRun)
class IngestRunAdmin(admin.ModelAdmin):
    list_display = (
        "kind",
        "started_at",
        "finished_at",
        "wells_processed",
        "status",
        "error_count",
    )
    list_filter = ("kind", "status")

    @admin.display(description="Errors")
    def error_count(self, obj: IngestRun) -> int:
        return len(obj.errors_json)
