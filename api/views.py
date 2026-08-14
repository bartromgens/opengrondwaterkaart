from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Iterable

from django.contrib.gis.geos import Polygon
from django.db.models import Count, F, Max, Min, Prefetch
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from .classification import classify_value
from .models import (
    IngestRun,
    IngestRunStatus,
    Measurement,
    MonitoringNetwork,
    Organization,
    PeriodType,
    Well,
    WellBaseline,
)

KVK_SEARCH_URL = "https://www.kvk.nl/zoeken/?kvknummer="

FREQUENCY_THRESHOLDS_DAYS = (
    (1.5, "daily"),
    (9, "weekly"),
    (45, "monthly"),
    (120, "quarterly"),
    (450, "yearly"),
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


def _organization_payload(
    kvk: str, organizations_by_kvk: dict[str, Organization]
) -> dict | None:
    if not kvk:
        return None
    org = organizations_by_kvk.get(kvk)
    return {
        "kvk": kvk,
        "name": org.name if org else None,
        "kvk_url": f"{KVK_SEARCH_URL}{kvk}",
    }


@api_view(["GET"])
def well_detail(request: Request, bro_id: str) -> Response:
    try:
        well = Well.objects.prefetch_related("monitoring_networks").get(bro_id=bro_id)
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

    org_kvks = [kvk for kvk in (well.owner_kvk, well.bronhouder_kvk) if kvk]
    organizations_by_kvk = {
        org.kvk_number: org
        for org in Organization.objects.filter(kvk_number__in=org_kvks)
    }

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
        "well_construction_date": (
            well.well_construction_date.isoformat()
            if well.well_construction_date
            else None
        ),
        "initial_function": well.initial_function or None,
        "number_of_monitoring_tubes": well.number_of_monitoring_tubes,
        "research_first_date": (
            well.research_first_date.isoformat() if well.research_first_date else None
        ),
        "research_last_date": (
            well.research_last_date.isoformat() if well.research_last_date else None
        ),
        "monitoring_networks": [
            {
                "bro_id": network.bro_id,
                "name": network.name or network.bro_id,
                "monitoring_purpose": network.monitoring_purpose or None,
                "groundwater_aspect": network.groundwater_aspect or None,
                "bro_object_url": network.bro_object_url or None,
            }
            for network in well.monitoring_networks.all().order_by("name", "bro_id")
        ],
        "owner": _organization_payload(well.owner_kvk, organizations_by_kvk),
        "bronhouder": _organization_payload(well.bronhouder_kvk, organizations_by_kvk),
        "bro_object_url": well.bro_object_url or None,
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


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _frequency_from_median_gap(median_gap_days: float | None) -> str | None:
    if median_gap_days is None:
        return None
    for max_gap, label in FREQUENCY_THRESHOLDS_DAYS:
        if median_gap_days <= max_gap:
            return label
    return "irregular"


def _measurement_frequency(dates: list[date]) -> str | None:
    if len(dates) < 2:
        return None
    ordered = sorted(dates)
    gaps = [float((ordered[i] - ordered[i - 1]).days) for i in range(1, len(ordered))]
    return _frequency_from_median_gap(_median(gaps))


def _frequencies_by_well_id(well_ids: Iterable[int]) -> dict[int, str | None]:
    ids = list(well_ids)
    if not ids:
        return {}
    dates_by_well: dict[int, list[date]] = defaultdict(list)
    for well_id, measured_on in (
        Measurement.objects.filter(well_id__in=ids)
        .order_by("well_id", "measured_on")
        .values_list("well_id", "measured_on")
        .iterator(chunk_size=10_000)
    ):
        dates_by_well[well_id].append(measured_on)
    return {
        well_id: _measurement_frequency(dates_by_well.get(well_id, []))
        for well_id in ids
    }


def _monitoring_networks_by_well_id(
    well_ids: Iterable[int],
) -> dict[int, list[dict[str, str]]]:
    ids = list(well_ids)
    if not ids:
        return {}
    networks = Prefetch(
        "monitoring_networks",
        queryset=MonitoringNetwork.objects.order_by("name", "bro_id"),
    )
    result: dict[int, list[dict[str, str]]] = {well_id: [] for well_id in ids}
    for well in Well.objects.filter(id__in=ids).prefetch_related(networks):
        result[well.id] = [
            {"bro_id": network.bro_id, "name": network.name or network.bro_id}
            for network in well.monitoring_networks.all()
        ]
    return result


def _all_frequencies_by_well_id() -> dict[int, str | None]:
    """Median consecutive gap per well via Postgres window + percentile_cont."""
    from django.db import connection

    sql = """
        WITH gaps AS (
            SELECT
                well_id,
                measured_on - LAG(measured_on) OVER (
                    PARTITION BY well_id ORDER BY measured_on
                ) AS gap_days
            FROM api_measurement
        )
        SELECT
            well_id,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY gap_days) AS median_gap
        FROM gaps
        WHERE gap_days IS NOT NULL
        GROUP BY well_id
    """
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return {
            well_id: _frequency_from_median_gap(float(median_gap))
            for well_id, median_gap in cursor.fetchall()
        }


OVERVIEW_ORDER_FIELDS = {
    "name",
    "bro_id",
    "nitg_code",
    "well_construction_date",
    "initial_function",
    "number_of_monitoring_tubes",
    "research_first_date",
    "research_last_date",
    "first_measured_on",
    "last_measured_on",
    "measurement_count",
}
OVERVIEW_DEFAULT_ORDERING = "-last_measured_on"
OVERVIEW_DEFAULT_PAGE_SIZE = 50
OVERVIEW_MAX_PAGE_SIZE = 200


def _overview_ordering(request: Request) -> tuple[str, str]:
    """Return (ordering, resolved db expression) for the wells overview query.

    Falls back to the default ordering for unknown/missing fields. Wells
    without any measurements are always sorted after wells with data,
    regardless of sort direction.
    """
    raw = request.query_params.get("ordering", OVERVIEW_DEFAULT_ORDERING)
    field = raw.lstrip("-")
    if field not in OVERVIEW_ORDER_FIELDS:
        raw, field = OVERVIEW_DEFAULT_ORDERING, OVERVIEW_DEFAULT_ORDERING.lstrip("-")
    descending = raw.startswith("-")

    if field in (
        "first_measured_on",
        "last_measured_on",
        "well_construction_date",
        "research_first_date",
        "research_last_date",
    ):
        expr = (
            F(field).desc(nulls_last=True)
            if descending
            else F(field).asc(nulls_last=True)
        )
    else:
        expr = f"-{field}" if descending else field
    return raw, expr


@api_view(["GET"])
def wells_overview(request: Request) -> Response:
    ordering, order_expr = _overview_ordering(request)

    try:
        page = max(int(request.query_params.get("page", 1)), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(
            request.query_params.get("page_size", OVERVIEW_DEFAULT_PAGE_SIZE)
        )
    except (TypeError, ValueError):
        page_size = OVERVIEW_DEFAULT_PAGE_SIZE
    page_size = min(max(page_size, 1), OVERVIEW_MAX_PAGE_SIZE)

    qs = Well.objects.annotate(
        first_measured_on=Min("measurements__measured_on"),
        last_measured_on=Max("measurements__measured_on"),
        measurement_count=Count("measurements"),
    ).order_by(order_expr, "bro_id")

    total = qs.count()
    start = (page - 1) * page_size
    rows = list(
        qs[start : start + page_size].values(
            "id",
            "bro_id",
            "nitg_code",
            "name",
            "well_construction_date",
            "initial_function",
            "number_of_monitoring_tubes",
            "research_first_date",
            "research_last_date",
            "first_measured_on",
            "last_measured_on",
            "measurement_count",
        )
    )
    frequencies = _frequencies_by_well_id(
        row["id"] for row in rows if row["measurement_count"] >= 2
    )
    networks_by_well_id = _monitoring_networks_by_well_id(row["id"] for row in rows)

    results = [
        {
            "bro_id": row["bro_id"],
            "nitg_code": row["nitg_code"],
            "name": row["name"],
            "well_construction_date": (
                row["well_construction_date"].isoformat()
                if row["well_construction_date"]
                else None
            ),
            "initial_function": row["initial_function"] or None,
            "number_of_monitoring_tubes": row["number_of_monitoring_tubes"],
            "research_first_date": (
                row["research_first_date"].isoformat()
                if row["research_first_date"]
                else None
            ),
            "research_last_date": (
                row["research_last_date"].isoformat()
                if row["research_last_date"]
                else None
            ),
            "monitoring_networks": networks_by_well_id.get(row["id"], []),
            "first_measured_on": (
                row["first_measured_on"].isoformat()
                if row["first_measured_on"]
                else None
            ),
            "last_measured_on": (
                row["last_measured_on"].isoformat() if row["last_measured_on"] else None
            ),
            "measurement_count": row["measurement_count"],
            "frequency": frequencies.get(row["id"]),
        }
        for row in rows
    ]

    return Response(
        {
            "count": total,
            "page": page,
            "page_size": page_size,
            "ordering": ordering,
            "results": results,
        }
    )


FREQUENCY_DISTRIBUTION_ORDER = [
    "daily",
    "weekly",
    "monthly",
    "quarterly",
    "yearly",
    "irregular",
    "unknown",
    "no_data",
]

# (key, Dutch label, inclusive max age in days; None = open-ended)
AGE_BUCKETS: list[tuple[str, str, int | None]] = [
    ("0_7", "0–7 dagen", 7),
    ("8_30", "8–30 dagen", 30),
    ("31_90", "1–3 maanden", 90),
    ("91_180", "3–6 maanden", 180),
    ("181_365", "6–12 maanden", 365),
    ("366_730", "1–2 jaar", 730),
    ("over_730", ">2 jaar", None),
]


def _age_bucket_key(age_days: int) -> str:
    for key, _label, max_days in AGE_BUCKETS:
        if max_days is None or age_days <= max_days:
            return key
    return AGE_BUCKETS[-1][0]


@api_view(["GET"])
def wells_stats(request: Request) -> Response:
    total_wells = Well.objects.count()
    today = timezone.localdate()

    measurement_stats = list(
        Measurement.objects.values("well_id").annotate(
            last_measured_on=Max("measured_on"),
            measurement_count=Count("id"),
        )
    )
    wells_with_data = len(measurement_stats)
    frequencies = _all_frequencies_by_well_id()

    frequency_counts: Counter = Counter({"no_data": total_wells - wells_with_data})
    age_counts: Counter = Counter()
    newest_measured_on: date | None = None
    for row in measurement_stats:
        if row["measurement_count"] < 2:
            frequency_counts["unknown"] += 1
        else:
            frequency = frequencies.get(row["well_id"]) or "unknown"
            frequency_counts[frequency] += 1

        last_on = row["last_measured_on"]
        age_counts[_age_bucket_key((today - last_on).days)] += 1
        if newest_measured_on is None or last_on > newest_measured_on:
            newest_measured_on = last_on

    newest_measurement_age_days = (
        (today - newest_measured_on).days if newest_measured_on else None
    )

    return Response(
        {
            "total_wells": total_wells,
            "wells_with_data": wells_with_data,
            "wells_without_data": total_wells - wells_with_data,
            "newest_measured_on": (
                newest_measured_on.isoformat() if newest_measured_on else None
            ),
            "newest_measurement_age_days": newest_measurement_age_days,
            "frequency_distribution": {
                label: frequency_counts.get(label, 0)
                for label in FREQUENCY_DISTRIBUTION_ORDER
            },
            "latest_measurement_age_distribution": [
                {
                    "key": key,
                    "label": label,
                    "count": age_counts.get(key, 0),
                }
                for key, label, _max in AGE_BUCKETS
            ],
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
