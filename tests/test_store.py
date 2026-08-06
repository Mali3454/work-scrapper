import json
from datetime import datetime, timezone

from scrapper.models import Job
from scrapper.store import append, load_seen, select_new

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


def _job(key: str) -> Job:
    return Job(
        source="justjoinit",
        external_id=key,
        title="Frontend Developer",
        company="Acme",
        city="Szczecin",
        remote=False,
        url=f"https://example.com/{key}",
        key=key,
        first_seen=NOW,
    )


def test_load_seen_returns_empty_set_when_file_missing(tmp_path):
    assert load_seen(tmp_path / "brak.jsonl") == set()


def test_append_then_load_seen_roundtrip(tmp_path):
    path = tmp_path / "data" / "jobs.jsonl"

    append(path, [_job("a"), _job("b")])

    assert load_seen(path) == {"a", "b"}


def test_append_does_not_overwrite_existing_lines(tmp_path):
    path = tmp_path / "jobs.jsonl"
    append(path, [_job("a")])

    append(path, [_job("b")])

    assert load_seen(path) == {"a", "b"}


def test_appended_line_is_valid_json_with_key(tmp_path):
    path = tmp_path / "jobs.jsonl"

    append(path, [_job("a")])

    line = path.read_text(encoding="utf-8").splitlines()[0]
    assert json.loads(line)["key"] == "a"


def test_select_new_returns_only_unseen(tmp_path):
    result = select_new([_job("a"), _job("b")], seen={"a"})

    assert [j.key for j in result] == ["b"]


def test_second_run_reports_nothing_new(tmp_path):
    path = tmp_path / "jobs.jsonl"
    jobs = [_job("a"), _job("b")]
    append(path, select_new(jobs, load_seen(path)))

    second_run = select_new(jobs, load_seen(path))

    assert second_run == []
