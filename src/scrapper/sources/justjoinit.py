import logging
from datetime import datetime

import httpx

from scrapper.models import RawJob
from scrapper.sources.base import Source, build_queries  # noqa: F401 - Source dokumentuje protokół

logger = logging.getLogger(__name__)

API_URL = "https://justjoin.it/api/candidate-api/offers"
OFFER_URL = "https://justjoin.it/job-offer/{slug}"

# Twardy limit okna wyników API (patrz docs/sources.md) — żądania z
# from + itemsCount > _WINDOW_LIMIT kończą się HTTP 500.
_WINDOW_LIMIT = 10000

# Priorytet typu umowy przy wyborze wpisu wynagrodzenia (patrz docs/sources.md).
_TYPE_PRIORITY = ("b2b", "permanent")


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _type_rank(type_value: str | None) -> int:
    normalized = (type_value or "").casefold()
    if normalized in _TYPE_PRIORITY:
        return _TYPE_PRIORITY.index(normalized)
    return len(_TYPE_PRIORITY)


def _salary(entry: dict) -> str | None:
    types = entry.get("employmentTypes") or []
    candidates = [
        item
        for item in types
        if (item.get("currencySource") or "").casefold() == "original"
        and item.get("from")
        and item.get("to")
    ]
    if not candidates:
        return None

    candidates.sort(key=lambda item: _type_rank(item.get("type")))
    chosen = candidates[0]

    low, high = chosen.get("from"), chosen.get("to")
    currency = (chosen.get("currency") or "").upper()
    unit = (chosen.get("unit") or "").casefold()
    type_ = (chosen.get("type") or "").casefold()

    unit_label = "/miesiąc" if unit == "month" else (f"/{unit}" if unit else "")
    type_label = f" ({type_.upper()})" if type_ else ""

    def _fmt(value):
        return f"{value:g}" if isinstance(value, float) else str(value)

    return f"{_fmt(low)}-{_fmt(high)} {currency}{unit_label}{type_label}".strip()


def _skills(entry: dict) -> list[str]:
    """Nazwy z `requiredSkills`/`niceToHaveSkills`.

    Format to lista OBIEKTÓW `{"name": ..., "level": ...}`, nie stringów —
    potraktowanie ich jak stringi daje `TypeError` przy sklejaniu. Nazwa
    narzędzia bywa tylko tutaj i nigdy w tytule (patrz `RawJob.skills`).
    """
    names = []
    for key in ("requiredSkills", "niceToHaveSkills"):
        for skill in entry.get(key) or []:
            name = skill.get("name") if isinstance(skill, dict) else skill
            if name:
                names.append(str(name))
    return names


def parse(payload: dict | list, source: str = "justjoinit",
          offer_url: str = OFFER_URL) -> list[RawJob]:
    """Mapuje odpowiedź API rodziny justjoin.it na `RawJob`.

    `source`/`offer_url` są parametrami, bo RocketJobs.pl (ten sam operator)
    wystawia BAJT W BAJT tę samą strukturę odpowiedzi — różni się wyłącznie
    hostem i ścieżką oferty. Kopiowanie parsera byłoby dublowaniem także
    wszystkich pułapek (widełki, paginacja `from`, limit okna).
    """
    entries = (payload.get("data") or []) if isinstance(payload, dict) else payload
    jobs = []
    for entry in entries:
        guid = entry.get("guid")
        slug = entry.get("slug")
        if not guid or not slug:
            continue
        jobs.append(
            RawJob(
                source=source,
                external_id=guid,
                title=entry.get("title", ""),
                company=entry.get("companyName", ""),
                city=entry.get("city"),
                remote=(entry.get("workplaceType") or "").casefold() == "remote",
                url=offer_url.format(slug=slug),
                salary=_salary(entry),
                posted_at=_parse_datetime(entry.get("publishedAt")),
                skills=_skills(entry),
            )
        )
    return jobs


_PAGE_SIZE = 100


