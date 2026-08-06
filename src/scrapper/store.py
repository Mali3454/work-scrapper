import json
import logging
from pathlib import Path

from scrapper.models import Job

logger = logging.getLogger(__name__)


def load_seen(path: Path) -> set[str]:
    path = Path(path)
    if not path.exists():
        return set()
    seen: set[str] = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                seen.add(json.loads(line)["key"])
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(
                    f"Skipping malformed line {line_no} in {path}: {e}"
                )
                continue
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
