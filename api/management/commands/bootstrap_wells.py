import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from typing import Any

import fiona
import requests
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.utils import timezone as django_timezone

from api.management.dev_bbox import point_in_dev_bbox, write_dev_bbox_notice
from api.models import IngestRun, IngestRunStatus, Well

ATOM_URL = (
    "https://service.pdok.nl/bzk/brogmwvolledigeset/atom/v2_1/brogmwvolledigeset.xml"
)
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _find_gpkg_url(atom_url: str) -> str:
    resp = requests.get(atom_url, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    # Find the first <link> with type application/geopackage+sqlite3 or href ending in .zip
    for entry in root.findall("atom:entry", ATOM_NS):
        for link in entry.findall("atom:link", ATOM_NS):
            href = link.get("href", "")
            if href.endswith(".zip") or "gpkg" in href.lower():
                return href
    # Fallback: any zip link at the feed level
    for link in root.findall("atom:link", ATOM_NS):
        href = link.get("href", "")
        if href.endswith(".zip"):
            return href
    raise RuntimeError(f"No GeoPackage ZIP link found in ATOM feed: {atom_url}")


def _parse_float(val: Any) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


@dataclass
class ElevationLookups:
    ground_levels: dict[int, float | None]
    tube_tops: dict[tuple[int, int], float | None]
    tube_fks: dict[tuple[int, int], int]
    screens: dict[int, tuple[float | None, float | None]]


def _load_elevation_lookups(gpkg_path: str) -> ElevationLookups:
    ground_levels: dict[int, float | None] = {}
    tube_tops: dict[tuple[int, int], float | None] = {}
    tube_fks: dict[tuple[int, int], int] = {}
    screens: dict[int, tuple[float | None, float | None]] = {}

    with fiona.open(gpkg_path, layer="delivered_vertical_position") as src:
        for feature in src:
            well_fk = feature["properties"].get("groundwater_monitoring_well_fk")
            if well_fk is None:
                continue
            ground_levels[int(well_fk)] = _parse_float(
                feature["properties"].get("ground_level_position")
            )

    with fiona.open(gpkg_path, layer="monitoring_tube") as src:
        for feature in src:
            props = feature["properties"]
            well_fk = props.get("groundwater_monitoring_well_fk")
            tube_number = props.get("tube_number")
            if well_fk is None or tube_number is None:
                continue
            key = (int(well_fk), int(tube_number))
            tube_tops[key] = _parse_float(props.get("tube_top_position"))
            tube_fks[key] = int(feature["id"])

    with fiona.open(gpkg_path, layer="screen") as src:
        for feature in src:
            tube_fk = feature["properties"].get("monitoring_tube_fk")
            if tube_fk is None:
                continue
            props = feature["properties"]
            screens[int(tube_fk)] = (
                _parse_float(props.get("screen_top_position")),
                _parse_float(props.get("screen_bottom_position")),
            )

    return ElevationLookups(
        ground_levels=ground_levels,
        tube_tops=tube_tops,
        tube_fks=tube_fks,
        screens=screens,
    )


def _elevation_for_well(
    well_pk: int, tube_number: int, lookups: ElevationLookups
) -> tuple[float | None, float | None, float | None, float | None]:
    ground_level_m = lookups.ground_levels.get(well_pk)
    tube_key = (well_pk, tube_number)
    tube_top_m = lookups.tube_tops.get(tube_key)
    tube_fk = lookups.tube_fks.get(tube_key)
    screen_top_m = screen_bottom_m = None
    if tube_fk is not None:
        screen = lookups.screens.get(tube_fk)
        if screen is not None:
            screen_top_m, screen_bottom_m = screen
    return ground_level_m, tube_top_m, screen_top_m, screen_bottom_m


class Command(BaseCommand):
    help = "Bootstrap well locations from the PDOK GMW bulk GeoPackage ATOM feed."

    def handle(self, *args: Any, **options: Any) -> None:
        run = IngestRun.objects.create(kind="bootstrap_wells")
        errors: list[str] = []
        now = django_timezone.now()

        try:
            self.stdout.write("Fetching ATOM feed...")
            gpkg_url = _find_gpkg_url(ATOM_URL)
            self.stdout.write(f"Downloading: {gpkg_url}")

            with tempfile.TemporaryDirectory() as tmpdir:
                resp = requests.get(gpkg_url, timeout=300, stream=True)
                resp.raise_for_status()

                zip_path = f"{tmpdir}/gmw.zip"
                with open(zip_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)

                self.stdout.write("Extracting GeoPackage...")
                with zipfile.ZipFile(zip_path) as zf:
                    gpkg_names = [n for n in zf.namelist() if n.endswith(".gpkg")]
                    if not gpkg_names:
                        raise RuntimeError("No .gpkg file found in ZIP")
                    zf.extract(gpkg_names[0], tmpdir)
                    gpkg_path = f"{tmpdir}/{gpkg_names[0]}"

                self.stdout.write("Loading elevation lookups...")
                lookups = _load_elevation_lookups(gpkg_path)
                self.stdout.write("Reading GeoPackage layers...")
                with fiona.open(gpkg_path) as src:
                    self._upsert_layer(src, now, errors, lookups)

            run.wells_processed = Well.objects.count()
            run.status = IngestRunStatus.SUCCESS
            self.stdout.write(
                self.style.SUCCESS(f"Done. Wells in DB: {run.wells_processed}")
            )

        except Exception as exc:
            errors.append(str(exc))
            run.status = IngestRunStatus.FAILED
            self.stderr.write(self.style.ERROR(f"bootstrap_wells failed: {exc}"))

        run.finished_at = django_timezone.now()
        run.errors_json = errors
        run.save()

    def _upsert_layer(
        self,
        src: fiona.Collection,
        now: Any,
        errors: list[str],
        lookups: ElevationLookups,
    ) -> None:
        batch_size = 500
        to_create: list[Well] = []
        to_update: list[Well] = []
        existing = {w.bro_id: w for w in Well.objects.only("bro_id", "id")}

        total = len(src)
        write_dev_bbox_notice(self.stdout)
        self.stdout.write(f"Processing {total} features...")

        for i, feature in enumerate(src):
            try:
                props = feature["properties"]
                bro_id = (
                    props.get("bro_id") or props.get("broId") or props.get("BRO_ID")
                )
                if not bro_id:
                    continue

                geom = feature.get("geometry")
                if not geom or geom["type"] != "Point":
                    continue

                lon, lat = geom["coordinates"][:2]
                if not point_in_dev_bbox(lon, lat):
                    continue

                point = Point(lon, lat, srid=4326)

                tube_number = int(
                    props.get("tube_number") or props.get("tubeNumber") or 1
                )
                nitg_code = str(props.get("nitg_code") or props.get("nitgCode") or "")
                name = str(props.get("name") or "")
                ground_level_m, tube_top_m, screen_top_m, screen_bottom_m = (
                    _elevation_for_well(int(feature["id"]), tube_number, lookups)
                )

                if bro_id in existing:
                    w = existing[bro_id]
                    w.location = point
                    w.tube_number = tube_number
                    w.nitg_code = nitg_code
                    w.name = name
                    w.ground_level_m = ground_level_m
                    w.tube_top_m = tube_top_m
                    w.screen_top_m = screen_top_m
                    w.screen_bottom_m = screen_bottom_m
                    w.pdok_updated_at = now
                    to_update.append(w)
                else:
                    to_create.append(
                        Well(
                            bro_id=bro_id,
                            tube_number=tube_number,
                            nitg_code=nitg_code,
                            name=name,
                            location=point,
                            ground_level_m=ground_level_m,
                            tube_top_m=tube_top_m,
                            screen_top_m=screen_top_m,
                            screen_bottom_m=screen_bottom_m,
                            pdok_updated_at=now,
                        )
                    )

                if len(to_create) >= batch_size:
                    Well.objects.bulk_create(to_create, ignore_conflicts=True)
                    to_create = []
                if len(to_update) >= batch_size:
                    Well.objects.bulk_update(
                        to_update,
                        [
                            "location",
                            "tube_number",
                            "nitg_code",
                            "name",
                            "ground_level_m",
                            "tube_top_m",
                            "screen_top_m",
                            "screen_bottom_m",
                            "pdok_updated_at",
                        ],
                    )
                    to_update = []

                if (i + 1) % 5000 == 0:
                    self.stdout.write(f"  {i + 1}/{total}")

            except Exception as exc:
                errors.append(f"feature {i}: {exc}")

        if to_create:
            Well.objects.bulk_create(to_create, ignore_conflicts=True)
        if to_update:
            Well.objects.bulk_update(
                to_update,
                [
                    "location",
                    "tube_number",
                    "nitg_code",
                    "name",
                    "ground_level_m",
                    "tube_top_m",
                    "screen_top_m",
                    "screen_bottom_m",
                    "pdok_updated_at",
                ],
            )
