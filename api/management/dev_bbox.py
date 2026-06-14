from typing import Any

from django.conf import settings
from django.contrib.gis.geos import Point, Polygon


def get_dev_bbox() -> tuple[float, float, float, float] | None:
    return getattr(settings, "DEV_WELL_BBOX", None)


def dev_bbox_polygon() -> Polygon | None:
    bbox = get_dev_bbox()
    if bbox is None:
        return None
    return Polygon.from_bbox(bbox)


def filter_wells_by_dev_bbox(qs: Any) -> Any:
    poly = dev_bbox_polygon()
    if poly is None:
        return qs
    return qs.filter(location__within=poly)


def filter_by_well_dev_bbox(qs: Any) -> Any:
    poly = dev_bbox_polygon()
    if poly is None:
        return qs
    return qs.filter(well__location__within=poly)


def point_in_dev_bbox(lon: float, lat: float) -> bool:
    poly = dev_bbox_polygon()
    if poly is None:
        return True
    return poly.contains(Point(lon, lat, srid=4326))


def write_dev_bbox_notice(stdout: Any) -> None:
    bbox = get_dev_bbox()
    if bbox:
        stdout.write(f"Dev bbox filter active: {bbox}")
