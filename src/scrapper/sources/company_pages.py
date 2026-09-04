"""Proste, bezposrednie strony karier bez zewnetrznego ATS-a."""

import re
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser

from scrapper.models import RawJob
from scrapper.sources.ats.location import extract_city, is_remote


_LOCATION_RE = re.compile(
    r"(?:location|lokalizacja|miejsce pracy)\s*:\s*([^,\[\].;]+)", re.IGNORECASE
)


def _clean(value: str | None) -> str:
    return " ".join((value or "").split())


def _location(text: str, fallback: str | None) -> tuple[str | None, bool]:
    match = _LOCATION_RE.search(text)
    raw = _clean(match.group(1)) if match else (_clean(text) or fallback)
    remote = is_remote(raw) or is_remote(text)
    city = extract_city(raw)
    # Firmowe karty czesto zwracaja caly opis biura z numerem ulicy bez
    # przecinka. Normalizator slusznie nie uznaje go za nazwe miasta, ale
    # zachowanie tekstu pozwala matcherowi znalezc w nim "Szczecin".
    return (None if remote else (city or raw or None)), remote


def _job(
    entry, title: str, url: str, text: str, index: int, *, use_text_location: bool
) -> RawJob:
    city, remote = _location(text if use_text_location else "", entry.city)
    return RawJob(
        source=f"company:{entry.slug}",
        external_id=url or str(index),
        title=title,
        company=entry.name,
        city=city,
        remote=remote,
        url=url,
        posted_at=None,
        search_text=text,
    )


def parse_company_page(html: str, entry) -> list[RawJob]:
    tree = HTMLParser(html)
    jobs: list[RawJob] = []
    seen: set[str] = set()

    if entry.parser == "html_cards":
        if not entry.item_selector or not entry.title_selector:
            raise ValueError("html_cards wymaga item_selector i title_selector")
        for index, item in enumerate(tree.css(entry.item_selector)):
            title_node = item.css_first(entry.title_selector)
            if entry.link_selector:
                link_node = item.css_first(entry.link_selector)
            elif item.attributes.get("href"):
                link_node = item
            else:
                link_node = title_node
            if title_node is None or link_node is None:
                continue
            title = _clean(title_node.text())
            url = urljoin(entry.url, link_node.attributes.get("href") or "")
            location_node = (
                item.css_first(entry.location_selector) if entry.location_selector else None
            )
            text = _clean(location_node.text() if location_node else item.text())
            if not title or not url or url in seen:
                continue
            seen.add(url)
            jobs.append(
                _job(
                    entry,
                    title,
                    url,
                    text,
                    index,
                    use_text_location=location_node is not None,
                )
            )
        return jobs

    if entry.parser == "html_links":
        if not entry.link_selector:
            raise ValueError("html_links wymaga link_selector")
        for index, link in enumerate(tree.css(entry.link_selector)):
            title = _clean(link.text())
            url = urljoin(entry.url, link.attributes.get("href") or "")
            if not title or not url or url in seen:
                continue
            seen.add(url)
            jobs.append(
                _job(entry, title, url, title, index, use_text_location=False)
            )
        return jobs

    raise ValueError(f"Nieznany parser strony HTML: {entry.parser!r}")


def fetch_company_page(entry, client: httpx.Client) -> list[RawJob]:
    if not entry.url:
        raise ValueError("Zrodlo HTML wymaga pola url")
    response = client.get(entry.url)
    response.raise_for_status()
    return parse_company_page(response.text, entry)
