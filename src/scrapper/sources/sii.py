"""Bezposrednie publiczne API ofert na stronie Sii Polska."""

from datetime import datetime

import httpx

from scrapper.models import RawJob


API_URL = (
    "https://web-job-api.sii.pl/offers/en/"
    "all/all/all/all/all/all/all/all/score/desc/{page}/{page_size}/pl"
)
OFFER_URL = "https://sii.pl/en/job-ads/id/{offer_id}/"


def _datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _cities(offer: dict) -> list[str]:
    result: list[str] = []
    for location in offer.get("locations") or []:
        children = location.get("locations") or []
        if children:
            result.extend(child.get("name") for child in children if child.get("name"))
        elif location.get("name"):
            result.append(location["name"])
    return list(dict.fromkeys(result))


def _countries(offer: dict) -> list[str]:
    return list(dict.fromkeys(
        location.get("name")
        for location in offer.get("locations") or []
        if location.get("name")
    ))


def parse_sii(payload: dict, company: str, slug: str) -> list[RawJob]:
    jobs: list[RawJob] = []
    for offer in payload.get("offers") or []:
        offer_id = offer.get("offerId")
        if offer_id is None:
            continue
        cities = _cities(offer)
        countries = _countries(offer)
        work_modes = " ".join(
            mode.get("name", "") for mode in offer.get("workModes") or []
        )
        remote = "remote" in work_modes.casefold()
        jobs.append(
            RawJob(
                source=f"company:{slug}",
                external_id=str(offer_id),
                title=offer.get("title", ""),
                company=company,
                # Zachowujemy wszystkie miasta. Matcher sprawdza podciag, wiec
                # oferta wielolokalizacyjna obejmujaca Szczecin nie zniknie.
                city=None if remote else (", ".join(cities) or None),
                remote=remote,
                url=OFFER_URL.format(offer_id=offer_id),
                posted_at=_datetime(offer.get("publicationDate")),
                country=countries[0] if len(countries) == 1 else None,
            )
        )
    return jobs


def fetch_sii(entry, client: httpx.Client, page_size: int = 100) -> list[RawJob]:
    jobs: list[RawJob] = []
    page = 0
    while True:
        response = client.get(API_URL.format(page=page, page_size=page_size))
        response.raise_for_status()
        payload = response.json() or {}
        page_jobs = parse_sii(payload, entry.name, entry.slug)
        jobs.extend(page_jobs)
        total = int(payload.get("total") or 0)
        if not page_jobs or len(jobs) >= total:
            return jobs
        page += 1
