import logging
from pathlib import Path

import httpx
import yaml
from pydantic import BaseModel

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
    path = Path(path)
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [CompanyEntry(**entry) for entry in raw]


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
            try:
                jobs.extend(fetcher(entry, client))
            except Exception as exc:  # noqa: BLE001 - jedna firma nie może ubić reszty
                logger.warning("companies: firma %s padła: %s", entry.name, exc)
        return jobs
