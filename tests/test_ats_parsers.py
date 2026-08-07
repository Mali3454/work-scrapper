import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from scrapper.matcher import matches
from scrapper.models import Profile
from scrapper.sources.ats.greenhouse import fetch_greenhouse, parse_greenhouse
from scrapper.sources.ats.lever import fetch_lever, parse_lever
from scrapper.sources.ats.workable import fetch_workable, parse_workable
from scrapper.sources.companies import CompanyEntry

FIXTURES = Path(__file__).parent / "fixtures"


def _payload(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------

GH_PAYLOAD = "greenhouse.json"


def test_greenhouse_parse_returns_jobs():
    jobs = parse_greenhouse(_payload(GH_PAYLOAD), company="home.pl", slug="homepl")

    assert len(jobs) == 2


def test_greenhouse_stettin_is_normalized_to_szczecin():
    jobs = parse_greenhouse(_payload(GH_PAYLOAD), company="home.pl", slug="homepl")

    assert all(job.city == "Szczecin" for job in jobs)


def test_greenhouse_stettin_offer_matches_szczecin_profile_end_to_end():
    """Test regresyjny na sedno Task 15 (patrz task-15-brief.md).

    Bez normalizacji "Stettin" -> "Szczecin" w parserze, `matcher._location_ok`
    (`"szczecin" in "ul. zbożowa 4, 70-653 stettin"`) zwraca False i jedyna
    szczecińska firma z żywym ATS-em w projekcie zostaje odfiltrowana.
    """
    jobs = parse_greenhouse(_payload(GH_PAYLOAD), company="home.pl", slug="homepl")
    profile = Profile(name="frontend-szczecin", keywords=[jobs[0].title.split()[0]],
                       locations=["szczecin"], include_remote=True, max_age_days=3650)
    now = datetime(2026, 8, 7, tzinfo=timezone.utc)

    assert matches(jobs[0], profile, now)


def test_greenhouse_uses_first_published_not_updated_at():
    """`updated_at` jest identyczne dla WSZYSTKICH ofert home.pl (zbiorcze
    odświeżenie boarda), więc branie go dałoby fałszywie świeże daty. Fixture
    ma różne `first_published` dla obu ofert mimo identycznego `updated_at`.
    """
    jobs = {job.title: job for job in parse_greenhouse(_payload(GH_PAYLOAD), company="home.pl",
                                                        slug="homepl")}
    payload = _payload(GH_PAYLOAD)
    updated_at_values = {job["updated_at"] for job in payload["jobs"]}
    assert len(updated_at_values) == 1  # potwierdza założenie fixture'a

    posted_dates = {job.posted_at.date().isoformat() for job in jobs.values()}
    assert posted_dates == {"2026-04-07", "2026-06-15"}


def test_greenhouse_city_extraction_strips_street_and_postal_code():
    from scrapper.sources.ats.greenhouse import _extract_city

    assert _extract_city("ul. Zbożowa 4, 70-653 Stettin") == "Szczecin"


def test_greenhouse_city_extraction_handles_missing_location():
    from scrapper.sources.ats.greenhouse import _extract_city

    assert _extract_city(None) is None
    assert _extract_city("") is None


def test_greenhouse_offer_without_url_is_skipped():
    payload = {"jobs": [{"id": 1, "title": "Bez URL", "location": {"name": "Warszawa"}}]}

    assert parse_greenhouse(payload, company="Acme", slug="acme") == []


def test_greenhouse_unparseable_dates_give_none():
    payload = {"jobs": [{"id": 1, "title": "Dev", "absolute_url": "https://x/1",
                          "location": {"name": "Warszawa"},
                          "first_published": "wczoraj", "updated_at": "wczoraj"}]}

    assert parse_greenhouse(payload, company="Acme", slug="acme")[0].posted_at is None


def test_greenhouse_fetch_hits_boards_api():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, json={"jobs": []})

    entry = CompanyEntry(name="home.pl", ats="greenhouse", slug="homepl")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetch_greenhouse(entry, client)

    assert requested == ["https://boards-api.greenhouse.io/v1/boards/homepl/jobs"]


def test_greenhouse_fetch_raises_on_http_error():
    def handler(request):
        return httpx.Response(503)

    entry = CompanyEntry(name="home.pl", ats="greenhouse", slug="homepl")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            fetch_greenhouse(entry, client)


# ---------------------------------------------------------------------------
# Lever
# ---------------------------------------------------------------------------

LEVER_PAYLOAD = "lever.json"


def test_lever_parse_returns_jobs():
    assert len(parse_lever(_payload(LEVER_PAYLOAD), company="Pipedrive", slug="pipedrive")) == 3


def test_lever_payload_is_a_list_not_object():
    """Zweryfikowane na żywo: payload to LISTA, nie obiekt z kluczem
    (w przeciwieństwie do Recruitee/Greenhouse). Test dokumentuje to wprost —
    `_payload` zwraca `list`, nie `dict`."""
    assert isinstance(_payload(LEVER_PAYLOAD), list)


