import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

from scrapper.sources import justjoinit as jj
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


# --- Fetch/paginacja/multi-miasto: atrapy klienta, bez sieci -------------------


def _entry(guid: str, slug: str | None = None, city: str = "Warszawa") -> dict:
    slug = slug or guid
    return {
        "guid": guid,
        "slug": slug,
        "title": f"Title {guid}",
        "companyName": "Co",
        "city": city,
        "workplaceType": "office",
        "publishedAt": "2026-08-06T10:00:00.000Z",
        "employmentTypes": [],
    }


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=httpx.Request("GET", jj.API_URL),
                response=self,
            )

    def json(self):
        return self._payload


class _FakeClient:
    """Atrapa httpx.Client — kolejkuje odpowiedzi per miasto (klucz `_global_`
    gdy zapytanie bez `city`), zlicza wywołania i przekazane parametry."""

    def __init__(self, pages_by_city: dict[str, list[_FakeResponse]]):
        self._queues = {key: list(pages) for key, pages in pages_by_city.items()}
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, params=None):
        params = dict(params or {})
        self.calls.append((url, params))
        key = params.get("city") or "_global_"
        queue = self._queues.get(key)
        if not queue:
            return _FakeResponse({"data": [], "meta": {"next": {"cursor": None}}})
        return queue.pop(0)


def test_fetch_paginates_and_merges_pages(monkeypatch):
    monkeypatch.setattr(jj, "_PAGE_SIZE", 2)
    page1 = _FakeResponse({"data": [_entry("g1"), _entry("g2")], "meta": {"next": {"cursor": 2}}})
    page2 = _FakeResponse({"data": [_entry("g3")], "meta": {"next": {"cursor": None}}})
    client = _FakeClient({"_global_": [page1, page2]})

    jobs = JustJoinIt(max_offers=1000).fetch(client)

    assert {job.external_id for job in jobs} == {"g1", "g2", "g3"}
    assert len(client.calls) == 2


def test_max_offers_stops_pagination_despite_cursor_continuing(monkeypatch):
    monkeypatch.setattr(jj, "_PAGE_SIZE", 2)
    page1 = _FakeResponse({"data": [_entry("g1"), _entry("g2")], "meta": {"next": {"cursor": 2}}})
    page2 = _FakeResponse({"data": [_entry("g3"), _entry("g4")], "meta": {"next": {"cursor": 4}}})
    client = _FakeClient({"_global_": [page1, page2]})

    jobs = JustJoinIt(max_offers=3).fetch(client)

    assert len(jobs) == 3
    assert len(client.calls) == 2  # nie sięgnęliśmy po trzecią stronę mimo cursor=4


def test_duplicate_guid_across_pages_appears_once(monkeypatch):
    monkeypatch.setattr(jj, "_PAGE_SIZE", 2)
    page1 = _FakeResponse({"data": [_entry("dup"), _entry("g2")], "meta": {"next": {"cursor": 2}}})
    page2 = _FakeResponse({"data": [_entry("dup"), _entry("g3")], "meta": {"next": {"cursor": None}}})
    client = _FakeClient({"_global_": [page1, page2]})

    jobs = JustJoinIt(max_offers=1000).fetch(client)

    ids = [job.external_id for job in jobs]
    assert ids.count("dup") == 1
    assert len(jobs) == 3


def test_duplicate_guid_across_cities_appears_once():
    page_szczecin = _FakeResponse(
        {
            "data": [_entry("dup", city="Szczecin"), _entry("s2", city="Szczecin")],
            "meta": {"next": {"cursor": None}},
        }
    )
    page_gdansk = _FakeResponse(
        {
            "data": [_entry("dup", city="Gdańsk"), _entry("g2", city="Gdańsk")],
            "meta": {"next": {"cursor": None}},
        }
    )
    client = _FakeClient({"szczecin": [page_szczecin], "gdansk": [page_gdansk]})

    jobs = JustJoinIt(cities=["szczecin", "gdansk"]).fetch(client)

    ids = [job.external_id for job in jobs]
    assert ids.count("dup") == 1
    assert len(jobs) == 3


def test_cities_list_triggers_query_per_city():
    def _empty_page():
        return _FakeResponse({"data": [], "meta": {"next": {"cursor": None}}})

    client = _FakeClient({"szczecin": [_empty_page()], "gdansk": [_empty_page()]})

    JustJoinIt(cities=["szczecin", "gdansk"]).fetch(client)

    requested_cities = [params.get("city") for _, params in client.calls]
    assert requested_cities == ["szczecin", "gdansk"]


def test_cities_none_makes_single_query_without_city_param():
    client = _FakeClient({"_global_": [_FakeResponse({"data": [], "meta": {"next": {"cursor": None}}})]})

    JustJoinIt(cities=None).fetch(client)

    assert len(client.calls) == 1
    assert "city" not in client.calls[0][1]


