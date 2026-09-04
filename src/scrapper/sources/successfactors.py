"""Firmowe strony karier oparte o SAP SuccessFactors Recruiting Marketing."""

from datetime import datetime, timezone
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser

from scrapper.models import RawJob
from scrapper.sources.ats.location import extract_city, is_remote


def _text(node) -> str:
    return " ".join(node.text().split()) if node is not None else ""


def _date(value: str) -> datetime | None:
    normalized = value.replace("Sept", "Sep")
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(normalized, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def parse_successfactors(html: str, entry) -> list[RawJob]:
    tree = HTMLParser(html)
    jobs: list[RawJob] = []
    seen: set[str] = set()
    for tile in tree.css(".job-row"):
        desktop = tile.css_first(".sub-section-desktop") or tile
        link = desktop.css_first("a.jobTitle-link")
        if link is None:
            continue
        href = link.attributes.get("href") or ""
        url = urljoin(entry.url, href)
        if not href or url in seen:
            continue
        seen.add(url)
        city_raw = _text(desktop.css_first(".section-field.customfield5 div[id$='-value']"))
        date_raw = _text(desktop.css_first(".section-field.date div[id$='-value']"))
        external_id = href.rstrip("/").rsplit("/", 1)[-1]
        jobs.append(
            RawJob(
                source=f"company:{entry.slug}",
                external_id=external_id or url,
                title=_text(link),
                company=entry.name,
                city=extract_city(city_raw),
                remote=is_remote(city_raw),
                url=url,
                posted_at=_date(date_raw),
            )
        )
    return jobs


def fetch_successfactors(entry, client: httpx.Client) -> list[RawJob]:
    if not entry.url:
        raise ValueError("SuccessFactors wymaga pola url")
    response = client.get(entry.url)
    response.raise_for_status()
    return parse_successfactors(response.text, entry)
