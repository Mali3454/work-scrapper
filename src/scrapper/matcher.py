import re
from datetime import datetime, timedelta

from scrapper.models import Profile, RawJob


def _contains_word(haystack: str, needle: str) -> bool:
    """Dopasowanie całego słowa, odporne na wielkość liter.

    'lead' nie trafia w 'Leadership', ale 'next.js' trafia w 'Next.js Developer'.
    """
    pattern = r"(?<!\w)" + re.escape(needle) + r"(?!\w)"
    return re.search(pattern, haystack, flags=re.IGNORECASE) is not None


def _location_ok(job: RawJob, profile: Profile) -> bool:
    if job.remote:
        country = (job.country or "").strip().casefold()
        if country and country not in {"pl", "poland", "polska"}:
            return False
        return profile.include_remote
    if not profile.locations:
        return True
    city = (job.city or "").casefold()
    return any(loc.casefold() in city for loc in profile.locations)


def _age_ok(job: RawJob, profile: Profile, now: datetime) -> bool:
    # Jesli oferta nadal widnieje na firmowym boardzie, jest aktywna niezaleznie
    # od pierwotnej daty publikacji. Limit wieku chroni przed starymi kopiami na
    # portalach, nie przed aktualnymi wakatami na stronie pracodawcy.
    if job.source.startswith("company:"):
        return True
    if job.posted_at is None:
        return True
    return job.posted_at >= now - timedelta(days=profile.max_age_days)


def _keyword_haystack(job: RawJob, profile: Profile) -> str:
    """Tytuł + wymagane umiejętności — tam szukamy słów kluczowych.

    Sama nazwa narzędzia bywa wyłącznie w `skills`: oferta „Asystent/ka
    Projektanta Konstrukcji" (RocketJobs) ma „Tekla” tylko tam. Szukanie po
    samym tytule gubiłoby takie oferty.
    """
    parts = [job.title, *job.skills]
    if profile.search_description:
        parts.append(job.search_text)
    return " ".join(parts)


def matches(job: RawJob, profile: Profile, now: datetime) -> bool:
    # `exclude` celowo patrzy TYLKO na tytuł. Gdyby obejmowało umiejętności,
    # `exclude: [senior]` odrzucałoby ofertę juniorską wymagającą współpracy
    # z seniorem, a wykluczenia mają dotyczyć poziomu stanowiska, nie techniki.
    if any(_contains_word(job.title, word) for word in profile.exclude):
        return False
    haystack = _keyword_haystack(job, profile)
    if not any(_contains_word(haystack, word) for word in profile.keywords):
        return False
    if not _location_ok(job, profile):
        return False
    return _age_ok(job, profile, now)


def filter_jobs(jobs: list[RawJob], profile: Profile, now: datetime) -> list[RawJob]:
    return [job for job in jobs if matches(job, profile, now)]
