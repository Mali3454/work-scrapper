import re
import unicodedata
from datetime import datetime

from scrapper.models import Job, RawJob

SOURCE_PRIORITY = {"nofluffjobs": 50, "justjoinit": 40}
COMPANY_PRIORITY = 100

# Transliteracja znaków, które NFKD nie rozkłada kanonicznie (np. Ł, ł).
TRANSLITERATION = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D"})

# Sufiksy form prawnych — 'Acme' i 'Acme Sp. z o.o.' to ta sama firma.
# Rozszerzono o warianty rozspacjowane powstające po _slug (np. 's a' z 'S.A.').
LEGAL_SUFFIXES = ("sp z o o", "sp z oo", "sa", "s a", "sp j", "sp k", "z o o")


def priority_of(source: str) -> int:
    if source.startswith("company:"):
        return COMPANY_PRIORITY
    return SOURCE_PRIORITY.get(source, 0)


def _slug(value: str) -> str:
    # Transliteruj znaki bez kanonicznego rozkładu NFKD, zanim normalizujesz.
    transliterated = value.translate(TRANSLITERATION)
    normalized = unicodedata.normalize("NFKD", transliterated)
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
        # Ta sama oferta pasująca do dwóch profili trafia tu dwa razy z tym
        # samym URL-em. Bez tego filtra dostawałaby w mailu link "także tutaj"
        # prowadzący pod ten sam adres co link główny.
        if priority_of(candidate.source) > priority_of(existing.source):
            candidate.alt_urls = _without_duplicates(
                [*existing.alt_urls, existing.url], candidate.url
            )
            best[key] = candidate
        elif candidate.url != existing.url and candidate.url not in existing.alt_urls:
            existing.alt_urls.append(candidate.url)
    return list(best.values())


def _without_duplicates(urls: list[str], main_url: str) -> list[str]:
    result = []
    for url in urls:
        if url != main_url and url not in result:
            result.append(url)
    return result
