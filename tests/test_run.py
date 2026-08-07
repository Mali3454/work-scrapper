from datetime import datetime, timezone

import pytest

from scrapper.models import Config, Profile, RawJob, SmtpConfig
from scrapper.run import categories_from_profiles, cities_from_profiles, run
from scrapper.sources.base import AllSourcesFailed
from scrapper.store import load_seen

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)

CONFIG = Config(
    smtp=SmtpConfig(host="smtp.example.com", port=587, user="me@example.com",
                    password="sekret", to="olosolo16@gmail.com"),
    profiles=[Profile(name="frontend", keywords=["react"], locations=["szczecin"])],
)


class CountingSource:
    def __init__(self, jobs, name="fake", error=None):
        self.name, self._jobs, self._error = name, jobs, error
        self.calls = 0

    def fetch(self, client):
        self.calls += 1
        if self._error:
            raise RuntimeError(self._error)
        return self._jobs


FakeSource = CountingSource


def _raw(title="React Developer", **overrides) -> RawJob:
    data = {"source": "justjoinit", "external_id": "1", "title": title,
            "company": "Acme", "city": "Szczecin", "remote": False,
            "url": "https://justjoin.it/1"}
    data.update(overrides)
    return RawJob(**data)


class RecordingSender:
    def __init__(self):
        self.messages = []

    def __call__(self, host, port):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        pass

    def send_message(self, message):
        self.messages.append(message)


class FailingSender(RecordingSender):
    def send_message(self, message):
        raise RuntimeError("SMTP padł")


def test_sends_new_jobs_and_records_them(tmp_path):
    path = tmp_path / "jobs.jsonl"
    sender = RecordingSender()

    count = run(CONFIG, [FakeSource([_raw()])], path, client=None, now=NOW, sender=sender)

    assert count == 1
    assert len(sender.messages) == 1
    assert load_seen(path) != set()


def test_second_run_sends_nothing(tmp_path):
    path = tmp_path / "jobs.jsonl"
    run(CONFIG, [FakeSource([_raw()])], path, client=None, now=NOW, sender=RecordingSender())

    sender = RecordingSender()
    count = run(CONFIG, [FakeSource([_raw()])], path, client=None, now=NOW, sender=sender)

    assert count == 0
    assert sender.messages == []


def test_non_matching_jobs_are_not_sent(tmp_path):
    sender = RecordingSender()

    count = run(CONFIG, [FakeSource([_raw(title="Backend Developer")])],
                tmp_path / "jobs.jsonl", client=None, now=NOW, sender=sender)

    assert count == 0
    assert sender.messages == []


def test_failing_source_does_not_break_run(tmp_path):
    sender = RecordingSender()
    sources = [FakeSource([], name="zly", error="timeout"), FakeSource([_raw()], name="dobry")]

    count = run(CONFIG, sources, tmp_path / "jobs.jsonl", client=None, now=NOW, sender=sender)

    assert count == 1


def test_zero_offers_from_every_source_fails_the_run(tmp_path):
    """Padnięcie portali nie może dać zielonego runu.

    `CompaniesSource` z założenia nie rzuca wyjątków (łapie błędy per firma),
    więc gdy portale przestaną odpowiadać, `collect` nie zobaczy "wszystkie
    padły" i przebieg zakończyłby się cicho z `nowe_oferty=0`. Maila też by nie
    było, bo mail idzie tylko przy nowych ofertach — awaria byłaby niewidoczna.
    """
    sources = [FakeSource([], name="justjoinit", error="timeout"),
               FakeSource([], name="companies")]

    with pytest.raises(AllSourcesFailed):
        run(CONFIG, sources, tmp_path / "jobs.jsonl", client=None, now=NOW,
            sender=RecordingSender())


def test_offers_that_match_nothing_are_not_a_failure(tmp_path):
    # Źródła DZIAŁAJĄ (zwracają oferty), tylko nic nie pasuje do profilu —
    # to normalny przebieg, nie awaria.
    count = run(CONFIG, [FakeSource([_raw(title="Backend Developer")])],
                tmp_path / "jobs.jsonl", client=None, now=NOW, sender=RecordingSender())

    assert count == 0


def test_smtp_failure_does_not_persist_state(tmp_path):
    path = tmp_path / "jobs.jsonl"

    with pytest.raises(RuntimeError, match="SMTP padł"):
        run(CONFIG, [FakeSource([_raw()])], path, client=None, now=NOW, sender=FailingSender())

    assert load_seen(path) == set()


def test_sources_are_queried_once_regardless_of_profile_count(tmp_path):
    config = CONFIG.model_copy(update={"profiles": [
        Profile(name="frontend", keywords=["react"], locations=["szczecin"]),
        Profile(name="js", keywords=["javascript"], locations=["szczecin"]),
    ]})
    source = CountingSource([_raw()])

    run(config, [source], tmp_path / "jobs.jsonl", client=None, now=NOW, sender=RecordingSender())

    assert source.calls == 1


def test_job_matching_two_profiles_is_sent_once(tmp_path):
    config = CONFIG.model_copy(update={"profiles": [
        Profile(name="a", keywords=["react"], locations=["szczecin"]),
        Profile(name="b", keywords=["developer"], locations=["szczecin"]),
    ]})

    count = run(config, [FakeSource([_raw()])], tmp_path / "jobs.jsonl",
                client=None, now=NOW, sender=RecordingSender())

    assert count == 1


def test_cities_from_profiles_deduplicates_case_insensitively():
    profiles = [
        Profile(name="a", keywords=["react"], locations=["Szczecin"]),
        Profile(name="b", keywords=["developer"], locations=["szczecin", "Gdańsk"]),
    ]

    cities = cities_from_profiles(profiles)

    assert cities == ["Szczecin", "Gdańsk"]


def test_cities_from_profiles_returns_none_when_no_locations():
    profiles = [Profile(name="a", keywords=["react"], locations=[])]

    assert cities_from_profiles(profiles) is None


def test_categories_from_profiles_unions_and_deduplicates():
    profiles = [
        Profile(name="a", keywords=["x"], nofluffjobs_categories=["frontend", "mobile"]),
        Profile(name="b", keywords=["y"], nofluffjobs_categories=["Frontend", "fullstack"]),
    ]

    assert categories_from_profiles(profiles) == ["frontend", "mobile", "fullstack"]


def test_categories_from_profiles_returns_none_when_unset():
    # None, nie [] — pusta lista trafiłaby do zapytania jako pusty filtr.
    assert categories_from_profiles([Profile(name="a", keywords=["x"])]) is None
