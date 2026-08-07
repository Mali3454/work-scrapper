import pytest

from scrapper.models import RawJob
from scrapper.sources.base import AllSourcesFailed, build_queries, collect


class FakeSource:
    def __init__(self, name, jobs=None, error=None):
        self.name = name
        self._jobs = jobs or []
        self._error = error

    def fetch(self, client):
        if self._error:
            raise RuntimeError(self._error)
        return self._jobs


def _job() -> RawJob:
    return RawJob(source="fake", external_id="1", title="React Dev",
                  company="Acme", url="https://example.com/1")


def test_collect_returns_jobs_from_each_source():
    results = collect([FakeSource("a", jobs=[_job()]), FakeSource("b", jobs=[_job()])],
                      client=None)

    assert [r.name for r in results] == ["a", "b"]
    assert all(len(r.jobs) == 1 for r in results)


def test_failing_source_does_not_stop_others():
    results = collect([FakeSource("padnie", error="timeout"), FakeSource("dziala", jobs=[_job()])],
                      client=None)

    assert results[0].error is not None
    assert "timeout" in results[0].error
    assert results[0].jobs == []
    assert len(results[1].jobs) == 1


def test_successful_source_has_no_error():
    results = collect([FakeSource("a", jobs=[_job()])], client=None)

    assert results[0].error is None


def test_all_sources_failing_raises():
    sources = [FakeSource("a", error="timeout"), FakeSource("b", error="500")]

    with pytest.raises(AllSourcesFailed):
        collect(sources, client=None)


def test_empty_results_are_not_treated_as_failure():
    results = collect([FakeSource("a", jobs=[])], client=None)

    assert results[0].error is None


def test_build_queries_appends_nationwide_after_cities():
    """Pula ogólnopolska jest potrzebna dla ofert ZDALNYCH: portale tagują je
    miastem siedziby firmy, więc zapytanie o Szczecin nie zwróci zdalnej oferty
    firmy z Krakowa. Miasta idą pierwsze — mają priorytet przy dzieleniu
    budżetu `max_offers`."""
    assert build_queries(["Szczecin", "Gdańsk"], True) == ["Szczecin", "Gdańsk", None]


def test_build_queries_without_nationwide_keeps_only_cities():
    assert build_queries(["Szczecin"], False) == ["Szczecin"]


def test_build_queries_without_cities_always_queries_nationwide():
    # Brak miast = brak filtra, niezależnie od flagi — inaczej źródło nie
    # wysłałoby ani jednego zapytania i cicho zwróciło zero ofert.
    assert build_queries(None, False) == [None]
    assert build_queries([], False) == [None]
