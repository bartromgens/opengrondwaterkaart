from django.db import connection

from .models import Well


def refresh_well_measurement_stats() -> int:
    update_sql = """
        UPDATE api_well AS well
        SET
            first_measured_on = mapped.first_on,
            last_measured_on = mapped.last_on,
            measurement_count = mapped.n
        FROM (
            SELECT
                well.id AS well_id,
                stats.first_on,
                stats.last_on,
                COALESCE(stats.n, 0) AS n
            FROM api_well AS well
            LEFT JOIN (
                SELECT
                    well_id,
                    MIN(measured_on) AS first_on,
                    MAX(measured_on) AS last_on,
                    COUNT(*)::integer AS n
                FROM api_measurement
                GROUP BY well_id
            ) AS stats ON stats.well_id = well.id
        ) AS mapped
        WHERE well.id = mapped.well_id
          AND (
              well.first_measured_on IS DISTINCT FROM mapped.first_on
              OR well.last_measured_on IS DISTINCT FROM mapped.last_on
              OR well.measurement_count IS DISTINCT FROM mapped.n
          )
    """
    with connection.cursor() as cursor:
        cursor.execute(update_sql)
    return Well.objects.filter(measurement_count__gt=0).count()
