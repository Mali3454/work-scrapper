import logging
from pathlib import Path

import httpx
import yaml
from pydantic import BaseModel, ValidationError

from scrapper.models import RawJob
from scrapper.sources.ats.recruitee import fetch_recruitee

logger = logging.getLogger(__name__)


class CompanyEntry(BaseModel):
    """Jeden wpis w rejestrze `companies.yaml`.

    `slug` jest wymagany dla firm z ATS-em obsługiwanym przez fetcher
    (np. `recruitee`), `url` jest informacyjny/przydatny dla wpisów
    `parser: skip` (przyszły research, Task 15).
    """

    name: str
    ats: str
    slug: str | None = None
    url: str | None = None
    parser: str | None = None


def load_companies(path: Path) -> list[CompanyEntry]:
    """Wczytuje rejestr firm. Błąd w pliku nie może zabić przebiegu.

    `companies.yaml` jest plikiem danych edytowanym ręcznie — dopisanie firmy
    to jedna linijka, więc literówka albo złe wcięcie to kwestia czasu.
    Wyjątek poleciałby z `main()` przed odpytaniem czegokolwiek, czyli pomyłka
    przy JEDNEJ firmie kładłaby cały scraper. Zamiast tego: zły plik → pusty
    rejestr, zły wpis → pominięty, oba z logiem ostrzeżenia.
    """
    path = Path(path)
    if not path.exists():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except yaml.YAMLError as exc:
        logger.warning("companies: nie mogę sparsować %s, pomijam rejestr: %s", path, exc)
        return []
    if not isinstance(raw, list):
        logger.warning("companies: %s nie zawiera listy wpisów (jest %s), pomijam rejestr",
                       path, type(raw).__name__)
        return []

    entries = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            logger.warning("companies: wpis #%d w %s nie jest obiektem, pomijam", index, path)
            continue
        try:
            entries.append(CompanyEntry(**item))
        except (ValidationError, TypeError) as exc:
            logger.warning("companies: pomijam błędny wpis #%d w %s: %s", index, path, exc)
    return entries


DEFAULT_FETCHERS = {"recruitee": fetch_recruitee}


class CompaniesSource:
    """Jedno źródło obejmujące wszystkie firmy z `companies.yaml`.

    Awaria jednej firmy (padnięta strona, timeout, HTTP 5xx) jest logowana
    (`logger.warning`) i pomijana — nie może zabrać ze sobą pozostałych
    firm w rejestrze. Wpisy z `parser: skip` oraz z ATS-em, dla którego nie
    ma jeszcze fetchera (np. `lever`, `greenhouse`, `workable`, `traffit` —
    Task 15) są pomijane po cichu z logiem `logger.info`, nie są to awarie.
    """

    name = "companies"

    def __init__(self, entries: list[CompanyEntry], fetchers: dict | None = None):
        self.entries = entries
        self.fetchers = DEFAULT_FETCHERS if fetchers is None else fetchers

    def fetch(self, client: httpx.Client) -> list[RawJob]:
        jobs: list[RawJob] = []
        for entry in self.entries:
            if entry.parser == "skip":
                logger.info("companies: pomijam %s (parser: skip)", entry.name)
                continue
            fetcher = self.fetchers.get(entry.ats)
            if fetcher is None:
                logger.info(
                    "companies: pomijam %s — brak parsera dla ATS '%s'", entry.name, entry.ats
                )
                continue
            if not entry.slug:
                # Bez sluga nie ma z czego zbudować URL-a API. Gdybyśmy weszli
                # w fetcher, poleciałby błąd DNS złapany niżej i zalogowany jako
                # "firma padła" — czyli komunikat o awarii zewnętrznej zamiast
                # o literówce w rejestrze.
                logger.warning(
                    "companies: pomijam %s — ATS '%s' wymaga pola `slug`, którego brakuje",
                    entry.name, entry.ats,
                )
                continue
            try:
                jobs.extend(fetcher(entry, client))
            except Exception as exc:  # noqa: BLE001 - jedna firma nie może ubić reszty
                logger.warning("companies: firma %s padła: %s", entry.name, exc)
        return jobs
