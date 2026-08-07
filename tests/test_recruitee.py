import json
from pathlib import Path

from scrapper.sources.ats.recruitee import parse_recruitee

FIXTURE = Path(__file__).parent / "fixtures" / "recruitee.json"


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_returns_jobs():
    assert len(parse_recruitee(_payload(), company="Acme", slug="acme")) >= 1


def test_source_is_prefixed_with_company():
    jobs = parse_recruitee(_payload(), company="Acme", slug="acme")

    assert all(job.source == "company:acme" for job in jobs)


def test_company_name_comes_from_registry_not_payload():
    jobs = parse_recruitee(_payload(), company="Acme", slug="acme")

    assert all(job.company == "Acme" for job in jobs)


def test_parse_handles_empty_payload():
    assert parse_recruitee({"offers": []}, company="Acme", slug="acme") == []


def test_remote_field_read_directly_from_payload():
    jobs = {job.title: job for job in parse_recruitee(_payload(), company="Acme", slug="acme")}

    assert jobs["Project Manager"].remote is False
    assert jobs["AI Solutions Engineer"].remote is True


def test_posted_at_parses_non_iso_recruitee_format():
    jobs = parse_recruitee(_payload(), company="Acme", slug="acme")

    assert all(job.posted_at is not None for job in jobs)
    assert all(job.posted_at.tzinfo is not None for job in jobs)


def test_offer_without_url_is_skipped():
    payload = {"offers": [{"id": 1, "title": "No URL"}]}

    assert parse_recruitee(payload, company="Acme", slug="acme") == []
