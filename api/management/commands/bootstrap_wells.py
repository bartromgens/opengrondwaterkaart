import logging
from collections import defaultdict
from datetime import date
from typing import Any

import fiona
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.utils import timezone as django_timezone

from api.management.dev_bbox import point_in_dev_bbox, write_dev_bbox_notice
from api.management.samenhang import (
    LAYER_GLD,
    LAYER_GMN,
    LAYER_GMN_MEASURINGPOINT,
    LAYER_GMW,
    LAYER_TUBE,
    download_samenhang_gpkg,
    parse_date,
    parse_float,
)
from api.models import IngestRun, IngestRunStatus, MonitoringNetwork, Well

BATCH_SIZE = 500
logger = logging.getLogger(__name__)
UPDATE_FIELDS = [
    "location",
    "tube_number",
    "nitg_code",
    "name",
    "ground_level_m",
    "tube_top_m",
    "screen_top_m",
    "screen_bottom_m",
    "owner_kvk",
    "bronhouder_kvk",
    "bro_object_url",
    "well_construction_date",
    "initial_function",
    "number_of_monitoring_tubes",
    "pdok_updated_at",
    "gld_bro_id",
    "research_first_date",
    "research_last_date",
]


def _build_tube_by_fid(gpkg_path: str) -> dict[int, str]:
    """Return {tube_fid: gmw_bro_id}."""
    tube_by_fid: dict[int, str] = {}
    with fiona.open(gpkg_path, layer=LAYER_TUBE) as src:
        for feat in src:
            gmw_bro_id = feat["properties"].get("gmw_bro_id") or ""
            if gmw_bro_id:
                tube_by_fid[int(feat.id)] = gmw_bro_id
    return tube_by_fid


def _build_link_map(
    gpkg_path: str,
    tube_by_fid: dict[int, str],
) -> dict[str, tuple[str, date | None, date | None]]:
    """Return {gmw_bro_id: (gld_bro_id, research_first_date, research_last_date)}.

    For wells with multiple GLD-linked tubes, keeps the entry with the
    most recent research_last_date.
    """
    link_map: dict[str, tuple[str, date | None, date | None]] = {}
    with fiona.open(gpkg_path, layer=LAYER_GLD) as src:
        for feat in src:
            props = feat["properties"]
            fk = props.get("gm_gmw_monitoringtube_fk")
            gld_bro_id = props.get("bro_id") or ""
            if fk is None or not gld_bro_id:
                continue
            gmw_bro_id = tube_by_fid.get(int(fk))
            if not gmw_bro_id:
                continue
            research_first_date = parse_date(props.get("research_first_date"))
            research_last_date = parse_date(props.get("research_last_date"))
            existing = link_map.get(gmw_bro_id)
            if existing is None or (
                research_last_date is not None
                and (existing[2] is None or research_last_date > existing[2])
            ):
                link_map[gmw_bro_id] = (
                    gld_bro_id,
                    research_first_date,
                    research_last_date,
                )
    return link_map


def _build_tube_extras(
    gpkg_path: str,
) -> dict[str, tuple[float | None, float | None]]:
    """Return {gmw_bro_id: (screen_top_m, screen_bottom_m)} for tube 1."""
    extras: dict[str, tuple[float | None, float | None]] = {}
    with fiona.open(gpkg_path, layer=LAYER_TUBE) as src:
        for feat in src:
            props = feat["properties"]
            gmw_bro_id = props.get("gmw_bro_id") or ""
            tube_number = props.get("tube_number")
            if not gmw_bro_id or tube_number != 1:
                continue
            extras[gmw_bro_id] = (
                parse_float(props.get("screen_top_position")),
                parse_float(props.get("screen_bottom_position")),
            )
    return extras


