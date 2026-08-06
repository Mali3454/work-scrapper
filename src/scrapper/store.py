import json
from pathlib import Path

from scrapper.models import Job


def load_seen(path: Path) -> set[str]:
    path = Path(path)
    if not path.exists():
        return set()
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            seen.add(json.loads(line)["key"])
    return seen


def select_new(jobs: list[Job], seen: set[str]) -> list[Job]:
    return [job for job in jobs if job.key not in seen]


def append(path: Path, jobs: list[Job]) -> None:
    if not jobs:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for job in jobs:
            handle.write(job.model_dump_json() + "\n")
