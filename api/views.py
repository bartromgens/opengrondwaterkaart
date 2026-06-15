from datetime import date, timedelta

from django.contrib.gis.geos import Polygon
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from .classification import classify_value
from .models import (
    IngestRun,
    IngestRunStatus,
    Measurement,
    PeriodType,
    Well,
    WellBaseline,
)


def _parse_date(request: Request) -> date:
    raw = request.query_params.get("date")
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return timezone.localdate()


def _week_of(d: date) -> int:
    return d.isocalendar()[1]


def _baseline_for_week(
    well_id: int, week: int, baselines_by_well: dict
) -> "WellBaseline | None":
    return baselines_by_well.get(well_id)


@api_view(["GET"])
def health_check(request: Request) -> Response:
    return Response({"status": "ok"})


def _well_feature(
    well: Well,
    value_m_nap: float | None,
    classification: str | None,
    percentile: float | None,
    selected_date: date,
) -> dict:
    lng, lat = well.location.x, well.location.y
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
        "properties": {
            "id": well.bro_id,
            "classification": classification,
            "percentile": percentile,
            "value_m_nap": value_m_nap,
            "measured_on": (
                selected_date.isoformat() if value_m_nap is not None else None
            ),
        },
    }


@api_view(["GET"])
def wells_geojson(request: Request) -> Response:
    selected_date = _parse_date(request)
    week = _week_of(selected_date)

    one_year_ago = (timezone.now() - timedelta(days=365)).date()
    qs = Well.objects.filter(research_last_date__gte=one_year_ago)

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

    wells = list(qs.only("id", "bro_id", "location"))
    well_ids = [w.id for w in wells]

    measurements = {
        row["well_id"]: row["value_m_nap"]
        for row in Measurement.objects.filter(
            well_id__in=well_ids, measured_on=selected_date
        ).values("well_id", "value_m_nap")
    }

    baselines = {
        row["well_id"]: row
        for row in WellBaseline.objects.filter(
            well_id__in=well_ids,
            period_type=PeriodType.WEEK,
            period_index=week,
        ).values("well_id", "p5", "p10", "p25", "p50", "p75", "p90", "p95")
    }

    features = []
    for well in wells:
        value = measurements.get(well.id)
        baseline_row = baselines.get(well.id)
        classification = None
        percentile = None
        if value is not None and baseline_row is not None:
            baseline_obj = _dict_to_baseline(baseline_row)
            classification, percentile = classify_value(value, baseline_obj)
        features.append(
            _well_feature(well, value, classification, percentile, selected_date)
        )

    return Response({"type": "FeatureCollection", "features": features})


class _DictBaseline:
    """Lightweight stand-in for WellBaseline when reading from .values()."""

    def __init__(self, d: dict) -> None:
        self.p5 = d["p5"]
        self.p10 = d["p10"]
        self.p25 = d["p25"]
        self.p50 = d["p50"]
        self.p75 = d["p75"]
        self.p90 = d["p90"]
        self.p95 = d["p95"]


def _dict_to_baseline(d: dict) -> _DictBaseline:
    return _DictBaseline(d)


@api_view(["GET"])
def well_detail(request: Request, bro_id: str) -> Response:
    try:
        well = Well.objects.get(bro_id=bro_id)
    except Well.DoesNotExist:
        return Response({"error": "Well not found."}, status=404)

    selected_date = _parse_date(request)
    week = _week_of(selected_date)

    measurement = (
        Measurement.objects.filter(well=well, measured_on=selected_date)
        .values("value_m_nap")
        .first()
    )
    value = measurement["value_m_nap"] if measurement else None

    baseline = WellBaseline.objects.filter(
        well=well,
        period_type=PeriodType.WEEK,
        period_index=week,
    ).first()

    classification = None
    percentile = None
    if value is not None and baseline is not None:
        classification, percentile = classify_value(value, baseline)

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
            "value_m_nap": value,
            "measured_on": selected_date.isoformat() if value is not None else None,
            "percentile": percentile,
            "classification": classification,
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
        well = Well.objects.get(bro_id=bro_id)
    except Well.DoesNotExist:
        return Response({"error": "Well not found."}, status=404)

    selected_date = _parse_date(request)
    week = _week_of(selected_date)

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

    baseline = WellBaseline.objects.filter(
        well=well,
        period_type=PeriodType.WEEK,
        period_index=week,
    ).first()

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

    return Response(
        {
            "last_updated": (
                last_run.finished_at.isoformat()
                if last_run and last_run.finished_at
                else None
            ),
            "total_wells": Well.objects.count(),
        }
    )