def test_empty_response_ends_pagination_without_looping():
    client = _FakeClient({"_global_": [_FakeResponse({"data": [], "meta": {"next": {"cursor": None}}})]})

    jobs = JustJoinIt(max_offers=1000).fetch(client)

    assert jobs == []
    assert len(client.calls) == 1


def test_subsequent_page_http_error_ends_pagination_gracefully(monkeypatch):
    monkeypatch.setattr(jj, "_PAGE_SIZE", 2)
    page1 = _FakeResponse({"data": [_entry("g1"), _entry("g2")], "meta": {"next": {"cursor": 2}}})
    page2 = _FakeResponse({}, status_code=500)
    client = _FakeClient({"_global_": [page1, page2]})

    jobs = JustJoinIt(max_offers=1000).fetch(client)

    assert len(jobs) == 2


def test_first_page_http_error_propagates():
    import pytest

    client = _FakeClient({"_global_": [_FakeResponse({}, status_code=500)]})

    with pytest.raises(httpx.HTTPStatusError):
        JustJoinIt().fetch(client)


def test_http_503_on_second_page_returns_partial_results_and_logs_warning(monkeypatch, caplog):
    monkeypatch.setattr(jj, "_PAGE_SIZE", 2)
    page1 = _FakeResponse({"data": [_entry("g1"), _entry("g2")], "meta": {"next": {"cursor": 2}}})
    page2 = _FakeResponse({}, status_code=503)
    client = _FakeClient({"_global_": [page1, page2]})

    with caplog.at_level(logging.WARNING, logger="scrapper.sources.justjoinit"):
        jobs = JustJoinIt(max_offers=1000).fetch(client)

    assert len(jobs) == 2
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "503" in warnings[0].message or "503" in str(warnings[0].args)


def test_http_500_at_window_boundary_is_soft_end_without_warning(monkeypatch, caplog):
    monkeypatch.setattr(jj, "_PAGE_SIZE", 5)
    # Kursor sztucznie ustawiony blisko limitu okna (10000), żeby wywołać
    # gałąź "łagodny koniec" bez potrzeby realnie pobierania 10000 wpisów.
    page1 = _FakeResponse(
        {"data": [_entry(f"g{i}") for i in range(5)], "meta": {"next": {"cursor": 9998}}}
    )
    page2 = _FakeResponse({}, status_code=500)
    client = _FakeClient({"_global_": [page1, page2]})

    with caplog.at_level(logging.DEBUG, logger="scrapper.sources.justjoinit"):
        jobs = JustJoinIt(max_offers=1000).fetch(client)

    assert len(jobs) == 5
    assert not any(r.levelno == logging.WARNING for r in caplog.records)
    assert any(r.levelno == logging.DEBUG for r in caplog.records)


def test_max_offers_caps_total_across_all_cities_not_per_city(monkeypatch):
    monkeypatch.setattr(jj, "_PAGE_SIZE", 100)
    page_szczecin_1 = _FakeResponse(
        {"data": [_entry(f"a{i}") for i in range(100)], "meta": {"next": {"cursor": 100}}}
    )
    page_szczecin_2 = _FakeResponse(
        {"data": [_entry(f"a{i}") for i in range(100, 200)], "meta": {"next": {"cursor": 200}}}
    )
    page_gdansk = _FakeResponse(
        {"data": [_entry(f"b{i}") for i in range(100)], "meta": {"next": {"cursor": 100}}}
    )
    client = _FakeClient(
        {"szczecin": [page_szczecin_1, page_szczecin_2], "gdansk": [page_gdansk]}
    )

    jobs = JustJoinIt(max_offers=150, cities=["szczecin", "gdansk"]).fetch(client)

    assert len(jobs) <= 150
    # limit wyczerpał się na pierwszym mieście — drugie w ogóle nie odpytane
    requested_cities = [params.get("city") for _, params in client.calls]
    assert "gdansk" not in requested_cities


def test_nationwide_query_is_added_when_flag_set():
    """Bez zapytania bez filtra miasta oferty zdalne firm spoza profilu
    (np. Shoper: 18 ofert remote=True, wszystkie z city="Kraków") nigdy nie
    trafiłyby do puli, mimo `include_remote: true`."""
    seen_params = []

    def handler(request):
        seen_params.append(dict(request.url.params))
        return httpx.Response(200, json={"data": [], "meta": {}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        JustJoinIt(cities=["Szczecin"], include_nationwide=True).fetch(client)

    assert [p.get("city") for p in seen_params] == ["Szczecin", None]


def test_nationwide_query_absent_when_flag_unset():
    seen_params = []

    def handler(request):
        seen_params.append(dict(request.url.params))
        return httpx.Response(200, json={"data": [], "meta": {}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        JustJoinIt(cities=["Szczecin"], include_nationwide=False).fetch(client)

    assert [p.get("city") for p in seen_params] == ["Szczecin"]
