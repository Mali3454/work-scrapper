import re
import unicodedata
from datetime import datetime

from scrapper.models import Job, RawJob

SOURCE_PRIORITY = {"nofluffjobs": 50, "justjoinit": 40}
COMPANY_PRIORITY = 100

# Sufiksy form prawnych — 'Acme' i 'Acme Sp. z o.o.' to ta sama firma.
LEGAL_SUFFIXES = ("sp z o o", "sp z oo", "sa", "sp j", "sp k", "z o o")


def priority_of(source: str) -> int:
    if source.startswith("company:"):
        return COMPANY_PRIORITY
    return SOURCE_PRIORITY.get(source, 0)


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-z0-9]+", " ", ascii_only.casefold()).strip()
    return re.sub(r"\s+", "-", cleaned)


def _company_slug(company: str) -> str:
    slug = _slug(company)
    spaced = slug.replace("-", " ")
    for suffix in LEGAL_SUFFIXES:
        if spaced.endswith(" " + suffix):
            spaced = spaced[: -len(suffix) - 1]
    return _slug(spaced)


def dedup_key(job: RawJob) -> str:
    city = _slug(job.city or "") or ("remote" if job.remote else "")
    return f"{_company_slug(job.company)}|{_slug(job.title)}|{city}"


def deduplicate(jobs: list[RawJob], now: datetime) -> list[Job]:
    best: dict[str, Job] = {}
    for raw in jobs:
        key = dedup_key(raw)
        candidate = Job(**raw.model_dump(), key=key, first_seen=now)
        existing = best.get(key)
        if existing is None:
            best[key] = candidate
            continue
        if priority_of(candidate.source) > priority_of(existing.source):
            candidate.alt_urls = [*existing.alt_urls, existing.url]
            best[key] = candidate
        else:
            existing.alt_urls.append(candidate.url)
    return list(best.values())
