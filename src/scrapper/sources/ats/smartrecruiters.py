"""SmartRecruiters — publiczne API ofert per firma.

Powód: TietoEVRY ma biuro w Szczecinie (aleja Piastów 30) i wystawia tam
realne oferty IT — 14 na 372 w chwili weryfikacji (juniorzy C/C++, DevOps,
testerzy). Do tej pory wpis miał `parser: skip`, więc te oferty nie docierały
nigdzie.

PUŁAPKA — zły slug NIE daje błędu. `GET .../companies/<cokolwiek>/postings`
zwraca HTTP 200 z `totalFound: 0`, nie 404. Sprawdzone: `Tieto` → 0,
`TietoEVRY` → 0, `tietoevry` → 0, a poprawny jest `Tieto2` → 372. Literówka
w `companies.yaml` cicho wyzeruje firmę; jedynym sygnałem jest ostrzeżenie
o zerowej liczbie ofert w stopce maila.
"""

import logging
from datetime import datetime

import httpx

from scrapper.models import RawJob
from scrapper.sources.ats.location import extract_city, is_remote

logger = logging.getLogger(__name__)

API_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
# Kanoniczny adres publiczny. Zweryfikowany negatywnie: zmyślone id daje
# HTTP 400. Wariant `careers.smartrecruiters.com` odpada — zwraca 200 także
# dla zmyślonego id, więc nie dałoby się nim potwierdzić, że oferta istnieje.
OFFER_URL = "https://jobs.smartrecruiters.com/{slug}/{posting_id}"

# API zwraca maks. 100 pozycji na stronę; paginacja przez `offset`.
_PAGE_SIZE = 100


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_smartrecruiters(payload: dict, company: str, slug: str) -> list[RawJob]:
    jobs = []
    for posting in payload.get("content") or []:
        posting_id = posting.get("id")
        if not posting_id:
            logger.debug("smartrecruiters(%s): pomijam ofertę bez id: %r", slug, posting)
            continue
        location = posting.get("location") or {}
        city_raw = location.get("city")
        # `location.remote` to prawdziwy bool zwracany przez API — nie trzeba
        # heurystyki po tekście. `is_remote` na nazwie miasta jest tylko
        # zabezpieczeniem, gdy firma wpisała "Remote" jako miasto.
        remote = bool(location.get("remote")) or is_remote(city_raw)
        jobs.append(
            RawJob(
                source=f"company:{slug}",
                external_id=str(posting_id),
                title=posting.get("name", ""),
                company=company,
                # Wspólna normalizacja jak w pozostałych ATS-ach — SmartRecruiters
                # zwraca m.in. "Warsaw"/"Wroclaw" obok "Wrocław", a bez tego
                # klucz deduplikacji rozjeżdżałby się z portalami.
                city=extract_city(city_raw),
                remote=remote,
                url=OFFER_URL.format(slug=slug, posting_id=posting_id),
                salary=None,  # brak pola wynagrodzenia w tym endpoincie
                posted_at=_parse_datetime(posting.get("releasedDate")),
            )
        )
    return jobs


def fetch_smartrecruiters(entry, client: httpx.Client, max_offers: int = 2000) -> list[RawJob]:
    """Pobiera wszystkie oferty firmy, stronicując po `offset`.

    Bez paginacji widzielibyśmy tylko pierwsze 100 z 372 ofert TietoEVRY, a
    API nie sortuje tak, by szczecińskie były na początku — przy limicie 100
    w próbce nie było ani jednej oferty ze Szczecina.
    """
    content: list[dict] = []
    offset = 0
    while len(content) < max_offers:
        response = client.get(
            API_URL.format(slug=entry.slug),
            params={"limit": _PAGE_SIZE, "offset": offset},
        )
        response.raise_for_status()
        page = (response.json() or {}).get("content") or []
        if not page:
            break
        content.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    return parse_smartrecruiters({"content": content[:max_offers]},
                                 company=entry.name, slug=entry.slug)
