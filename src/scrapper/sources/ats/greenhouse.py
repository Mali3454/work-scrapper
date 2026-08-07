import logging
from datetime import datetime

import httpx

from scrapper.models import RawJob
from scrapper.sources.ats.location import extract_city, is_remote

logger = logging.getLogger(__name__)

API_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_greenhouse(payload: dict, company: str, slug: str) -> list[RawJob]:
    """Mapuje odpowiedź `GET .../v1/boards/<slug>/jobs` na `RawJob`.

    Data publikacji: `first_published`, NIE `updated_at` — zweryfikowane na
    żywo (home.pl), że `updated_at` bywa IDENTYCZNE dla wszystkich ofert
    boarda (zbiorcze odświeżenie, nie publikacja pojedynczej oferty), co
    zepsułoby `max_age_days` (stara oferta wyglądałaby jak świeża).
    `updated_at` jest fallbackiem tylko, gdy `first_published` brakuje.

    Greenhouse NIE ma pola boolowskiego dla pracy zdalnej — jedynym nośnikiem
    tej informacji jest tekst w `location.name` ("Remote", "Remote - Europe").
    Stąd `is_remote`: bez tego oferta zdalna dostawałaby `remote=False` i
    `city="Remote"`, więc matcher szukałby miasta z profilu w słowie "remote"
    i odrzucał każdą ofertę zdalną, także przy `include_remote: true`.
    """
    jobs = []
    for offer in payload.get("jobs") or []:
        url = offer.get("absolute_url")
        if not url:
            logger.debug("greenhouse(%s): pomijam ofertę bez URL: %r", slug, offer)
            continue
        offer_id = offer.get("id")
        location_name = (offer.get("location") or {}).get("name")
        remote = is_remote(location_name)
        # `extract_city` sam zeruje "Remote"/"Remote - Europe" — nie jest to
        # miasto (patrz location.py).
        city = extract_city(location_name)
        posted_at = _parse_datetime(offer.get("first_published")) or _parse_datetime(
            offer.get("updated_at")
        )
        jobs.append(
            RawJob(
                source=f"company:{slug}",
                external_id=str(offer_id) if offer_id is not None else url,
                title=offer.get("title", ""),
                company=company,
                city=city,
                remote=remote,
                url=url,
                salary=None,
                posted_at=posted_at,
            )
        )
    return jobs


def fetch_greenhouse(entry, client: httpx.Client) -> list[RawJob]:
    response = client.get(API_URL.format(slug=entry.slug))
    response.raise_for_status()
    return parse_greenhouse(response.json(), company=entry.name, slug=entry.slug)
