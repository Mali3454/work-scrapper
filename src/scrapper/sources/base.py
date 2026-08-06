import logging
import ssl
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


def _system_trust_ssl_context() -> ssl.SSLContext | None:
    """Zwraca kontekst SSL oparty o systemowy magazyn certyfikatów (truststore).

    Na niektórych maszynach (np. z antywirusem/proxy przechwytującym TLS)
    wbudowana lista `certifi` nie zawiera certyfikatu, którym podmieniane są
    połączenia — a systemowy magazyn (Windows Certificate Store) już go ma,
    bo korzysta z niego przeglądarka i `curl`. `truststore` każe Pythonowi
    weryfikować certyfikaty przez ten sam magazyn.

    Nigdy nie wyłączamy weryfikacji — jeśli pakiet jest niedostępny albo jego
    inicjalizacja się nie powiedzie, wracamy do domyślnej weryfikacji httpx
    (czyli `certifi`), nie do braku weryfikacji.
    """
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception as exc:  # noqa: BLE001 - celowo łapiemy wszystko
        logger.debug("truststore niedostępny, używam domyślnej weryfikacji httpx: %s", exc)
        return None


def build_client(timeout: float = 20.0) -> httpx.Client:
    kwargs = {
        "timeout": timeout,
        "follow_redirects": True,
        "headers": {"User-Agent": USER_AGENT, "Accept-Language": "pl,en;q=0.8"},
    }
    ssl_context = _system_trust_ssl_context()
    if ssl_context is not None:
        kwargs["verify"] = ssl_context
    return httpx.Client(**kwargs)


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
