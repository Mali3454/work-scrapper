import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from scrapper.matcher import matches
from scrapper.models import Profile
from scrapper.sources.ats.smartrecruiters import fetch_smartrecruiters, parse_smartrecruiters
from scrapper.sources.companies import DEFAULT_FETCHERS, CompanyEntry

FIXTURE = Path(__file__).parent / "fixtures" / "smartrecruiters.json"
NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _entry():
    return CompanyEntry(name="TietoEVRY", ats="smartrecruiters", slug="Tieto2")


def test_parse_returns_jobs_with_company_prefix():
    jobs = parse_smartrecruiters(_payload(), company="TietoEVRY", slug="Tieto2")

    assert len(jobs) == 3
    assert all(job.source == "company:Tieto2" for job in jobs)
    assert all(job.company == "TietoEVRY" for job in jobs)


def test_szczecin_offer_matches_profile_end_to_end():
    """Sedno tego parsera: TietoEVRY ma 14 realnych ofert IT w Szczecinie,
    które do tej pory nie docierały nigdzie (wpis miał `parser: skip`)."""
    jobs = parse_smartrecruiters(_payload(), company="TietoEVRY", slug="Tieto2")
    szczecin = [j for j in jobs if j.city == "Szczecin"]
    assert szczecin, "fixture musi zawierać ofertę ze Szczecina"

    profile = Profile(name="szczecin", keywords=["engineer", "analyst"],
                      locations=["szczecin"], include_remote=False, max_age_days=3650)

    assert any(matches(job, profile, NOW) for job in szczecin)


def test_url_points_at_canonical_jobs_host():
    """`jobs.smartrecruiters.com` zweryfikowany negatywnie (zmyślone id → 400).
    Wariant `careers.` odpada: zwraca 200 nawet dla zmyślonego id."""
    job = parse_smartrecruiters(_payload(), company="TietoEVRY", slug="Tieto2")[0]

    assert job.url.startswith("https://jobs.smartrecruiters.com/Tieto2/")
    assert job.url.endswith(job.external_id)


def test_remote_is_read_from_location_field():
    jobs = {j.title: j for j in parse_smartrecruiters(_payload(), company="T", slug="Tieto2")}
    remote = [j for j in jobs.values() if j.remote]
    stationary = [j for j in jobs.values() if not j.remote]

    assert remote and stationary  # obie gałęzie pokryte realnymi danymi


def test_offer_without_id_is_skipped():
    payload = {"content": [{"name": "Bez id", "location": {"city": "Szczecin"}}]}

    assert parse_smartrecruiters(payload, company="T", slug="Tieto2") == []


def test_fetch_paginates_until_short_page():
    """Bez paginacji widać tylko pierwsze 100 z 372 ofert — a w tej setce nie
    ma ANI JEDNEJ oferty ze Szczecina (API nie sortuje po lokalizacji)."""
    seen_offsets = []

    def handler(request):
        offset = int(request.url.params.get("offset", 0))
        seen_offsets.append(offset)
        count = 100 if offset < 200 else 30
        content = [{"id": f"{offset + i}", "name": "Dev", "location": {"city": "Szczecin"}}
                   for i in range(count)]
        return httpx.Response(200, json={"content": content})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs = fetch_smartrecruiters(_entry(), client)

    assert seen_offsets == [0, 100, 200]
    assert len(jobs) == 230


def test_fetch_respects_max_offers_budget():
    def handler(request):
        content = [{"id": f"x{i}", "name": "Dev", "location": {}} for i in range(100)]
        return httpx.Response(200, json={"content": content})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs = fetch_smartrecruiters(_entry(), client, max_offers=150)

    assert len(jobs) == 150


def test_fetch_raises_on_http_error():
    def handler(request):
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            fetch_smartrecruiters(_entry(), client)


def test_registered_in_default_fetchers():
    assert DEFAULT_FETCHERS["smartrecruiters"] is fetch_smartrecruiters


def test_city_goes_through_shared_normalization():
    """Na dzisiejszych danych TietoEVRY normalizacja jest no-op — żadne z 63
    miast się nie zmienia. Jest tu dla SPÓJNOŚCI z pozostałymi parserami ATS:
    gdyby firma wpisała "Remote" albo egzonim jako miasto, klucz deduplikacji
    rozjechałby się względem Greenhouse/Lever/Workable, które to normalizują.
    Stąd dane syntetyczne — realne tej ścieżki nie pokrywają.
    """
    payload = {"content": [
        {"id": "1", "name": "Dev", "location": {"city": "Stettin"}},
        {"id": "2", "name": "Dev", "location": {"city": "Remote", "remote": True}},
    ]}

    jobs = parse_smartrecruiters(payload, company="T", slug="Tieto2")

    assert jobs[0].city == "Szczecin"
    assert jobs[1].city is None and jobs[1].remote is True
