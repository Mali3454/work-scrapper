import logging
from datetime import datetime

import httpx

from scrapper.models import RawJob
from scrapper.sources.ats.location import extract_city

logger = logging.getLogger(__name__)

API_URL = "https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"


def _parse_datetime(value: str | None) -> datetime | None:
    """`published_on` to sama data ("2026-07-14"), bez godziny/strefy —
    zweryfikowane na żywo. `fromisoformat` zwróci naive datetime;
    `RawJob.normalize_posted_at` (models.py) dopisze UTC, więc nie trzeba
    tego robić tutaj.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_workable(payload: dict, company: str, slug: str) -> list[RawJob]:
    """Mapuje odpowiedź `GET .../widget/accounts/<slug>?details=true` na `RawJob`.

    `id` NIE istnieje w tym API (zweryfikowane na żywo) — identyfikatorem
    jest `shortcode`.

    `city` bywa pustym stringiem `""`, NIE `null`, gdy oferta nie ma podanej
    lokalizacji (zweryfikowane na żywo: netguru, oferty freelance/remote) —
    `entry.get("city") or None` jest konieczne, inaczej `RawJob.city`
    dostałby `""` i klucz deduplikacji miałby pusty segment zamiast braku
    segmentu.
    """
    jobs = []
    for offer in payload.get("jobs") or []:
        url = offer.get("url") or offer.get("shortlink")
        if not url:
            logger.debug("workable(%s): pomijam ofertę bez URL: %r", slug, offer)
            continue
        shortcode = offer.get("shortcode")
        jobs.append(
            RawJob(
                source=f"company:{slug}",
                external_id=str(shortcode) if shortcode else url,
                title=offer.get("title", ""),
                company=company,
                # Przez wspólną normalizację, jak Greenhouse i Lever — Workable
                # ma osobne pole `city`, więc adres/kraj się tu nie trafi, ale
                # egzonimy i marker "Remote" muszą działać tak samo we
                # wszystkich ATS-ach, inaczej dedup między nimi się rozjeżdża.
                city=extract_city(offer.get("city")),
                remote=bool(offer.get("telecommuting")),
                url=url,
                salary=None,
                posted_at=_parse_datetime(offer.get("published_on")),
            )
        )
    return jobs


def fetch_workable(entry, client: httpx.Client) -> list[RawJob]:
    response = client.get(API_URL.format(slug=entry.slug))
    response.raise_for_status()
    return parse_workable(response.json(), company=entry.name, slug=entry.slug)
