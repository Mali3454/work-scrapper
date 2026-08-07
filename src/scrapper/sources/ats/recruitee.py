import logging
from datetime import datetime, timezone

import httpx

from scrapper.models import RawJob

logger = logging.getLogger(__name__)

API_URL = "https://{slug}.recruitee.com/api/offers/"

# Format zaobserwowany empirycznie w realnej odpowiedzi API (patrz
# docs/sources.md): "2026-07-17 11:00:39 UTC" — NIE jest to ISO 8601 (spacja
# zamiast "T", literalny sufiks "UTC" zamiast "Z"/offsetu). Trzeba odciąć
# sufiks przed przekazaniem do `datetime.fromisoformat`.
_UTC_SUFFIX = " UTC"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    if value.endswith(_UTC_SUFFIX):
        value = value[: -len(_UTC_SUFFIX)]
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _salary(salary: dict | None) -> str | None:
    """Buduje string widełek. Obsługuje też widełki jednostronne.

    "od 15 000 PLN" bez górnej granicy to w polskich ofertach B2B częsty
    wzorzec — odrzucenie takiej oferty jako "bez widełek" gubiłoby informację,
    którą API realnie zwróciło. Porównania są przez `is None`, bo `0` jest
    poprawną (choć nietypową) wartością dolnej granicy.
    """
    if not salary:
        return None
    low, high = salary.get("min"), salary.get("max")
    if low is None and high is None:
        return None
    currency = (salary.get("currency") or "").upper()
    period = (salary.get("period") or "").casefold()
    period_label = f"/{period}" if period else ""

    def _fmt(value):
        return f"{value:g}" if isinstance(value, float) else str(value)

    if low is None:
        amount = f"do {_fmt(high)}"
    elif high is None:
        amount = f"od {_fmt(low)}"
    else:
        amount = f"{_fmt(low)}-{_fmt(high)}"

    return f"{amount} {currency}{period_label}".strip()


def parse_recruitee(payload: dict, company: str, slug: str) -> list[RawJob]:
    """Mapuje odpowiedź `GET https://<slug>.recruitee.com/api/offers/` na `RawJob`.

    `company` pochodzi z rejestru (`companies.yaml`), NIE z pola `company_name`
    zwracanego przez API — dzięki temu nazwa firmy jest spójna między źródłami
    i deduplikacja (`deduper.py`) działa poprawnie (patrz Task 14).
    """
    jobs = []
    for offer in payload.get("offers") or []:
        url = offer.get("careers_url") or offer.get("careers_apply_url")
        if not url:
            logger.debug("recruitee(%s): pomijam ofertę bez URL: %r", slug, offer)
            continue
        offer_id = offer.get("id")
        remote = bool(offer.get("remote"))
        city = offer.get("city")
        # `city` w Recruitee to siedziba firmy, NIE miejsce wykonywania pracy —
        # oferta zdalna też ma tam wpisane miasto centrali (patrz docs/sources.md).
        # Zostawienie go dałoby klucz deduplikacji `...|poznan` dla oferty, którą
        # portal pokazuje jako zdalną bez miasta — ta sama oferta z dwóch źródeł
        # nie scaliłaby się. Przy ofercie zdalnej miasto zerujemy.
        if remote and (offer.get("location") or "").strip().casefold() == "remote job":
            city = None
        jobs.append(
            RawJob(
                source=f"company:{slug}",
                external_id=str(offer_id) if offer_id is not None else url,
                title=offer.get("title", ""),
                company=company,
                city=city,
                # Pole `remote` (bool) jest zwracane wprost przez API — nie
                # trzeba go wyprowadzać heurystyką ze stringów lokalizacji.
                remote=remote,
                url=url,
                salary=_salary(offer.get("salary")),
                posted_at=_parse_datetime(offer.get("published_at")),
            )
        )
    return jobs


def fetch_recruitee(entry, client: httpx.Client) -> list[RawJob]:
    response = client.get(API_URL.format(slug=entry.slug))
    response.raise_for_status()
    return parse_recruitee(response.json(), company=entry.name, slug=entry.slug)
