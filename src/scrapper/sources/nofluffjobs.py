import logging
from datetime import datetime, timezone

import httpx

from scrapper.models import RawJob
from scrapper.sources.base import Source  # noqa: F401 - dokumentuje implementowany protokół

logger = logging.getLogger(__name__)

API_URL = "https://nofluffjobs.com/api/search/posting"
OFFER_URL = "https://nofluffjobs.com/pl/job/{slug}"

# Wymagane parametry query string — bez nich API zwraca HTTP 400 (patrz
# docs/sources.md). Ujednolicają walutę/okres wynagrodzenia we wszystkich
# zwróconych ofertach, więc `salary` w odpowiedzi jest zawsze w PLN/miesiąc,
# niezależnie od oryginalnej waluty/okresu podanej przez firmę.
_REQUIRED_PARAMS = {"salaryCurrency": "PLN", "salaryPeriod": "month"}

# Rozmiar strony zaobserwowany empirycznie — API nie przyjmuje parametru
# rozmiaru strony, zwraca stały rozmiar 20 na stronę (ostatnia strona bywa
# krótsza). Pole `totalPages` w odpowiedzi jest myląco niespójne z rzeczywistą
# liczbą stron potrzebną do wyczerpania `totalCount` przy zapytaniu
# nieprzefiltrowanym po mieście — nie polegamy na nim (patrz docs/sources.md).
_PAGE_SIZE = 20


def _location(entry: dict) -> tuple[str | None, bool]:
    location = entry.get("location") or {}
    places = location.get("places") or []
    remote = bool(location.get("fullyRemote"))
    city = next(
        (place.get("city") for place in places if place.get("city") and place.get("city") != "Remote"),
        None,
    )
    return city, remote


def _salary(entry: dict) -> str | None:
    salary = entry.get("salary") or {}
    if (salary.get("disclosedAt") or "").casefold() != "visible":
        return None
    low, high = salary.get("from"), salary.get("to")
    if not low or not high:
        return None
    currency = (salary.get("currency") or "").upper()
    type_ = (salary.get("type") or "").casefold()
    type_label = f" ({type_.upper()})" if type_ else ""

    def _fmt(value):
        return f"{value:g}" if isinstance(value, float) else str(value)

    return f"{_fmt(low)}-{_fmt(high)} {currency}/miesiąc{type_label}".strip()


def _posted_at(entry: dict) -> datetime | None:
    value = entry.get("posted")
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def parse(payload: dict | list) -> list[RawJob]:
    entries = (payload.get("postings") or []) if isinstance(payload, dict) else payload
    jobs = []
    for entry in entries:
        posting_id = entry.get("id")
        slug = entry.get("url")
        if not posting_id or not slug:
            logger.debug("nofluffjobs: pomijam wpis bez id/url: %r", entry)
            continue
        city, remote = _location(entry)
        jobs.append(
            RawJob(
                source="nofluffjobs",
                external_id=str(posting_id),
                title=entry.get("title", ""),
                company=entry.get("name", ""),
                city=city,
                remote=remote,
                url=OFFER_URL.format(slug=slug),
                salary=_salary(entry),
                posted_at=_posted_at(entry),
            )
        )
    return jobs


def _fetch_entries_for_city(client: httpx.Client, city: str | None, max_offers: int) -> list[dict]:
    """Pobiera surowe wpisy `postings[]` dla jednego zapytania (miasto albo brak filtra).

    Paginacja przez parametr query string `page` (1-indeksowany; brak
    parametru = strona 1) — zweryfikowane empirycznie: API zwraca stały
    rozmiar strony 20, kolejne strony mają rozłączne zestawy `id` (patrz
    docs/sources.md). Nie używamy pola odpowiedzi `totalPages` jako warunku
    zatrzymania — jego wartość jest niespójna z faktyczną liczbą stron
    potrzebną do wyczerpania wyników przy zapytaniu bez filtra miasta.

    Kończy pobieranie, gdy:
    - strona nie ma danych (pusta lista) — koniec wyników,
    - strona zwróciła mniej wpisów niż `_PAGE_SIZE` — ostatnia strona,
    - osiągnięto `max_offers`,
    - druga i kolejna strona zwróci błąd HTTP/sieci — traktowane jak w
      justjoinit: koniec paginacji z tym, co już zebrano (`logger.warning`).
      Błąd na pierwszej stronie propaguje się dalej (awaria całego źródła).
    """
    entries: list[dict] = []
    page = 1
    body = {"criteriaSearch": {"city": [city]} if city else {}}

    while len(entries) < max_offers:
        params = {**_REQUIRED_PARAMS, "page": page}
        try:
            response = client.post(API_URL, json=body, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            if page == 1:
                raise
            logger.warning(
                "nofluffjobs: błąd przy pobieraniu kolejnej strony (miasto=%s, page=%d): %s "
                "— zwracam to, co udało się już zebrać (%d wpisów)",
                city, page, exc, len(entries),
            )
            break

        payload = response.json()
        page_entries = (payload.get("postings") or []) if isinstance(payload, dict) else []
        if not page_entries:
            break
        entries.extend(page_entries)

        if len(page_entries) < _PAGE_SIZE:
            break
        page += 1

    return entries[:max_offers]


class NoFluffJobs:
    name = "nofluffjobs"

    def __init__(self, max_offers: int = 2000, cities: list[str] | None = None):
        self.max_offers = max_offers
        self.cities = cities

    def fetch(self, client: httpx.Client) -> list[RawJob]:
        queries = self.cities if self.cities else [None]

        seen_ids: set[str] = set()
        merged_entries: list[dict] = []
        for index, city in enumerate(queries):
            remaining_budget = self.max_offers - len(merged_entries)
            if remaining_budget <= 0:
                logger.warning(
                    "nofluffjobs: max_offers=%d wyczerpany po %d/%d miastach — "
                    "pomijam pozostałe (%s); rozważ podniesienie limitu",
                    self.max_offers, index, len(queries), queries[index:],
                )
                break

            for entry in _fetch_entries_for_city(client, city, remaining_budget):
                posting_id = entry.get("id")
                if posting_id:
                    if posting_id in seen_ids:
                        continue
                    seen_ids.add(posting_id)
                merged_entries.append(entry)

        return parse({"postings": merged_entries})
