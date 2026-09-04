"""Bezposrednie API Teamtailor udostepnione przez strone Spyrosoft."""

import httpx

from scrapper.models import RawJob


API_URL = "https://spyro-soft.com/wp-json/teamtailor/v1/get-jobs"


def parse_spyrosoft(payload: dict, company: str, slug: str) -> list[RawJob]:
    jobs: list[RawJob] = []
    for offer in payload.get("jobs") or []:
        offer_id = offer.get("id")
        url = offer.get("url")
        if not offer_id or not url:
            continue
        locations = offer.get("loc") or []
        countries = list(
            dict.fromkeys(
                location.get("country")
                for location in locations
                if location.get("country")
            )
        )
        cities = list(
            dict.fromkeys(
                location.get("city")
                for location in locations
                if location.get("city")
            )
        )
        remote = (offer.get("remote_status") or "").casefold() in {
            "fully",
            "remote",
            "fully_remote",
        }
        salary = None
        low, high = offer.get("min_salary"), offer.get("max_salary")
        if low is not None or high is not None:
            amount = f"{low or '?'}-{high or '?'}"
            salary = " ".join(
                filter(
                    None,
                    [amount, offer.get("currency"), offer.get("salary_time_unit")],
                )
            )
        jobs.append(
            RawJob(
                source=f"company:{slug}",
                external_id=str(offer_id),
                title=offer.get("title", ""),
                company=company,
                city=None if remote else (", ".join(cities) or None),
                remote=remote,
                url=url,
                salary=salary,
                # API nie zwraca wiarygodnej daty publikacji. Deduper dopilnuje,
                # zeby aktywna oferta bez daty zostala wyslana tylko raz.
                posted_at=None,
                skills=[str(skill) for skill in offer.get("skills") or []],
                search_text=offer.get("body") or "",
                country=countries[0] if len(countries) == 1 else None,
            )
        )
    return jobs


def fetch_spyrosoft(entry, client: httpx.Client, page_size: int = 50) -> list[RawJob]:
    jobs: list[RawJob] = []
    page = 1
    while True:
        response = client.get(API_URL, params={"page": page, "per_page": page_size})
        response.raise_for_status()
        payload = response.json() or {}
        page_jobs = parse_spyrosoft(payload, entry.name, entry.slug)
        jobs.extend(page_jobs)
        total = int(payload.get("total") or 0)
        if not page_jobs or len(jobs) >= total:
            return jobs
        page += 1
