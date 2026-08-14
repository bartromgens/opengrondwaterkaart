from django.urls import path

from .views import (
    health_check,
    meta,
    well_detail,
    well_series,
    wells_geojson,
    wells_overview,
    wells_stats,
)

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("wells/", wells_geojson, name="wells-geojson"),
    path("wells/overview/", wells_overview, name="wells-overview"),
    path("wells/stats/", wells_stats, name="wells-stats"),
    path("wells/<str:bro_id>/", well_detail, name="well-detail"),
    path("wells/<str:bro_id>/series/", well_series, name="well-series"),
    path("meta/", meta, name="meta"),
]
