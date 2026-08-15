from django.urls import path

from .views import (
    admin_log_content,
    admin_logs,
    admin_status,
    health_check,
    meta,
    monitoring_networks,
    well_detail,
    well_series,
    wells_geojson,
    wells_overview,
    wells_stats,
)

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("networks/", monitoring_networks, name="monitoring-networks"),
    path("wells/", wells_geojson, name="wells-geojson"),
    path("wells/overview/", wells_overview, name="wells-overview"),
    path("wells/stats/", wells_stats, name="wells-stats"),
    path("wells/<str:bro_id>/", well_detail, name="well-detail"),
    path("wells/<str:bro_id>/series/", well_series, name="well-series"),
    path("meta/", meta, name="meta"),
    path("admin/status/", admin_status, name="admin-status"),
    path("admin/logs/", admin_logs, name="admin-logs"),
    path("admin/logs/<str:name>/", admin_log_content, name="admin-log-content"),
]