def _sync_monitoring_networks(gpkg_path: str) -> dict[str, MonitoringNetwork]:
    """Upsert MonitoringNetwork rows; return {bro_id: instance}."""
    by_bro_id: dict[str, MonitoringNetwork] = {
        n.bro_id: n for n in MonitoringNetwork.objects.all()
    }
    to_create: list[MonitoringNetwork] = []
    to_update: list[MonitoringNetwork] = []
    update_fields = [
        "name",
        "monitoring_purpose",
        "groundwater_aspect",
        "delivery_context",
        "start_date",
        "end_date",
        "bro_object_url",
    ]

    with fiona.open(gpkg_path, layer=LAYER_GMN) as src:
        for feat in src:
            props = feat["properties"]
            bro_id = props.get("bro_id") or ""
            if not bro_id:
                continue
            values = {
                "name": str(props.get("name") or ""),
                "monitoring_purpose": str(props.get("monitoring_purpose") or ""),
                "groundwater_aspect": str(props.get("groundwater_aspect") or ""),
                "delivery_context": str(props.get("delivery_context") or ""),
                "start_date": parse_date(props.get("start_date_monitoring")),
                "end_date": parse_date(props.get("end_date_monitoring")),
                "bro_object_url": str(props.get("imbro_xml_url") or "").strip(),
            }
            if bro_id in by_bro_id:
                network = by_bro_id[bro_id]
                for field, value in values.items():
                    setattr(network, field, value)
                to_update.append(network)
            else:
                network = MonitoringNetwork(bro_id=bro_id, **values)
                to_create.append(network)
                by_bro_id[bro_id] = network

    if to_create:
        MonitoringNetwork.objects.bulk_create(to_create, ignore_conflicts=True)
        # Reload created rows so M2M linking has PKs.
        by_bro_id = {n.bro_id: n for n in MonitoringNetwork.objects.all()}
    if to_update:
        MonitoringNetwork.objects.bulk_update(to_update, update_fields)

    logger.info("Synced %d monitoring networks.", len(by_bro_id))
    return by_bro_id


def _build_well_network_links(
    gpkg_path: str,
    tube_by_fid: dict[int, str],
) -> dict[str, set[str]]:
    """Return {gmw_bro_id: {gmn_bro_id, ...}} from measuring points."""
    links: dict[str, set[str]] = defaultdict(set)
    with fiona.open(gpkg_path, layer=LAYER_GMN_MEASURINGPOINT) as src:
        for feat in src:
            props = feat["properties"]
            tube_fk = props.get("gm_gmw_monitoringtube_fk")
            gmn_bro_id = props.get("gmn_bro_id") or ""
            if tube_fk is None or not gmn_bro_id:
                continue
            gmw_bro_id = tube_by_fid.get(int(tube_fk))
            if gmw_bro_id:
                links[gmw_bro_id].add(gmn_bro_id)
    return links


