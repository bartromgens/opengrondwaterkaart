from datetime import timedelta

from django.contrib.gis.geos import Polygon
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from .models import (
    Classification,
    IngestRun,
    IngestRunStatus,
    Measurement,
    PeriodType,
    Well,
    WellBaseline,
    WellStatus,
)


def _baseline_period_index(status: WellStatus | None) -> int:
    if status and status.latest_measured_at:
        return status.latest_measured_at.isocalendar()[1]
    return timezone.now().isocalendar()[1]


def _weekly_baseline(well: Well, status: WellStatus | None) -> WellBaseline | None:
    return WellBaseline.objects.filter(
        well=well,
        period_type=PeriodType.WEEK,
        period_index=_baseline_period_index(status),
    ).first()


@api_view(["GET"])
def health_check(request: Request) -> Response:
    return Response({"status": "ok"})


def _well_feature(well: Well) -> dict:
    lng, lat = well.location.x, well.location.y
    status: WellStatus | None = getattr(well, "status", None)
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
        "properties": {
            "id": well.bro_id,
            "classification": (
                status.classification if status else Classification.UNKNOWN
            ),
            "percentile": status.percentile if status else None,
            "latest_measured_at": (
                status.latest_measured_at.isoformat()
                if status and status.latest_measured_at
                else None
            ),
            "is_stale": status.is_stale if status else False,
        },
    }


@api_view(["GET"])
def wells_geojson(request: Request) -> Response:
    one_year_ago = (timezone.now() - timedelta(days=365)).date()
    qs = Well.objects.filter(research_last_date__gte=one_year_ago).prefetch_related(
        "status"
    )

    bbox_param = request.query_params.get("bbox")
    if bbox_param:
        try:
            minx, miny, maxx, maxy = [float(v) for v in bbox_param.split(",")]
            bbox_poly = Polygon.from_bbox((minx, miny, maxx, maxy))
            qs = qs.filter(location__within=bbox_poly)
        except (ValueError, TypeError):
            return Response(
                {"error": "Invalid bbox. Expected minx,miny,maxx,maxy."}, status=400
            )

    features = [_well_feature(w) for w in qs.iterator(chunk_size=1000)]
    return Response({"type": "FeatureCollection", "features": features})


@api_view(["GET"])
def well_detail(request: Request, bro_id: str) -> Response:
    try:
        well = Well.objects.select_related("status").get(bro_id=bro_id)
    except Well.DoesNotExist:
        return Response({"error": "Well not found."}, status=404)

    status = getattr(well, "status", None)
    baseline = _weekly_baseline(well, status)

    data: dict = {
        "bro_id": well.bro_id,
        "tube_number": well.tube_number,
        "nitg_code": well.nitg_code,
        "name": well.name,
        "location": {"lng": well.location.x, "lat": well.location.y},
        "ground_level_m": well.ground_level_m,
        "tube_top_m": well.tube_top_m,
        "screen_top_m": well.screen_top_m,
        "screen_bottom_m": well.screen_bottom_m,
        "status": {
            "latest_value_m_nap": status.latest_value_m_nap if status else None,
            "latest_measured_at": (
                status.latest_measured_at.isoformat()
                if status and status.latest_measured_at
                else None
            ),
            "percentile": status.percentile if status else None,
            "classification": (
                status.classification if status else Classification.UNKNOWN
            ),
            "last_fetched_at": (
                status.last_fetched_at.isoformat()
                if status and status.last_fetched_at
                else None
            ),
            "is_stale": status.is_stale if status else True,
        },
        "baseline": (
            {
                "p10": baseline.p10,
                "p25": baseline.p25,
                "p50": baseline.p50,
                "p75": baseline.p75,
                "p90": baseline.p90,
                "sample_count": baseline.sample_count,
                "baseline_start": baseline.baseline_start.isoformat(),
                "baseline_end": baseline.baseline_end.isoformat(),
            }
            if baseline
            else None
        ),
    }
    return Response(data)


@api_view(["GET"])
def well_series(request: Request, bro_id: str) -> Response:
    try:
        well = Well.objects.select_related("status").get(bro_id=bro_id)
    except Well.DoesNotExist:
        return Response({"error": "Well not found."}, status=404)

    status = getattr(well, "status", None)
    full = request.query_params.get("full", "")
    now = timezone.now()

    if full:
        measurements_qs = Measurement.objects.filter(well=well).order_by("measured_on")
    else:
        from_dt = now - timedelta(days=365)
        to_dt = now

        from_param = request.query_params.get("from")
        to_param = request.query_params.get("to")
        try:
            if from_param:
                from_dt = timezone.datetime.fromisoformat(from_param).replace(
                    tzinfo=timezone.utc
                )
            if to_param:
                to_dt = timezone.datetime.fromisoformat(to_param).replace(
                    tzinfo=timezone.utc
                )
        except ValueError:
            return Response({"error": "Invalid date format. Use ISO 8601."}, status=400)

        measurements_qs = Measurement.objects.filter(
            well=well,
            measured_on__gte=from_dt.date(),
            measured_on__lte=to_dt.date(),
        ).order_by("measured_on")

    series = [
        {"t": d.isoformat(), "v": v}
        for d, v in measurements_qs.values_list("measured_on", "value_m_nap")
    ]

    baseline = _weekly_baseline(well, status)

    weekly_baselines = [
        {"week": idx, "p10": p10, "p50": p50, "p90": p90}
        for idx, p10, p50, p90 in WellBaseline.objects.filter(
            well=well, period_type=PeriodType.WEEK
        )
        .order_by("period_index")
        .values_list("period_index", "p10", "p50", "p90")
    ]

    return Response(
        {
            "bro_id": bro_id,
            "series": series,
            "baseline_bands": (
                {
                    "p10": baseline.p10,
                    "p50": baseline.p50,
                    "p90": baseline.p90,
                }
                if baseline
                else None
            ),
            "weekly_baselines": weekly_baselines,
        }
    )


@api_view(["GET"])
def meta(request: Request) -> Response:
    last_run = (
        IngestRun.objects.filter(
            kind="fetch_measurements", status=IngestRunStatus.SUCCESS
        )
        .order_by("-finished_at")
        .first()
    )

    counts: dict[str, int] = {}
    for row in WellStatus.objects.values("classification").order_by():
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1

    return Response(
        {
            "last_updated": (
                last_run.finished_at.isoformat()
                if last_run and last_run.finished_at
                else None
            ),
            "classification_counts": counts,
            "total_wells": Well.objects.count(),
        }
    )
