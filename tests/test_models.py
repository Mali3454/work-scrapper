from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from scrapper.models import Job, Profile, RawJob


def _raw(**overrides) -> RawJob:
    data = {
        "source": "justjoinit",
        "external_id": "abc123",
        "title": "Frontend Developer",
        "company": "Acme",
        "city": "Szczecin",
        "remote": False,
        "url": "https://example.com/oferta",
        "salary": "12 000 - 16 000 PLN",
        "posted_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return RawJob(**data)


def test_rawjob_holds_all_fields():
    job = _raw()

    assert job.company == "Acme"
    assert job.remote is False


def test_rawjob_allows_missing_optional_fields():
    job = _raw(city=None, salary=None, posted_at=None)

    assert job.city is None
    assert job.salary is None


def test_rawjob_rejects_missing_url():
    with pytest.raises(ValidationError):
        RawJob(source="justjoinit", external_id="x", title="t", company="c", remote=False)


def test_job_defaults_alt_urls_to_empty_list():
    job = Job(**_raw().model_dump(), key="acme|frontend-developer|szczecin",
              first_seen=datetime(2026, 8, 6, tzinfo=timezone.utc))

    assert job.alt_urls == []


def test_profile_defaults():
    profile = Profile(name="frontend", keywords=["react"])

    assert profile.exclude == []
    assert profile.include_remote is True
    assert profile.max_age_days == 14
