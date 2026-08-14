from datetime import date

from django.db import connection

from .models import Well

FREQUENCY_THRESHOLDS_DAYS = (
    (1.5, "daily"),
    (9, "weekly"),
    (45, "monthly"),
    (120, "quarterly"),
    (450, "yearly"),
)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def frequency_from_median_gap(median_gap_days: float | None) -> str | None:
    if median_gap_days is None:
        return None
    for max_gap, label in FREQUENCY_THRESHOLDS_DAYS:
        if median_gap_days <= max_gap:
            return label
    return "irregular"


def measurement_frequency(dates: list[date]) -> str | None:
    if len(dates) < 2:
        return None
    ordered = sorted(dates)
    gaps = [float((ordered[i] - ordered[i - 1]).days) for i in range(1, len(ordered))]
    return frequency_from_median_gap(_median(gaps))


def _frequency_case_sql(median_expr: str = "median_gap") -> str:
    whens = " ".join(
        f"WHEN {median_expr} <= {max_gap} THEN '{label}'"
        for max_gap, label in FREQUENCY_THRESHOLDS_DAYS
    )
    return f"CASE {whens} ELSE 'irregular' END"


def refresh_well_frequencies() -> int:
    """Store median-gap frequency on every well. Returns wells with a frequency."""
    case_sql = _frequency_case_sql()
    update_sql = f"""
        WITH gaps AS (
            SELECT
                well_id,
                measured_on - LAG(measured_on) OVER (
                    PARTITION BY well_id ORDER BY measured_on
                ) AS gap_days
            FROM api_measurement
        ),
        medians AS (
            SELECT
                well_id,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY gap_days) AS median_gap
            FROM gaps
            WHERE gap_days IS NOT NULL
            GROUP BY well_id
        )
        UPDATE api_well AS well
        SET measurement_frequency = mapped.frequency
        FROM (
            SELECT well_id, {case_sql} AS frequency
            FROM medians
        ) AS mapped
        WHERE well.id = mapped.well_id
          AND well.measurement_frequency IS DISTINCT FROM mapped.frequency
    """
    clear_sql = """
        UPDATE api_well AS well
        SET measurement_frequency = NULL
        WHERE well.measurement_frequency IS NOT NULL
          AND (
              SELECT COUNT(*)
              FROM api_measurement AS measurement
              WHERE measurement.well_id = well.id
          ) < 2
    """
    with connection.cursor() as cursor:
        cursor.execute(update_sql)
        cursor.execute(clear_sql)
    return Well.objects.exclude(measurement_frequency__isnull=True).count()
