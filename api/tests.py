from datetime import date
from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .management.commands.bootstrap_wells import LAYER_GLD, LAYER_GMW, LAYER_TUBE
from .management.commands.sync_bro_organizations import (
    Command as SyncOrganizationsCommand,
)
from .management.commands.sync_bro_organizations import parse_organizations
from .models import Measurement, Organization, Well
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


class _FakeFionaCollection(list):
    """List-based stand-in for a fiona layer collection (supports `with` + len())."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class BootstrapWellsOwnershipTests(TestCase):
    """Verify owner/bronhouder/BRO-object fields are imported from PDOK features."""

    def _gmw_feature(self) -> dict:
        return {
            "properties": {
                "bro_id": "GMW000000003622",
                "nitg_code": "B07C1874",
                "well_code": "GMW07C001874",
                "ground_level_position": "1.65",
                "owner": "01182779",
                "delivery_accountable_party": "73552208",
                "imbro_xml_url": (
                    "https://publiek.broservices.nl/gm/gmw/v1/objects/"
                    "GMW000000003622"
                ),
            },
            "geometry": {"type": "Point", "coordinates": [5.0, 52.0]},
        }

    def _fake_open(self, _path, layer=None):
        if layer == LAYER_GMW:
            return _FakeFionaCollection([self._gmw_feature()])
        if layer in (LAYER_TUBE, LAYER_GLD):
            return _FakeFionaCollection([])
        return _FakeFionaCollection([])

    @patch("api.management.commands.bootstrap_wells.fiona")
    def test_upsert_wells_stores_ownership_fields(self, mock_fiona):
        mock_fiona.open.side_effect = self._fake_open

        from .management.commands.bootstrap_wells import Command

        Command()._upsert_wells(
            gpkg_path="fake.gpkg",
            link_map={},
            tube_extras={},
            now=timezone.now(),
            errors=[],
        )

        well = Well.objects.get(bro_id="GMW000000003622")
        self.assertEqual(well.owner_kvk, "01182779")
        self.assertEqual(well.bronhouder_kvk, "73552208")
        self.assertEqual(
            well.bro_object_url,
            "https://publiek.broservices.nl/gm/gmw/v1/objects/GMW000000003622",
        )


SAMPLE_ORGANIZATIONS_HTML = """
<h2>Organisatienaam | KVK-nummer (B) Bronhouder</h2>
<p>4Infra B.V. | 05084212<br>Gemeente Zuidhorn | 01182779 (B)<br>\
Gemeente Westerveld | 73552208 (​B)</p>
"""


class ParseOrganizationsTests(TestCase):
    def test_parses_name_and_kvk_pairs(self):
        organizations = parse_organizations(SAMPLE_ORGANIZATIONS_HTML)

        self.assertEqual(organizations["05084212"], "4Infra B.V.")
        self.assertEqual(organizations["01182779"], "Gemeente Zuidhorn")
        self.assertEqual(organizations["73552208"], "Gemeente Westerveld")

    def test_raises_when_marker_missing(self):
        with self.assertRaises(RuntimeError):
            parse_organizations("<p>no marker here</p>")


class SyncBroOrganizationsTests(TestCase):
    @patch("api.management.commands.sync_bro_organizations._fetch_html")
    def test_syncs_organizations_into_database(self, mock_fetch_html):
        mock_fetch_html.return_value = SAMPLE_ORGANIZATIONS_HTML

        SyncOrganizationsCommand().handle()

        self.assertEqual(Organization.objects.count(), 3)
        self.assertEqual(
            Organization.objects.get(kvk_number="01182779").name, "Gemeente Zuidhorn"
        )

    @patch("api.management.commands.sync_bro_organizations._fetch_html")
    def test_updates_existing_organization_name(self, mock_fetch_html):
        Organization.objects.create(
            kvk_number="01182779", name="Old Name", resolved_at=timezone.now()
        )
        mock_fetch_html.return_value = SAMPLE_ORGANIZATIONS_HTML

        SyncOrganizationsCommand().handle()

        self.assertEqual(
            Organization.objects.get(kvk_number="01182779").name, "Gemeente Zuidhorn"
        )


class WellDetailOrganizationTests(TestCase):
    def setUp(self):
        self.well = Well.objects.create(
            bro_id="BRO001",
            location=Point(5.0, 52.0, srid=4326),
            owner_kvk="01182779",
            bronhouder_kvk="73552208",
            bro_object_url="https://publiek.broservices.nl/gm/gmw/v1/objects/BRO001",
        )
        Organization.objects.create(
            kvk_number="73552208",
            name="Gemeente Westerveld",
            resolved_at=timezone.now(),
        )

    def test_returns_resolved_and_unresolved_organizations(self):
        response = self.client.get(reverse("well-detail", args=["BRO001"]))
        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(body["bronhouder"]["kvk"], "73552208")
        self.assertEqual(body["bronhouder"]["name"], "Gemeente Westerveld")
        self.assertIn("73552208", body["bronhouder"]["kvk_url"])

        self.assertEqual(body["owner"]["kvk"], "01182779")
        self.assertIsNone(body["owner"]["name"])
        self.assertIn("01182779", body["owner"]["kvk_url"])

        self.assertEqual(
            body["bro_object_url"],
            "https://publiek.broservices.nl/gm/gmw/v1/objects/BRO001",
        )

    def test_returns_none_for_wells_without_ownership_data(self):
        Well.objects.create(bro_id="BRO002", location=Point(5.1, 52.1, srid=4326))
        response = self.client.get(reverse("well-detail", args=["BRO002"]))
        body = response.json()

        self.assertIsNone(body["owner"])
        self.assertIsNone(body["bronhouder"])
        self.assertIsNone(body["bro_object_url"])


class WellsStatsViewTests(TestCase):
    def setUp(self):
        self.well_daily = Well.objects.create(
            bro_id="BRO001", location=Point(5.0, 52.0, srid=4326)
        )
        self.well_yearly = Well.objects.create(
            bro_id="BRO002", location=Point(5.1, 52.1, srid=4326)
        )
        self.well_without_data = Well.objects.create(
            bro_id="BRO003", location=Point(5.2, 52.2, srid=4326)
        )

        for offset in range(5):
            Measurement.objects.create(
                well=self.well_daily,
                measured_on=date(2020, 1, 1 + offset),
                value_m_nap=1.0,
            )
        Measurement.objects.create(
            well=self.well_yearly, measured_on=date(2015, 1, 1), value_m_nap=2.0
        )
        Measurement.objects.create(
            well=self.well_yearly, measured_on=date(2020, 1, 1), value_m_nap=2.1
        )

    def test_returns_totals_and_distribution(self):
        response = self.client.get(reverse("wells-stats"))
        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(body["total_wells"], 3)
        self.assertEqual(body["wells_with_data"], 2)
        self.assertEqual(body["wells_without_data"], 1)
        self.assertEqual(body["frequency_distribution"]["daily"], 1)
        self.assertEqual(body["frequency_distribution"]["yearly"], 1)
        self.assertEqual(body["frequency_distribution"]["no_data"], 1)

    def test_newest_measurement_age_is_computed_from_latest_date(self):
        response = self.client.get(reverse("wells-stats"))
        body = response.json()

        self.assertEqual(body["newest_measured_on"], "2020-01-05")
        expected_age = (timezone.localdate() - date(2020, 1, 5)).days
        self.assertEqual(body["newest_measurement_age_days"], expected_age)

    def test_handles_no_measurements_at_all(self):
        Measurement.objects.all().delete()
        response = self.client.get(reverse("wells-stats"))
        body = response.json()

        self.assertEqual(body["wells_with_data"], 0)
        self.assertIsNone(body["newest_measured_on"])
        self.assertIsNone(body["newest_measurement_age_days"])
        self.assertEqual(body["frequency_distribution"]["no_data"], 3)
