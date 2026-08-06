import pytest

from scrapper.models import RawJob
from scrapper.sources.base import AllSourcesFailed, collect


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
