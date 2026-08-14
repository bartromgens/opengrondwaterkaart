from datetime import date

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from .models import Measurement, Well
from .views import _measurement_frequency


class MeasurementFrequencyTests(TestCase):
    def test_no_data_returns_none(self):
        self.assertIsNone(_measurement_frequency(None, None, 0))

    def test_single_measurement_returns_none(self):
        self.assertIsNone(_measurement_frequency(date(2020, 1, 1), date(2020, 1, 1), 1))

    def test_daily_measurements(self):
        frequency = _measurement_frequency(date(2020, 1, 1), date(2020, 1, 31), 31)
        self.assertEqual(frequency, "daily")

    def test_weekly_measurements(self):
        frequency = _measurement_frequency(date(2020, 1, 1), date(2020, 3, 25), 13)
        self.assertEqual(frequency, "weekly")

    def test_monthly_measurements(self):
        frequency = _measurement_frequency(date(2020, 1, 1), date(2021, 1, 1), 13)
        self.assertEqual(frequency, "monthly")

    def test_irregular_measurements(self):
        frequency = _measurement_frequency(date(2000, 1, 1), date(2024, 1, 1), 3)
        self.assertEqual(frequency, "irregular")


class WellsOverviewViewTests(TestCase):
    def setUp(self):
        self.well_with_data = Well.objects.create(
            bro_id="BRO001",
            nitg_code="NITG001",
            name="Put A",
            location=Point(5.0, 52.0, srid=4326),
        )
        self.well_without_data = Well.objects.create(
            bro_id="BRO002",
            nitg_code="NITG002",
            name="Put B",
            location=Point(5.1, 52.1, srid=4326),
        )
        Measurement.objects.create(
            well=self.well_with_data, measured_on=date(2020, 1, 1), value_m_nap=1.0
        )
        Measurement.objects.create(
            well=self.well_with_data, measured_on=date(2020, 1, 8), value_m_nap=1.1
        )
        Measurement.objects.create(
            well=self.well_with_data, measured_on=date(2020, 1, 15), value_m_nap=1.2
        )

    def test_returns_stats_for_well_with_measurements(self):
        response = self.client.get(reverse("wells-overview"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 2)
        by_bro_id = {row["bro_id"]: row for row in body["results"]}

        self.assertEqual(by_bro_id["BRO001"]["first_measured_on"], "2020-01-01")
        self.assertEqual(by_bro_id["BRO001"]["last_measured_on"], "2020-01-15")
        self.assertEqual(by_bro_id["BRO001"]["measurement_count"], 3)
        self.assertEqual(by_bro_id["BRO001"]["frequency"], "weekly")

    def test_returns_nulls_for_well_without_measurements(self):
        response = self.client.get(reverse("wells-overview"))
        by_bro_id = {row["bro_id"]: row for row in response.json()["results"]}

        self.assertIsNone(by_bro_id["BRO002"]["first_measured_on"])
        self.assertIsNone(by_bro_id["BRO002"]["last_measured_on"])
        self.assertEqual(by_bro_id["BRO002"]["measurement_count"], 0)
        self.assertIsNone(by_bro_id["BRO002"]["frequency"])

    def test_default_ordering_puts_wells_with_data_first(self):
        response = self.client.get(reverse("wells-overview"))
        results = response.json()["results"]
        self.assertEqual(results[0]["bro_id"], "BRO001")
        self.assertEqual(results[1]["bro_id"], "BRO002")

    def test_pagination_limits_results(self):
        response = self.client.get(reverse("wells-overview"), {"page_size": 1})
        body = response.json()
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["count"], 2)
        self.assertEqual(body["page_size"], 1)

    def test_invalid_ordering_falls_back_to_default(self):
        response = self.client.get(
            reverse("wells-overview"), {"ordering": "not_a_field"}
        )
        self.assertEqual(response.json()["ordering"], "-last_measured_on")
