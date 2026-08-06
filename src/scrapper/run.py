import logging
import os
import smtplib
import sys
from datetime import datetime, timezone
from pathlib import Path

from scrapper.config import load_config
from scrapper.deduper import deduplicate
from scrapper.matcher import filter_jobs
from scrapper.models import Config
from scrapper.notifier import render, send, subject_for, warnings_from
from scrapper.sources.base import Source, build_client, collect
from scrapper.sources.justjoinit import JustJoinIt
from scrapper.store import append, load_seen, select_new

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config.yaml"
STORE_PATH = ROOT / "data" / "jobs.jsonl"


def run(config: Config, sources: list[Source], store_path: Path, client,
        now: datetime, sender=smtplib.SMTP) -> int:
    results = collect(sources, client)  # jedno odpytanie źródeł na przebieg
    warnings = warnings_from(results)

    matched = []
    for profile in config.profiles:
        for result in results:
            matched.extend(filter_jobs(result.jobs, profile, now))

    # Oferta pasująca do dwóch profili trafia tu dwa razy — deduplikacja to scala.
    jobs = deduplicate(matched, now)
    new_jobs = select_new(jobs, load_seen(store_path))

    if not new_jobs:
        logger.info("Brak nowych ofert (dopasowanych: %d)", len(jobs))
        return 0

    send(config.smtp, subject_for(new_jobs), render(new_jobs, warnings), sender=sender)
    append(store_path, new_jobs)  # dopiero po udanej wysyłce
    logger.info("Wysłano %d nowych ofert", len(new_jobs))
    return len(new_jobs)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = load_config(CONFIG_PATH, env=os.environ)
    with build_client() as client:
        count = run(config, [JustJoinIt()], STORE_PATH, client, datetime.now(timezone.utc))
    print(f"nowe_oferty={count}")


if __name__ == "__main__":
    sys.exit(main())
