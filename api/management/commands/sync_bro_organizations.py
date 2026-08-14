import html
import logging
import re
from typing import Any

import requests
from django.core.management.base import BaseCommand
from django.utils import timezone as django_timezone

from api.models import Organization

logger = logging.getLogger(__name__)

BRO_ORGANIZATIONS_URL = (
    "https://basisregistratieondergrond.nl/service-contact/formulieren/aangemeld-bro/"
)
# The site redirects the default python-requests User-Agent into a redirect loop.
USER_AGENT = (
    "OpenGrondWaterKaart/1.0 (+https://github.com/bartromgens/opengrondwaterkaart)"
)
LIST_MARKER = "Organisatienaam | KVK-nummer"
ENTRY_PATTERN = re.compile(r"([^|<]+)\|\s*(\d{8})")


def _fetch_html() -> str:
    resp = requests.get(
        BRO_ORGANIZATIONS_URL,
        timeout=30,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    return resp.text


def _extract_list_html(page_html: str) -> str:
    """Return the <p> block containing the "Name | KvK-number" list."""
    marker_pos = page_html.find(LIST_MARKER)
    if marker_pos == -1:
        raise RuntimeError("Could not find organizations list marker on page.")
    p_start = page_html.find("<p>", marker_pos)
    p_end = page_html.find("</p>", p_start)
    if p_start == -1 or p_end == -1:
        raise RuntimeError("Could not find organizations list <p> block.")
    return page_html[p_start + len("<p>") : p_end]


def parse_organizations(page_html: str) -> dict[str, str]:
    """Return {kvk_number: name} parsed from the BRO organizations page HTML."""
    list_html = _extract_list_html(page_html)
    organizations: dict[str, str] = {}
    for line in list_html.split("<br>"):
        match = ENTRY_PATTERN.search(line)
        if not match:
            continue
        name = html.unescape(match.group(1)).strip()
        kvk_number = match.group(2)
        if name:
            organizations[kvk_number] = name
    return organizations


class Command(BaseCommand):
    help = (
        "Sync the Organization table from the BRO 'Aangemeld bij de BRO' "
        "list, which maps organization names to KvK numbers for well "
        "owners and bronhouders. Intended to run monthly."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        logger.info("Fetching BRO organizations list from %s", BRO_ORGANIZATIONS_URL)
        page_html = _fetch_html()
        organizations = parse_organizations(page_html)
        logger.info("Parsed %d organizations from BRO page.", len(organizations))

        now = django_timezone.now()
        for kvk_number, name in organizations.items():
            Organization.objects.update_or_create(
                kvk_number=kvk_number,
                defaults={"name": name, "resolved_at": now},
            )

        logger.info("Synced %d organizations into the database.", len(organizations))
