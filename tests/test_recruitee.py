import json
from pathlib import Path

import httpx
import pytest

from scrapper.sources.ats.recruitee import fetch_recruitee, parse_recruitee
from scrapper.sources.companies import CompanyEntry

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


def test_external_id_falls_back_to_url_without_id():
    payload = {"offers": [{"title": "Bez id", "careers_url": "https://x.example/o/a"}]}

    jobs = parse_recruitee(payload, company="Acme", slug="acme")

    assert jobs[0].external_id == "https://x.example/o/a"


def test_remote_offer_drops_headquarters_city():
    # `city` w Recruitee to siedziba firmy, nie miejsce pracy — przy ofercie
    # zdalnej zostawienie go rozjechałoby klucz deduplikacji względem portali.
    jobs = {job.title: job for job in parse_recruitee(_payload(), company="Acme", slug="acme")}

    assert jobs["AI Solutions Engineer"].city is None
    assert jobs["Project Manager"].city == "Poznań"


def _offer_with_salary(salary):
    return {"offers": [{"id": 1, "title": "Dev", "careers_url": "https://x/1", "salary": salary}]}


def test_salary_range_is_formatted():
    jobs = parse_recruitee(
        _offer_with_salary({"min": 15000, "max": 20000, "currency": "PLN", "period": "month"}),
        company="Acme", slug="acme")

    assert jobs[0].salary == "15000-20000 PLN/month"


def test_salary_with_only_lower_bound_is_kept():
    jobs = parse_recruitee(
        _offer_with_salary({"min": 15000, "max": None, "currency": "PLN", "period": "month"}),
        company="Acme", slug="acme")

    assert jobs[0].salary == "od 15000 PLN/month"


def test_salary_with_only_upper_bound_is_kept():
    jobs = parse_recruitee(
        _offer_with_salary({"min": None, "max": 20000, "currency": "PLN"}),
        company="Acme", slug="acme")

    assert jobs[0].salary == "do 20000 PLN"


def test_zero_lower_bound_is_not_treated_as_missing():
    jobs = parse_recruitee(
        _offer_with_salary({"min": 0, "max": 20000, "currency": "PLN"}),
        company="Acme", slug="acme")

    assert jobs[0].salary == "0-20000 PLN"


def test_empty_salary_object_gives_none():
    jobs = parse_recruitee(
        _offer_with_salary({"min": None, "max": None, "period": None, "currency": None}),
        company="Acme", slug="acme")

    assert jobs[0].salary is None


def test_unparseable_published_at_gives_none_instead_of_raising():
    payload = {"offers": [{"id": 1, "title": "Dev", "careers_url": "https://x/1",
                           "published_at": "wczoraj"}]}

    assert parse_recruitee(payload, company="Acme", slug="acme")[0].posted_at is None


def test_fetch_hits_company_endpoint_and_maps_registry_fields():
    """Chroni kolejność argumentów `company=`/`slug=` w fetch_recruitee.

    Ich zamiana dałaby `company="espeo"` i `source="company:Espeo Software"` —
    parser i tak by przeszedł, a deduplikacja rozjechałaby się dopiero na żywo.
    """
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, json={"offers": [
            {"id": 7, "title": "React Dev", "careers_url": "https://espeo.recruitee.com/o/x",
             "city": "Poznań", "remote": False}]})

    entry = CompanyEntry(name="Espeo Software", ats="recruitee", slug="espeo")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs = fetch_recruitee(entry, client)

    assert requested == ["https://espeo.recruitee.com/api/offers/"]
    assert jobs[0].company == "Espeo Software"
    assert jobs[0].source == "company:espeo"


def test_fetch_raises_on_http_error():
    def handler(request):
        return httpx.Response(503)

    entry = CompanyEntry(name="Espeo Software", ats="recruitee", slug="espeo")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            fetch_recruitee(entry, client)


def test_fetch_can_use_recruitee_custom_domain_api():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, json={"offers": []})

    entry = CompanyEntry(
        name="Strix",
        ats="recruitee",
        slug="strix",
        api_url="https://career.strix.example/api/offers/",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetch_recruitee(entry, client)

    assert requested == ["https://career.strix.example/api/offers/"]