class Command(BaseCommand):
    help = (
        "Bootstrap well locations, ownership, GLD links and monitoring "
        "networks from the PDOK GM-in-samenhang GeoPackage."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        run = IngestRun.objects.create(kind="bootstrap_wells")
        errors: list[str] = []
        now = django_timezone.now()

        try:
            with download_samenhang_gpkg() as gpkg_path:
                logger.info("Building tube index...")
                tube_by_fid = _build_tube_by_fid(gpkg_path)

                logger.info("Building GLD link map...")
                link_map = _build_link_map(gpkg_path, tube_by_fid)
                logger.info("  %d wells have a GLD link in kenset", len(link_map))

                logger.info("Building tube screen positions...")
                tube_extras = _build_tube_extras(gpkg_path)

                logger.info("Syncing monitoring networks...")
                networks_by_bro_id = _sync_monitoring_networks(gpkg_path)
                well_network_links = _build_well_network_links(gpkg_path, tube_by_fid)
                logger.info(
                    "  %d wells linked to one or more monitoring networks",
                    len(well_network_links),
                )

                write_dev_bbox_notice()
                self._upsert_wells(gpkg_path, link_map, tube_extras, now, errors)
                self._sync_well_network_membership(
                    well_network_links, networks_by_bro_id
                )

            run.wells_processed = Well.objects.count()
            run.status = IngestRunStatus.SUCCESS
            logger.info("Done. Wells in DB: %d", run.wells_processed)

        except Exception as exc:
            errors.append(str(exc))
            run.status = IngestRunStatus.FAILED
            logger.error("bootstrap_wells failed: %s", exc)

        run.finished_at = django_timezone.now()
        run.errors_json = errors
        run.save()

    def _upsert_wells(
        self,
        gpkg_path: str,
        link_map: dict[str, tuple[str, date | None, date | None]],
        tube_extras: dict[str, tuple[float | None, float | None]],
        now: Any,
        errors: list[str],
    ) -> None:
        existing = {w.bro_id: w for w in Well.objects.only("bro_id", "id")}

        with fiona.open(gpkg_path, layer=LAYER_GMW) as src:
            total_features = len(src)

        logger.info("Processing %d GMW features...", total_features)

        to_create: list[Well] = []
        to_update: list[Well] = []
        processed = 0

        with fiona.open(gpkg_path, layer=LAYER_GMW) as src:
            for i, feature in enumerate(src):
                try:
                    props = feature["properties"]
                    bro_id = props.get("bro_id") or ""
                    if not bro_id:
                        continue

                    geom = feature.get("geometry")
                    if not geom or geom["type"] != "Point":
                        continue

                    lon, lat = geom["coordinates"][:2]
                    if not point_in_dev_bbox(lon, lat):
                        continue

                    nitg_code = str(props.get("nitg_code") or "")
                    name = str(props.get("well_code") or nitg_code or "")
                    ground_level_m = parse_float(props.get("ground_level_position"))
                    screen_top_m, screen_bottom_m = tube_extras.get(
                        bro_id, (None, None)
                    )
                    gld_bro_id, research_first_date, research_last_date = link_map.get(
                        bro_id, ("", None, None)
                    )
                    owner_kvk = str(props.get("owner") or "").strip()
                    bronhouder_kvk = str(
                        props.get("delivery_accountable_party") or ""
                    ).strip()
                    bro_object_url = str(props.get("imbro_xml_url") or "").strip()
                    well_construction_date = parse_date(
                        props.get("well_construction_date")
                    )
                    initial_function = str(props.get("initial_function") or "").strip()
                    number_of_tubes = props.get("number_of_monitoring_tubes") or 1
                    try:
                        number_of_monitoring_tubes = int(number_of_tubes)
                    except (TypeError, ValueError):
                        number_of_monitoring_tubes = 1
                    point = Point(lon, lat, srid=4326)

                    if bro_id in existing:
                        w = existing[bro_id]
                        w.location = point
                        w.tube_number = 1
                        w.nitg_code = nitg_code
                        w.name = name
                        w.ground_level_m = ground_level_m
                        w.tube_top_m = None
                        w.screen_top_m = screen_top_m
                        w.screen_bottom_m = screen_bottom_m
                        w.owner_kvk = owner_kvk
                        w.bronhouder_kvk = bronhouder_kvk
                        w.bro_object_url = bro_object_url
                        w.well_construction_date = well_construction_date
                        w.initial_function = initial_function
                        w.number_of_monitoring_tubes = number_of_monitoring_tubes
                        w.pdok_updated_at = now
                        w.gld_bro_id = gld_bro_id
                        w.research_first_date = research_first_date
                        w.research_last_date = research_last_date
                        to_update.append(w)
                    else:
                        to_create.append(
                            Well(
                                bro_id=bro_id,
                                tube_number=1,
                                nitg_code=nitg_code,
                                name=name,
                                location=point,
                                ground_level_m=ground_level_m,
                                tube_top_m=None,
                                screen_top_m=screen_top_m,
                                screen_bottom_m=screen_bottom_m,
                                owner_kvk=owner_kvk,
                                bronhouder_kvk=bronhouder_kvk,
                                bro_object_url=bro_object_url,
                                well_construction_date=well_construction_date,
                                initial_function=initial_function,
                                number_of_monitoring_tubes=number_of_monitoring_tubes,
                                pdok_updated_at=now,
                                gld_bro_id=gld_bro_id,
                                research_first_date=research_first_date,
                                research_last_date=research_last_date,
                            )
                        )

                    processed += 1

                    if len(to_create) >= BATCH_SIZE:
                        Well.objects.bulk_create(to_create, ignore_conflicts=True)
                        to_create = []
                    if len(to_update) >= BATCH_SIZE:
                        Well.objects.bulk_update(to_update, UPDATE_FIELDS)
                        to_update = []

                    if (i + 1) % 5000 == 0:
                        logger.info("  %d/%d", i + 1, total_features)

                except Exception as exc:
                    errors.append(f"feature {i}: {exc}")

        if to_create:
            Well.objects.bulk_create(to_create, ignore_conflicts=True)
        if to_update:
            Well.objects.bulk_update(to_update, UPDATE_FIELDS)

        logger.info(
            "Upserted %d wells (%d GLD links available in kenset).",
            processed,
            len(link_map),
        )

    def _sync_well_network_membership(
        self,
        well_network_links: dict[str, set[str]],
        networks_by_bro_id: dict[str, MonitoringNetwork],
    ) -> None:
        wells = {
            w.bro_id: w
            for w in Well.objects.filter(bro_id__in=well_network_links.keys()).only(
                "id", "bro_id"
            )
        }
        Through = Well.monitoring_networks.through
        Through.objects.filter(well_id__in=[w.id for w in wells.values()]).delete()

        memberships: list[Through] = []
        for gmw_bro_id, gmn_bro_ids in well_network_links.items():
            well = wells.get(gmw_bro_id)
            if well is None:
                continue
            for gmn_bro_id in gmn_bro_ids:
                network = networks_by_bro_id.get(gmn_bro_id)
                if network is None or network.pk is None:
                    continue
                memberships.append(
                    Through(well_id=well.id, monitoringnetwork_id=network.pk)
                )

        if memberships:
            Through.objects.bulk_create(memberships, ignore_conflicts=True)
        logger.info("Updated monitoring-network membership for %d wells.", len(wells))
