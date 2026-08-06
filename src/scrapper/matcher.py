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
        return profile.include_remote
    if not profile.locations:
        return True
    city = (job.city or "").casefold()
    return any(loc.casefold() in city for loc in profile.locations)


def _age_ok(job: RawJob, profile: Profile, now: datetime) -> bool:
    if job.posted_at is None:
        return True
    return job.posted_at >= now - timedelta(days=profile.max_age_days)


def matches(job: RawJob, profile: Profile, now: datetime) -> bool:
    if any(_contains_word(job.title, word) for word in profile.exclude):
        return False
    if not any(_contains_word(job.title, word) for word in profile.keywords):
        return False
    if not _location_ok(job, profile):
        return False
    return _age_ok(job, profile, now)


def filter_jobs(jobs: list[RawJob], profile: Profile, now: datetime) -> list[RawJob]:
    return [job for job in jobs if matches(job, profile, now)]
