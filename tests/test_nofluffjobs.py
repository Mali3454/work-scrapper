import json
import logging
from pathlib import Path

import httpx
import pytest

from scrapper.sources import nofluffjobs as nfj
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


def test_parse_handles_null_postings():
    assert parse({"postings": None}) == []


# --- Fetch/paginacja/multi-miasto: atrapy klienta, bez sieci -------------------


def _entry(posting_id: str, city: str = "Warszawa") -> dict:
    return {
        "id": posting_id,
        "url": posting_id.casefold(),
        "title": f"Title {posting_id}",
        "name": "Co",
        "location": {"places": [{"city": city}], "fullyRemote": False},
        "salary": None,
        "posted": 1785535222245,
    }


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=httpx.Request("POST", nfj.API_URL),
                response=self,
            )

    def json(self):
        return self._payload


class _FakeClient:
    """Atrapa httpx.Client — kolejkuje odpowiedzi per miasto (klucz `_global_`
    gdy `criteriaSearch.city` puste/brak), zlicza wywołania i przekazane
    ciało/parametry zapytania."""

    def __init__(self, pages_by_city: dict[str, list[_FakeResponse]]):
        self._queues = {key: list(pages) for key, pages in pages_by_city.items()}
        self.calls: list[tuple[str, dict, dict]] = []

    def post(self, url, json=None, params=None):
        body = json or {}
        params = dict(params or {})
        self.calls.append((url, body, params))
        cities = (body.get("criteriaSearch") or {}).get("city") or []
        key = cities[0] if cities else "_global_"
        queue = self._queues.get(key)
        if not queue:
            return _FakeResponse({"postings": []})
        return queue.pop(0)


def _empty_page():
    return _FakeResponse({"postings": []})


def test_fetch_paginates_and_merges_pages(monkeypatch):
    monkeypatch.setattr(nfj, "_PAGE_SIZE", 2)
    page1 = _FakeResponse({"postings": [_entry("p1"), _entry("p2")]})
    page2 = _FakeResponse({"postings": [_entry("p3")]})
    client = _FakeClient({"_global_": [page1, page2]})

    jobs = NoFluffJobs(max_offers=1000).fetch(client)

    assert {job.external_id for job in jobs} == {"p1", "p2", "p3"}
    assert len(client.calls) == 2


def test_short_page_ends_pagination():
    # Strona krótsza niż _PAGE_SIZE (domyślnie 20) sygnalizuje koniec wyników
    # bez sięgania po kolejną stronę.
    page1 = _FakeResponse({"postings": [_entry("p1")]})
    client = _FakeClient({"_global_": [page1]})

    jobs = NoFluffJobs(max_offers=1000).fetch(client)

    assert len(jobs) == 1
    assert len(client.calls) == 1


def test_empty_response_ends_pagination_without_looping():
    client = _FakeClient({"_global_": [_empty_page()]})

    jobs = NoFluffJobs(max_offers=1000).fetch(client)

    assert jobs == []
    assert len(client.calls) == 1


def test_max_offers_caps_total_across_all_cities_not_per_city(monkeypatch):
    monkeypatch.setattr(nfj, "_PAGE_SIZE", 100)
    page_szczecin_1 = _FakeResponse({"postings": [_entry(f"a{i}") for i in range(100)]})
    page_szczecin_2 = _FakeResponse({"postings": [_entry(f"a{i}") for i in range(100, 200)]})
    page_gdansk = _FakeResponse({"postings": [_entry(f"b{i}") for i in range(100)]})
    client = _FakeClient(
        {"szczecin": [page_szczecin_1, page_szczecin_2], "gdansk": [page_gdansk]}
    )

    jobs = NoFluffJobs(max_offers=150, cities=["szczecin", "gdansk"]).fetch(client)

    assert len(jobs) <= 150
    # limit wyczerpał się na pierwszym mieście — drugie w ogóle nie odpytane
    requested_cities = [
        ((body.get("criteriaSearch") or {}).get("city") or [None])[0] for _, body, _ in client.calls
    ]
    assert "gdansk" not in requested_cities


def test_duplicate_id_across_pages_appears_once(monkeypatch):
    monkeypatch.setattr(nfj, "_PAGE_SIZE", 2)
    page1 = _FakeResponse({"postings": [_entry("dup"), _entry("p2")]})
    page2 = _FakeResponse({"postings": [_entry("dup"), _entry("p3")]})
    client = _FakeClient({"_global_": [page1, page2]})

    jobs = NoFluffJobs(max_offers=1000).fetch(client)

    ids = [job.external_id for job in jobs]
    assert ids.count("dup") == 1
    assert len(jobs) == 3


def test_duplicate_id_across_cities_appears_once():
    page_szczecin = _FakeResponse(
        {"postings": [_entry("dup", city="Szczecin"), _entry("s2", city="Szczecin")]}
    )
    page_gdansk = _FakeResponse(
        {"postings": [_entry("dup", city="Gdańsk"), _entry("g2", city="Gdańsk")]}
    )
    client = _FakeClient({"szczecin": [page_szczecin], "gdansk": [page_gdansk]})

    jobs = NoFluffJobs(cities=["szczecin", "gdansk"]).fetch(client)

    ids = [job.external_id for job in jobs]
    assert ids.count("dup") == 1
    assert len(jobs) == 3


def test_cities_list_triggers_query_per_city():
    client = _FakeClient({"szczecin": [_empty_page()], "gdansk": [_empty_page()]})

    NoFluffJobs(cities=["szczecin", "gdansk"]).fetch(client)

    requested_cities = [
        ((body.get("criteriaSearch") or {}).get("city") or [None])[0] for _, body, _ in client.calls
    ]
    assert requested_cities == ["szczecin", "gdansk"]


def test_cities_none_makes_single_query_without_city_filter():
    client = _FakeClient({"_global_": [_empty_page()]})

    NoFluffJobs(cities=None).fetch(client)

    assert len(client.calls) == 1
    _, body, _ = client.calls[0]
    assert body == {"criteriaSearch": {}}


def test_required_query_params_are_always_sent():
    client = _FakeClient({"_global_": [_empty_page()]})

    NoFluffJobs(cities=None).fetch(client)

    _, _, params = client.calls[0]
    assert params["salaryCurrency"] == "PLN"
    assert params["salaryPeriod"] == "month"


def test_subsequent_page_http_error_returns_partial_results_and_logs_warning(monkeypatch, caplog):
    monkeypatch.setattr(nfj, "_PAGE_SIZE", 2)
    page1 = _FakeResponse({"postings": [_entry("p1"), _entry("p2")]})
    page2 = _FakeResponse({}, status_code=503)
    client = _FakeClient({"_global_": [page1, page2]})

    with caplog.at_level(logging.WARNING, logger="scrapper.sources.nofluffjobs"):
        jobs = NoFluffJobs(max_offers=1000).fetch(client)

    assert len(jobs) == 2
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "503" in warnings[0].message or "503" in str(warnings[0].args)


def test_first_page_http_error_propagates():
    client = _FakeClient({"_global_": [_FakeResponse({}, status_code=500)]})

    with pytest.raises(httpx.HTTPStatusError):
        NoFluffJobs().fetch(client)