def _fetch_entries_for_city(
    client: httpx.Client, city: str | None, max_offers: int, page_size: int | None = None,
    api_url: str = API_URL,
) -> list[dict]:
    """Pobiera surowe wpisy `data[]` dla jednego zapytania (miasto albo brak filtra).

    Paginacja przez parametr `from` (nie `cursor` — nazwa parametru z briefu i
    ze wstępnej wersji `docs/sources.md` była błędna, zweryfikowano na żywym
    API: patrz `docs/sources.md`). Wartość `meta.next.cursor` z odpowiedzi to
    liczba, którą trzeba przekazać jako `from` w kolejnym zapytaniu.

    Kończy pobieranie, gdy:
    - odpowiedź nie ma danych (pusta lista) — koniec wyników,
    - strona zwróciła mniej wpisów niż żądano — ostatnia strona,
    - `meta.next.cursor` brak/`None`,
    - osiągnięto `max_offers`,
    - kolejna (nie pierwsza) strona zwróci błąd HTTP. Tu rozróżniamy dwa
      przypadki: znany, łagodny limit okna wyników (`HTTPStatusError` 500 przy
      `from + itemsCount > _WINDOW_LIMIT`) kończy paginację po cichu
      (`logger.debug`) — to oczekiwane zachowanie API, nie awaria. Każdy inny
      błąd HTTP (przeciążenie 502/503, timeout, cokolwiek innego) też kończy
      paginację dla tego miasta, ale głośno — `logger.warning` z nazwą
      miasta i offsetem — bo to realna, cicha utrata części danych, o której
      wywołujący (i finalnie użytkownik) musi się dowiedzieć. Błąd na
      pierwszej stronie w obu gałęziach propaguje się dalej bez zmian — to
      całkowita awaria źródła, łapana przez `collect()`.
    """
    if page_size is None:
        page_size = _PAGE_SIZE  # odczytane dynamicznie — testowalne przez monkeypatch

    entries: list[dict] = []
    from_: int | None = None

    while len(entries) < max_offers:
        remaining = max_offers - len(entries)
        items_count = min(page_size, remaining)
        params: dict = {"itemsCount": items_count}
        if from_ is not None:
            params["from"] = from_
        if city:
            params["city"] = city

        try:
            response = client.get(api_url, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if from_ is None:
                raise
            is_window_limit = (
                exc.response is not None
                and exc.response.status_code == 500
                and from_ + items_count > _WINDOW_LIMIT
            )
            if is_window_limit:
                logger.debug(
                    "justjoinit: limit okna wyników API osiągnięty (miasto=%s, from=%d, "
                    "itemsCount=%d) — kończę paginację",
                    city, from_, items_count,
                )
            else:
                logger.warning(
                    "justjoinit: błąd HTTP przy pobieraniu kolejnej strony (miasto=%s, "
                    "from=%d): %s — zwracam to, co udało się już zebrać (%d wpisów)",
                    city, from_, exc, len(entries),
                )
            break
        except httpx.HTTPError as exc:
            if from_ is None:
                raise
            logger.warning(
                "justjoinit: błąd sieci przy pobieraniu kolejnej strony (miasto=%s, "
                "from=%d): %s — zwracam to, co udało się już zebrać (%d wpisów)",
                city, from_, exc, len(entries),
            )
            break

        payload = response.json()
        page_entries = (payload.get("data") or []) if isinstance(payload, dict) else []
        if not page_entries:
            break
        entries.extend(page_entries)

        if len(page_entries) < items_count:
            break

        cursor = ((payload.get("meta") or {}).get("next") or {}).get("cursor")
        if cursor is None:
            break
        from_ = cursor

    return entries[:max_offers]


class JustJoinIt:
    """Źródło justjoin.it. Klasa bazowa także dla RocketJobs.pl — ten sam
    operator wystawia identyczne API, więc podklasa podmienia tylko trzy stałe
    (patrz `sources/rocketjobs.py`)."""

    name = "justjoinit"
    api_url = API_URL
    offer_url = OFFER_URL

    def __init__(self, max_offers: int = 2000, cities: list[str] | None = None,
                 include_nationwide: bool = False):
        self.max_offers = max_offers
        self.cities = cities
        self.include_nationwide = include_nationwide

    def fetch(self, client: httpx.Client) -> list[RawJob]:
        queries = build_queries(self.cities, self.include_nationwide)

        seen_guids: set[str] = set()
        merged_entries: list[dict] = []
        for index, city in enumerate(queries):
            remaining_budget = self.max_offers - len(merged_entries)
            if remaining_budget <= 0:
                logger.warning(
                    "%s: max_offers=%d wyczerpany po %d/%d miastach — "
                    "pomijam pozostałe (%s); rozważ podniesienie limitu",
                    self.name, self.max_offers, index, len(queries), queries[index:],
                )
                break

            for entry in _fetch_entries_for_city(client, city, remaining_budget,
                                                 api_url=self.api_url):
                guid = entry.get("guid")
                if guid:
                    if guid in seen_guids:
                        continue
                    seen_guids.add(guid)
                merged_entries.append(entry)

        return parse({"data": merged_entries}, source=self.name, offer_url=self.offer_url)
