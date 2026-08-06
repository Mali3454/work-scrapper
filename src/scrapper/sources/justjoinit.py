from datetime import datetime

import httpx

from scrapper.models import RawJob
from scrapper.sources.base import Source  # noqa: F401 - dokumentuje implementowany protokół

API_URL = "https://justjoin.it/api/candidate-api/offers"
OFFER_URL = "https://justjoin.it/job-offer/{slug}"

# Priorytet typu umowy przy wyborze wpisu wynagrodzenia (patrz docs/sources.md).
_TYPE_PRIORITY = ("b2b", "permanent")


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _type_rank(type_value: str | None) -> int:
    normalized = (type_value or "").casefold()
    if normalized in _TYPE_PRIORITY:
        return _TYPE_PRIORITY.index(normalized)
    return len(_TYPE_PRIORITY)


def _salary(entry: dict) -> str | None:
    types = entry.get("employmentTypes") or []
    candidates = [
        item
        for item in types
        if (item.get("currencySource") or "").casefold() == "original"
        and item.get("from")
        and item.get("to")
    ]
    if not candidates:
        return None

    candidates.sort(key=lambda item: _type_rank(item.get("type")))
    chosen = candidates[0]

    low, high = chosen.get("from"), chosen.get("to")
    currency = (chosen.get("currency") or "").upper()
    unit = (chosen.get("unit") or "").casefold()
    type_ = (chosen.get("type") or "").casefold()

    unit_label = "/miesiąc" if unit == "month" else (f"/{unit}" if unit else "")
    type_label = f" ({type_.upper()})" if type_ else ""

    def _fmt(value):
        return f"{value:g}" if isinstance(value, float) else str(value)

    return f"{_fmt(low)}-{_fmt(high)} {currency}{unit_label}{type_label}".strip()


def parse(payload: dict | list) -> list[RawJob]:
    entries = (payload.get("data") or []) if isinstance(payload, dict) else payload
    jobs = []
    for entry in entries:
        guid = entry.get("guid")
        slug = entry.get("slug")
        if not guid or not slug:
            continue
        jobs.append(
            RawJob(
                source="justjoinit",
                external_id=guid,
                title=entry.get("title", ""),
                company=entry.get("companyName", ""),
                city=entry.get("city"),
                remote=(entry.get("workplaceType") or "").casefold() == "remote",
                url=OFFER_URL.format(slug=slug),
                salary=_salary(entry),
                posted_at=_parse_datetime(entry.get("publishedAt")),
            )
        )
    return jobs


class JustJoinIt:
    name = "justjoinit"

    def fetch(self, client: httpx.Client) -> list[RawJob]:
        response = client.get(API_URL, params={"itemsCount": 100})
        response.raise_for_status()
        return parse(response.json())
