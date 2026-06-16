import logging
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from contextlib import contextmanager
from datetime import date
from typing import Any, Generator

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SAMENHANG_ATOM_URL = (
    "https://service.pdok.nl/tno/bro-grondwatermonitoring-in-samenhang-karakteristieken"
    "/atom/index.xml"
)
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

LAYER_GMW = "gm_gmw"
LAYER_TUBE = "gm_gmw_monitoringtube"
LAYER_GLD = "gm_gld"


def _atom_url() -> str:
    return getattr(settings, "SAMENHANG_ATOM_URL", SAMENHANG_ATOM_URL)


def _find_gpkg_url(atom_url: str) -> str:
    """Walk the (possibly nested) ATOM feed and return the .gpkg or .zip download URL."""
    resp = requests.get(atom_url, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    for entry in root.findall("atom:entry", ATOM_NS):
        for link in entry.findall("atom:link", ATOM_NS):
            href = link.get("href", "")
            typ = link.get("type", "")
            if typ == "application/geopackage+sqlite3" or href.endswith(".gpkg"):
                return href
            if href.endswith(".zip") or "gpkg" in href.lower():
                return href
            # Nested ATOM feed — recurse one level
            if typ == "application/atom+xml" and href != atom_url:
                try:
                    return _find_gpkg_url(href)
                except (requests.RequestException, RuntimeError):
                    continue

    for link in root.findall("atom:link", ATOM_NS):
        href = link.get("href", "")
        if href.endswith(".zip") or href.endswith(".gpkg"):
            return href

    raise RuntimeError(f"No GeoPackage download link found in ATOM feed: {atom_url}")


@contextmanager
def download_samenhang_gpkg() -> Generator[str, None, None]:
    """Download the samenhang GeoPackage and yield the local .gpkg path."""
    atom_url = _atom_url()
    logger.info("Resolving samenhang ATOM feed: %s", atom_url)

    gpkg_url = _find_gpkg_url(atom_url)
    logger.info("Downloading: %s", gpkg_url)

    with tempfile.TemporaryDirectory() as tmpdir:
        resp = requests.get(gpkg_url, timeout=600, stream=True)
        resp.raise_for_status()

        if gpkg_url.endswith(".zip"):
            zip_path = f"{tmpdir}/download.zip"
            with open(zip_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
            with zipfile.ZipFile(zip_path) as zf:
                gpkg_names = [n for n in zf.namelist() if n.endswith(".gpkg")]
                if not gpkg_names:
                    raise RuntimeError("No .gpkg file found in ZIP")
                zf.extract(gpkg_names[0], tmpdir)
                gpkg_path = f"{tmpdir}/{gpkg_names[0]}"
        else:
            gpkg_path = f"{tmpdir}/download.gpkg"
            with open(gpkg_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)

        yield gpkg_path


def parse_float(val: Any) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def parse_date(val: Any) -> date | None:
    try:
        return date.fromisoformat(str(val).strip()) if val else None
    except (ValueError, TypeError):
        return None
