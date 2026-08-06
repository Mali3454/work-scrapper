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


def test_load_seen_skips_malformed_json_line(tmp_path):
    path = tmp_path / "jobs.jsonl"
    # Write one valid line and one broken line
    path.write_text(
        '{"key": "a", "source": "justjoinit"}\n'
        '{"key": "b"',  # Missing closing brace
        encoding="utf-8",
    )

    result = load_seen(path)

    assert result == {"a"}


def test_load_seen_skips_json_without_key(tmp_path):
    path = tmp_path / "jobs.jsonl"
    # Write one valid line and one without 'key'
    path.write_text(
        '{"key": "a", "source": "justjoinit"}\n'
        '{"source": "justjoinit", "title": "DevOps"}\n',
        encoding="utf-8",
    )

    result = load_seen(path)

    assert result == {"a"}


def test_load_seen_skips_merge_conflict_lines(tmp_path):
    path = tmp_path / "jobs.jsonl"
    # Write valid lines with merge conflict markers
    path.write_text(
        '{"key": "a", "source": "justjoinit"}\n'
        "<<<<<<< HEAD\n"
        '{"key": "b", "source": "justjoinit"}\n'
        "=======\n"
        '{"key": "c", "source": "justjoinit"}\n'
        ">>>>>>> main\n",
        encoding="utf-8",
    )

    result = load_seen(path)

    # Only valid keys should be loaded
    assert "a" in result
    assert "HEAD" not in result
    assert "=======" not in result
    assert "main" not in result


def test_append_uses_unix_newlines(tmp_path):
    path = tmp_path / "jobs.jsonl"

    append(path, [_job("a")])

    binary_content = path.read_bytes()

    assert b"\n" in binary_content
    assert b"\r\n" not in binary_content