def test_lever_city_is_last_segment_of_country_comma_city():
    jobs = parse_lever(_payload(LEVER_PAYLOAD), company="Pipedrive", slug="pipedrive")
    cities = {job.city for job in jobs}

    # "Portugal, Lisbon" -> "Lisbon", "UK, London" -> "London" — miasto na
    # KOŃCU, nie na początku (pułapka opisana w task-15-brief.md).
    assert cities == {"Lisbon", "London"}


def test_lever_uses_workplace_type_field():
    payload = [{"id": "1", "text": "Dev", "hostedUrl": "https://x/1",
                "workplaceType": "remote", "categories": {"location": "Poland, Warsaw"},
                "createdAt": 1700000000000}]

    jobs = parse_lever(payload, company="Acme", slug="acme")

    assert jobs[0].remote is True


def test_lever_on_site_workplace_type_is_not_remote():
    payload = [{"id": "1", "text": "Dev", "hostedUrl": "https://x/1",
                "workplaceType": "on-site", "categories": {"location": "Poland, Warsaw"},
                "createdAt": 1700000000000}]

    jobs = parse_lever(payload, company="Acme", slug="acme")

    assert jobs[0].remote is False


def test_lever_created_at_is_epoch_milliseconds():
    jobs = parse_lever(_payload(LEVER_PAYLOAD), company="Pipedrive", slug="pipedrive")

    assert all(job.posted_at is not None and job.posted_at.tzinfo is not None for job in jobs)


def test_lever_offer_without_url_is_skipped():
    payload = [{"id": "1", "text": "Bez URL"}]

    assert parse_lever(payload, company="Acme", slug="acme") == []


def test_lever_fetch_hits_postings_api():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, json=[])

    entry = CompanyEntry(name="Pipedrive", ats="lever", slug="pipedrive")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetch_lever(entry, client)

    assert requested == ["https://api.lever.co/v0/postings/pipedrive?mode=json"]


def test_lever_fetch_raises_on_http_error():
    def handler(request):
        return httpx.Response(503)

    entry = CompanyEntry(name="Pipedrive", ats="lever", slug="pipedrive")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            fetch_lever(entry, client)


# ---------------------------------------------------------------------------
# Workable
# ---------------------------------------------------------------------------

WORKABLE_PAYLOAD = "workable.json"


def test_workable_parse_returns_jobs():
    assert len(parse_workable(_payload(WORKABLE_PAYLOAD), company="Netguru", slug="netguru")) == 3


def test_workable_empty_city_string_becomes_none():
    """Zweryfikowane na żywo: `city` bywa `""`, nie `null`. Bez `or None` w
    parserze klucz deduplikacji dostałby pusty segment zamiast braku miasta.
    """
    jobs = {job.title: job for job in parse_workable(_payload(WORKABLE_PAYLOAD), company="Netguru",
                                                       slug="netguru")}

    assert jobs["(Senior) Data Engineer - Freelance"].city is None
    assert jobs["Business Development Manager"].city is None


def test_workable_non_empty_city_is_kept():
    jobs = {job.title: job for job in parse_workable(_payload(WORKABLE_PAYLOAD), company="Netguru",
                                                       slug="netguru")}

    assert jobs["(Senior) Fullstack Engineer (Node.js + Python + Typescript) - Freelance"].city == "Poznań"


def test_workable_external_id_is_shortcode_not_id():
    jobs = parse_workable(_payload(WORKABLE_PAYLOAD), company="Netguru", slug="netguru")

    assert jobs[0].external_id == "C99A238797"


def test_workable_telecommuting_maps_to_remote():
    jobs = parse_workable(_payload(WORKABLE_PAYLOAD), company="Netguru", slug="netguru")

    assert all(job.remote is True for job in jobs)


def test_workable_published_on_is_date_only():
    jobs = parse_workable(_payload(WORKABLE_PAYLOAD), company="Netguru", slug="netguru")

    assert all(job.posted_at is not None for job in jobs)


def test_workable_offer_without_url_is_skipped():
    payload = {"jobs": [{"shortcode": "X1", "title": "Bez URL"}]}

    assert parse_workable(payload, company="Acme", slug="acme") == []


def test_workable_fetch_hits_widget_api():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, json={"jobs": []})

    entry = CompanyEntry(name="Netguru", ats="workable", slug="netguru")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetch_workable(entry, client)

    assert requested == ["https://apply.workable.com/api/v1/widget/accounts/netguru?details=true"]


def test_workable_fetch_raises_on_http_error():
    def handler(request):
        return httpx.Response(503)

    entry = CompanyEntry(name="Netguru", ats="workable", slug="netguru")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            fetch_workable(entry, client)
