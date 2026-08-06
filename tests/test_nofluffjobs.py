import json
from pathlib import Path

from scrapper.sources.nofluffjobs import NoFluffJobs, parse

FIXTURE = Path(__file__).parent / "fixtures" / "nofluffjobs.json"


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_returns_jobs():
    assert len(parse(_payload())) >= 1


def test_parsed_jobs_have_required_fields():
    for job in parse(_payload()):
        assert job.source == "nofluffjobs"
        assert job.title
        assert job.company
        assert job.url.startswith("https://")
        assert job.external_id


def test_parse_handles_empty_payload():
    assert parse({"postings": []}) == []


def test_source_name():
    assert NoFluffJobs().name == "nofluffjobs"


def test_parse_distinguishes_remote_and_onsite():
    jobs = {job.external_id: job for job in parse(_payload())}
    onsite = jobs["senior-power-platform-developer-with-copilot-studio-spyrosoft-Szczecin"]
    remote = jobs["leading-d365-technical-consultant-f-m-x-sii-polska-Szczecin"]
    assert onsite.remote is False
    assert remote.remote is True


def test_parse_extracts_city():
    jobs = parse(_payload())
    assert all(job.city == "Szczecin" for job in jobs)


def test_parse_builds_salary_string():
    jobs = {job.external_id: job for job in parse(_payload())}
    onsite = jobs["senior-power-platform-developer-with-copilot-studio-spyrosoft-Szczecin"]
    assert onsite.salary == "18480-25200 PLN/miesiąc (B2B)"


def test_parse_sets_posted_at_utc():
    jobs = parse(_payload())
    for job in jobs:
        assert job.posted_at is not None
        assert job.posted_at.tzinfo is not None


def test_parse_handles_missing_salary():
    # W próbce API (patrz docs/sources.md) NIE zaobserwowano ofert bez
    # ujawnionego wynagrodzenia — NoFluffJobs wymusza jawność widełek na
    # wszystkich zbadanych ofertach. Testujemy gałąź obsługi braku danych
    # syntetycznym payloadem, żeby nie polegać wyłącznie na fixture.
    payload = {
        "postings": [
            {
                "id": "example-job",
                "url": "example-job",
                "title": "Example",
                "name": "Example Sp. z o.o.",
                "location": {"places": [{"city": "Szczecin"}], "fullyRemote": False},
                "salary": None,
                "posted": 1785535222245,
            }
        ]
    }
    jobs = parse(payload)
    assert len(jobs) == 1
    assert jobs[0].salary is None


def test_parse_skips_entries_without_id_or_url():
    payload = {
        "postings": [
            {"title": "No id/url", "name": "Foo"},
            {"id": "has-id-no-url", "title": "X", "name": "Foo"},
            {"url": "has-url-no-id", "title": "X", "name": "Foo"},
        ]
    }
    assert parse(payload) == []
