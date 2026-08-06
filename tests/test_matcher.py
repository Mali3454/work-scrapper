from datetime import datetime, timedelta, timezone

from scrapper.matcher import filter_jobs, matches
from scrapper.models import Profile, RawJob

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)

PROFILE = Profile(
    name="frontend-szczecin",
    keywords=["frontend", "react"],
    exclude=["senior", "lead"],
    locations=["szczecin"],
    include_remote=True,
    max_age_days=14,
)


def _job(**overrides) -> RawJob:
    data = {
        "source": "justjoinit",
        "external_id": "1",
        "title": "Frontend Developer",
        "company": "Acme",
        "city": "Szczecin",
        "remote": False,
        "url": "https://example.com/1",
        "posted_at": NOW - timedelta(days=1),
    }
    data.update(overrides)
    return RawJob(**data)


def test_accepts_matching_job():
    assert matches(_job(), PROFILE, NOW) is True


def test_keyword_match_is_case_insensitive():
    assert matches(_job(title="REACT Engineer"), PROFILE, NOW) is True


def test_rejects_job_without_any_keyword():
    assert matches(_job(title="Backend Developer"), PROFILE, NOW) is False


def test_rejects_excluded_title():
    assert matches(_job(title="Senior Frontend Developer"), PROFILE, NOW) is False


def test_exclude_matches_whole_words_only():
    assert matches(_job(title="Frontend Developer - Leadership Tools"), PROFILE, NOW) is True


def test_rejects_other_city_when_not_remote():
    assert matches(_job(city="Kraków"), PROFILE, NOW) is False


def test_accepts_remote_job_from_other_city():
    assert matches(_job(city="Kraków", remote=True), PROFILE, NOW) is True


def test_rejects_remote_when_profile_excludes_remote():
    profile = PROFILE.model_copy(update={"include_remote": False})

    assert matches(_job(city="Kraków", remote=True), profile, NOW) is False


def test_rejects_job_older_than_max_age():
    assert matches(_job(posted_at=NOW - timedelta(days=30)), PROFILE, NOW) is False


def test_accepts_job_without_posted_at():
    assert matches(_job(posted_at=None), PROFILE, NOW) is True


def test_filter_jobs_keeps_only_matching():
    jobs = [_job(external_id="1"), _job(external_id="2", title="Backend Developer")]

    result = filter_jobs(jobs, PROFILE, NOW)

    assert [j.external_id for j in result] == ["1"]


def test_matches_with_naive_posted_at_old():
    # Naiwny posted_at (bez timezone) sprzed 30 dni powinien być odrzucony
    naive_dt = datetime(2026, 7, 7, 12, 0, 0)  # 30 dni przed NOW
    assert matches(_job(posted_at=naive_dt), PROFILE, NOW) is False


def test_matches_with_naive_posted_at_recent():
    # Naiwny posted_at sprzed 1 dnia powinien być przyjęty
    naive_dt = datetime(2026, 8, 5, 12, 0, 0)  # 1 dzień przed NOW
    assert matches(_job(posted_at=naive_dt), PROFILE, NOW) is True
