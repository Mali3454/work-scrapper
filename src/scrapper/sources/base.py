import logging
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from scrapper.models import Profile, RawJob

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class AllSourcesFailed(RuntimeError):
    """Żadne źródło nie odpowiedziało — system jest zepsuty, nie tylko pusty."""


class Source(Protocol):
    name: str

    def fetch(self, client: httpx.Client) -> list[RawJob]: ...


@dataclass
class SourceResult:
    name: str
    jobs: list[RawJob] = field(default_factory=list)
    error: str | None = None


def build_client(timeout: float = 20.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "pl,en;q=0.8"},
    )


def collect(sources: list[Source], client: httpx.Client) -> list[SourceResult]:
    """Odpytuje każde źródło. Awaria jednego nie przerywa pozostałych.

    Rzuca AllSourcesFailed, gdy padły wszystkie — wtedy przebieg ma się wysypać.
    """
    results = []
    for source in sources:
        try:
            results.append(SourceResult(name=source.name, jobs=source.fetch(client)))
        except Exception as exc:  # noqa: BLE001 - celowo łapiemy wszystko
            logger.warning("Źródło %s padło: %s", source.name, exc)
            results.append(SourceResult(name=source.name, error=f"{type(exc).__name__}: {exc}"))

    if results and all(result.error for result in results):
        raise AllSourcesFailed("Wszystkie źródła zwróciły błąd")
    return results
