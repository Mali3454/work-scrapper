import logging
import re
from datetime import datetime

import httpx

from scrapper.models import RawJob

logger = logging.getLogger(__name__)

API_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"

# `location.name` w Greenhouse to zwykle pełny adres w stylu
# "ul. Zbożowa 4, 70-653 Stettin" (home.pl, zweryfikowane na żywo — patrz
# docs/sources.md) — miasto jest w OSTATNIM segmencie po przecinku, poprzedzone
# kodem pocztowym. Wzorzec kodu pocztowego PL: "NN-NNN".
_POSTAL_CODE = re.compile(r"^\d{2}-\d{3}\s+")

# Greenhouse (albo firma wprowadzająca dane) używa niemieckich egzonimów dla
# części polskich miast zamiast nazw polskich — potwierdzone bezpośrednio na
# żywych danych home.pl: "Stettin" zamiast "Szczecin". Bez tej mapy
# `matcher._location_ok` (dopasowanie substringiem, casefold) NIE złapie
# żadnej oferty ze Szczecina, bo "szczecin" nie jest podciągiem "stettin" —
# a home.pl to jedyna szczecińska firma w całym projekcie z żywym ATS-em
# (patrz task-15-brief.md). Pozostałe wpisy (Warschau, Krakau, Danzig,
# Breslau, Posen) NIE są potwierdzone realnymi danymi z żadnego innego
# zweryfikowanego boarda Greenhouse w tym projekcie — dopisane defensywnie,
# bo Greenhouse jako platforma używana też przez firmy niemieckojęzyczne
# realnie stosuje egzonimy (potwierdzone dla Stettin), więc ryzyko tego
# samego dla innych miast jest realne, ale nie zweryfikowane.
_CITY_EXONYMS = {
    "stettin": "Szczecin",  # POTWIERDZONE: home.pl, boards-api/v1/boards/homepl/jobs
    "warschau": "Warszawa",  # niepotwierdzone na żywych danych
    "krakau": "Kraków",  # niepotwierdzone na żywych danych
    "danzig": "Gdańsk",  # niepotwierdzone na żywych danych
    "breslau": "Wrocław",  # niepotwierdzone na żywych danych
    "posen": "Poznań",  # niepotwierdzone na żywych danych
}


def _extract_city(location_name: str | None) -> str | None:
    """Wyciąga nazwę miasta z pełnego adresu i normalizuje egzonimy.

    `location.name` bywa pełnym adresem ("ul. Zbożowa 4, 70-653 Stettin"),
    nie samą nazwą miasta — bierzemy ostatni segment po przecinku i odcinamy
    poprzedzający go kod pocztowy.
    """
    if not location_name:
        return None
    segment = location_name.split(",")[-1].strip()
    segment = _POSTAL_CODE.sub("", segment).strip()
    if not segment:
        return None
    mapped = _CITY_EXONYMS.get(segment.casefold())
    return mapped if mapped is not None else segment


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
    """
    jobs = []
    for offer in payload.get("jobs") or []:
        url = offer.get("absolute_url")
        if not url:
            logger.debug("greenhouse(%s): pomijam ofertę bez URL: %r", slug, offer)
            continue
        offer_id = offer.get("id")
        location = offer.get("location") or {}
        posted_at = _parse_datetime(offer.get("first_published")) or _parse_datetime(
            offer.get("updated_at")
        )
        jobs.append(
            RawJob(
                source=f"company:{slug}",
                external_id=str(offer_id) if offer_id is not None else url,
                title=offer.get("title", ""),
                company=company,
                city=_extract_city(location.get("name")),
                remote=False,
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
