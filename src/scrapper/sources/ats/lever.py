import logging
from datetime import datetime, timezone

import httpx

from scrapper.models import RawJob
from scrapper.sources.ats.location import extract_city

logger = logging.getLogger(__name__)

API_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"


def _city(categories: dict) -> str | None:
    """Wyciąga miasto z `categories.location`.

    Na pipedrive format to "Kraj, Miasto" ("Portugal, Lisbon", "UK, London"),
    ale `categories.location` to pole wpisywane swobodnie przez firmę, nie
    enum — inne boardy Levera używają "Miasto, Kraj" albo "Miasto, Stan".
    Reguła "weź ostatni segment" dopasowana do pipedrive zwracałaby "Poland"
    dla "Warsaw, Poland". Dlatego normalizacja jest wspólna dla wszystkich
    ATS-ów (`location.extract_city`) i odrzuca kraje zamiast liczyć na
    kolejność segmentów.
    """
    return extract_city((categories or {}).get("location"))


def _remote(offer: dict) -> bool:
    """`workplaceType` ("hybrid" / "remote" / "on-site") jest polem wprost
    zwracanym przez API — użyte zamiast heurystyki słów kluczowych po
    `location`/`categories.location`, tak samo jak w Recruitee (`remote`) i
    JustJoinIT (`workplaceType` tam też, ale nazwane inaczej). Heurystyka po
    tekście lokalizacji jest fallbackiem tylko, gdy pole brakuje — w
    zbadanej próbce (pipedrive, 16 ofert) zawsze obecne jako "hybrid".
    """
    workplace_type = (offer.get("workplaceType") or "").casefold()
    if workplace_type:
        return workplace_type == "remote"
    text = f"{offer.get('text', '')} {(offer.get('categories') or {}).get('location', '')}"
    return "remote" in text.casefold()


def _parse_datetime(value) -> datetime | None:
    """`createdAt` to milisekundy epoch (int) — potwierdzone na żywo."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def parse_lever(payload: list, company: str, slug: str) -> list[RawJob]:
    """Mapuje odpowiedź `GET https://api.lever.co/v0/postings/<slug>?mode=json`
    na `RawJob`.

    Payload to LISTA ofert (nie obiekt z kluczem), zweryfikowane na żywo
    (pipedrive, 16 ofert) — w przeciwieństwie do Recruitee/Greenhouse,
    gdzie lista jest zagnieżdżona pod kluczem.

    `categories.allLocations` (lista, oferta bywa w kilku miastach) jest
    świadomie NIE rozbijana na osobne `RawJob` — jedna oferta Lever = jeden
    wpis, z `city` z `categories.location` (główna lokalizacja). Powód: Lever
    i tak zwraca osobną ofertę z własnym `id` per lokalizacja (zweryfikowane
    na pipedrive — "Data Protection Officer" występuje 4 razy, po razie na
    miasto), więc rozbijanie zdublowałoby to, co API już rozbiło.

    Koszt tej decyzji: oferta, w której Szczecin jest lokalizacją inną niż
    główna, nie zostanie złapana po mieście.
    """
    jobs = []
    for offer in payload or []:
        url = offer.get("hostedUrl") or offer.get("applyUrl")
        if not url:
            logger.debug("lever(%s): pomijam ofertę bez URL: %r", slug, offer)
            continue
        offer_id = offer.get("id")
        jobs.append(
            RawJob(
                source=f"company:{slug}",
                external_id=str(offer_id) if offer_id is not None else url,
                title=offer.get("text", ""),
                company=company,
                city=_city(offer.get("categories") or {}),
                remote=_remote(offer),
                url=url,
                salary=None,
                posted_at=_parse_datetime(offer.get("createdAt")),
            )
        )
    return jobs


def fetch_lever(entry, client: httpx.Client) -> list[RawJob]:
    response = client.get(API_URL.format(slug=entry.slug))
    response.raise_for_status()
    return parse_lever(response.json(), company=entry.name, slug=entry.slug)
