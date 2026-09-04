"""Publiczna lista ofert BambooHR Careers."""

from urllib.parse import urljoin

import httpx

from scrapper.models import RawJob


def parse_bamboohr(payload: dict, entry) -> list[RawJob]:
    jobs: list[RawJob] = []
    for offer in payload.get("result", []):
        offer_id = str(offer.get("id") or "").strip()
        title = str(offer.get("jobOpeningName") or "").strip()
        if not offer_id or not title:
            continue

        location = offer.get("location") or {}
        ats_location = offer.get("atsLocation") or {}
        city = location.get("city") or ats_location.get("city")
        country = ats_location.get("country")
        remote = bool(offer.get("isRemote"))
        jobs.append(
            RawJob(
                source=f"company:{entry.slug}",
                external_id=offer_id,
                title=title,
                company=entry.name,
                city=None if remote else city,
                country=country,
                remote=remote,
                url=urljoin(entry.url.rstrip("/") + "/", offer_id),
                posted_at=None,
                search_text=str(offer.get("departmentLabel") or ""),
            )
        )
    return jobs


def fetch_bamboohr(entry, client: httpx.Client) -> list[RawJob]:
    if not entry.api_url:
        raise ValueError("BambooHR wymaga pola api_url")
    response = client.get(entry.api_url)
    response.raise_for_status()
    return parse_bamboohr(response.json(), entry)
