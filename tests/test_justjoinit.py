import json
from datetime import datetime, timezone
from pathlib import Path

from scrapper.sources.justjoinit import JustJoinIt, parse

FIXTURE = Path(__file__).parent / "fixtures" / "justjoinit.json"


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _by_title(jobs, title):
    for job in jobs:
        if job.title == title:
            return job
    raise AssertionError(f"brak oferty o tytule {title!r}")


def test_parse_returns_jobs():
    jobs = parse(_payload())

    assert len(jobs) == 3


def test_parsed_jobs_have_required_fields():
    for job in parse(_payload()):
        assert job.source == "justjoinit"
        assert job.title
        assert job.company
        assert job.url.startswith("https://")
        assert job.external_id


def test_parse_handles_empty_payload():
    assert parse({"data": []}) == []


def test_source_name():
    assert JustJoinIt().name == "justjoinit"


def test_remote_offer_is_remote_true():
    job = _by_title(parse(_payload()), "Senior .Net Developer")

    assert job.remote is True


def test_office_offer_is_remote_false():
    job = _by_title(parse(_payload()), "Grid Converter Control Engineer")

    assert job.remote is False


def test_hybrid_workplace_type_is_remote_false():
    payload = {
        "data": [
            {
                "guid": "hybrid-guid",
                "slug": "hybrid-slug",
                "title": "Hybrid Dev",
                "companyName": "HybridCo",
                "city": "Warszawa",
                "workplaceType": "hybrid",
                "publishedAt": "2026-08-06T10:00:00.000Z",
                "employmentTypes": [],
            }
        ]
    }
    job = parse(payload)[0]

    assert job.remote is False


def test_offer_with_salary_range_has_salary():
    job = _by_title(parse(_payload()), "Senior .Net Developer")

    assert job.salary is not None
    assert "26000" in job.salary
    assert "31000" in job.salary
    assert "PLN" in job.salary


def test_offer_without_salary_range_has_none_salary():
    job = _by_title(parse(_payload()), "Grid Converter Control Engineer")

    assert job.salary is None


def test_offer_with_only_permanent_and_no_range_still_none():
    job = _by_title(
        parse(_payload()),
        "Starszy Tester/Starsza Testerka oprogramowania (Playwright/Cypress)",
    )

    assert job.salary is None


def test_posted_at_is_utc_datetime():
    job = _by_title(parse(_payload()), "Senior .Net Developer")

    assert isinstance(job.posted_at, datetime)
    assert job.posted_at.tzinfo is not None
    assert job.posted_at.utcoffset() == timezone.utc.utcoffset(None)


def test_url_has_job_offer_path_with_slug():
    job = _by_title(parse(_payload()), "Senior .Net Developer")

    assert job.url == (
        "https://justjoin.it/job-offer/jit-team-senior-net-developer-gdansk-net-1db50058"
    )


def test_external_id_is_guid_not_slug():
    job = _by_title(parse(_payload()), "Senior .Net Developer")

    assert job.external_id == "d9bae961-b260-4230-a9ec-0763bfec307a"
    assert job.external_id != job.url.rsplit("/", 1)[-1]


def test_salary_prefers_b2b_over_permanent_when_both_have_ranges():
    payload = {
        "data": [
            {
                "guid": "guid-1",
                "slug": "slug-1",
                "title": "Dual Salary Offer",
                "companyName": "DualCo",
                "city": "Kraków",
                "workplaceType": "remote",
                "publishedAt": "2026-08-06T10:00:00.000Z",
                "employmentTypes": [
                    {
                        "from": 10000,
                        "to": 15000,
                        "currency": "PLN",
                        "currencySource": "original",
                        "type": "permanent",
                        "unit": "month",
                    },
                    {
                        "from": 20000,
                        "to": 25000,
                        "currency": "PLN",
                        "currencySource": "original",
                        "type": "b2b",
                        "unit": "month",
                    },
                ],
            }
        ]
    }
    job = parse(payload)[0]

    assert job.salary is not None
    assert "20000" in job.salary
    assert "25000" in job.salary
    assert "10000" not in job.salary


def test_salary_ignores_conversion_currency_source():
    payload = {
        "data": [
            {
                "guid": "guid-2",
                "slug": "slug-2",
                "title": "Conversion Only Offer",
                "companyName": "ConvCo",
                "city": "Poznań",
                "workplaceType": "office",
                "publishedAt": "2026-08-06T10:00:00.000Z",
                "employmentTypes": [
                    {
                        "from": 5000,
                        "to": 8000,
                        "currency": "USD",
                        "currencySource": "conversion",
                        "type": "b2b",
                        "unit": "month",
                    },
                ],
            }
        ]
    }
    job = parse(payload)[0]

    assert job.salary is None


def test_salary_unit_and_type_comparison_is_case_insensitive():
    payload = {
        "data": [
            {
                "guid": "guid-3",
                "slug": "slug-3",
                "title": "Case Insensitive Offer",
                "companyName": "CaseCo",
                "city": "Wrocław",
                "workplaceType": "remote",
                "publishedAt": "2026-08-06T10:00:00.000Z",
                "employmentTypes": [
                    {
                        "from": 100,
                        "to": 200,
                        "currency": "PLN",
                        "currencySource": "original",
                        "type": "B2B",
                        "unit": "Month",
                    },
                ],
            }
        ]
    }
    job = parse(payload)[0]

    assert job.salary is not None
    assert "(B2B)" in job.salary
    assert "/miesiąc" in job.salary


def test_entries_missing_guid_or_slug_are_skipped_others_still_parsed():
    payload = {
        "data": [
            {
                "guid": None,
                "slug": "no-guid-offer",
                "title": "No Guid Offer",
                "companyName": "NoGuidCo",
                "city": "Łódź",
                "workplaceType": "office",
                "publishedAt": "2026-08-06T10:00:00.000Z",
                "employmentTypes": [],
            },
            {
                "guid": "guid-no-slug",
                "slug": None,
                "title": "No Slug Offer",
                "companyName": "NoSlugCo",
                "city": "Łódź",
                "workplaceType": "office",
                "publishedAt": "2026-08-06T10:00:00.000Z",
                "employmentTypes": [],
            },
            {
                "guid": "guid-valid",
                "slug": "valid-offer",
                "title": "Valid Offer",
                "companyName": "ValidCo",
                "city": "Łódź",
                "workplaceType": "office",
                "publishedAt": "2026-08-06T10:00:00.000Z",
                "employmentTypes": [],
            },
        ]
    }
    jobs = parse(payload)

    assert len(jobs) == 1
    assert jobs[0].external_id == "guid-valid"


def test_parse_handles_null_data():
    assert parse({"data": None}) == []
