# Agregator ofert pracy — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zbudować system, który co godzinę zbiera oferty pracy z portali i stron
firm, filtruje je wg profilu i wysyła mailem wyłącznie nowe znaleziska.

**Architecture:** Jeden skrypt uruchamiany przez cron w GitHub Actions. Źródła
implementują wspólny protokół i są od siebie niezależne — awaria jednego nie
zatrzymuje pozostałych. Stan (co już wysłano) żyje w append-only pliku
`data/jobs.jsonl` commitowanym do repo, bo Actions nie zachowuje dysku między
przebiegami. Stan zapisujemy dopiero po udanej wysyłce maila.

**Tech Stack:** Python 3.12, httpx, selectolax, pydantic v2, jinja2, PyYAML, pytest.

## Global Constraints

- Python 3.12. Zależności w `pyproject.toml`, instalacja przez `pip install -e ".[dev]"`.
- Wszystkie testy działają **bez sieci**. Odpowiedzi HTTP pochodzą z fixture'ów w `tests/fixtures/`.
- Kod źródłowy w `src/scrapper/`, testy w `tests/`, mapowanie 1:1 (`matcher.py` → `test_matcher.py`).
- Sekrety wyłącznie przez zmienne środowiskowe: `SMTP_USER`, `SMTP_PASSWORD`. Nigdy w repo.
- Adres docelowy maila: `olosolo16@gmail.com`.
- Nazwa źródła (`source`) to stały string: `justjoinit`, `nofluffjobs`, albo `company:<slug>`.
- Priorytet źródeł przy deduplikacji (wyższy wygrywa): `company:* = 100`, `nofluffjobs = 50`, `justjoinit = 40`.
- Commity: `feat:`, `test:`, `chore:`, `fix:`. Jeden commit na zadanie, chyba że krok mówi inaczej.
- Czas zawsze w UTC, timezone-aware (`datetime.now(timezone.utc)`).

## Mapa plików

| Plik | Odpowiedzialność |
| --- | --- |
| `src/scrapper/models.py` | `RawJob`, `Job`, `Profile`, `SmtpConfig`, `Config` |
| `src/scrapper/config.py` | Wczytanie YAML-i, podstawienie zmiennych środowiskowych |
| `src/scrapper/matcher.py` | Decyzja, czy oferta pasuje do profilu |
| `src/scrapper/deduper.py` | Klucz deduplikacji, scalanie duplikatów |
| `src/scrapper/store.py` | Odczyt i dopisywanie `data/jobs.jsonl` |
| `src/scrapper/notifier.py` | Render HTML i wysyłka SMTP |
| `src/scrapper/sources/base.py` | Protokół `Source`, wspólny klient HTTP |
| `src/scrapper/sources/justjoinit.py` | Źródło JustJoinIT |
| `src/scrapper/sources/nofluffjobs.py` | Źródło NoFluffJobs |
| `src/scrapper/sources/ats/*.py` | Parsery systemów ATS |
| `src/scrapper/sources/companies.py` | Rozdzielanie `companies.yaml` na parsery ATS |
| `src/scrapper/run.py` | Orkiestracja przebiegu |
| `.github/workflows/scrape.yml` | Cron + commit stanu |

---

# Faza 1 — działający MVP end-to-end

Po tej fazie system realnie działa: JustJoinIT → filtr → mail.

---

### Task 1: Szkielet projektu

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/scrapper/__init__.py`, `tests/__init__.py`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Consumes: nic
- Produces: importowalny pakiet `scrapper`, działające `pytest`

- [ ] **Step 1: Utwórz `pyproject.toml`**

```toml
[project]
name = "work-scrapper"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "selectolax>=0.3.21",
    "pydantic>=2.7",
    "jinja2>=3.1",
    "PyYAML>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Utwórz `.gitignore`**

```
__pycache__/
*.pyc
.venv/
*.egg-info/
.pytest_cache/
.env
```

- [ ] **Step 3: Utwórz puste `src/scrapper/__init__.py` i `tests/__init__.py`**

Oba pliki puste. Istnieją tylko po to, żeby Python traktował katalogi jako pakiety.

- [ ] **Step 4: Napisz test dymny**

`tests/test_smoke.py`:

```python
def test_package_imports():
    import scrapper

    assert scrapper is not None
```

- [ ] **Step 5: Utwórz środowisko i zainstaluj**

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
```

(Na Windows ścieżka to `.venv/Scripts/`, nie `.venv/bin/`.)

- [ ] **Step 6: Uruchom testy**

Run: `.venv/Scripts/pytest -v`
Expected: PASS, 1 test

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore src tests
git commit -m "chore: szkielet projektu z pytest"
```

---

### Task 2: Modele danych

**Files:**
- Create: `src/scrapper/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nic
- Produces:
  - `RawJob(source: str, external_id: str, title: str, company: str, city: str | None, remote: bool, url: str, salary: str | None, posted_at: datetime | None)`
  - `Job(RawJob + key: str, alt_urls: list[str], first_seen: datetime)`
  - `Profile(name, keywords: list[str], exclude: list[str], locations: list[str], include_remote: bool, max_age_days: int)`
  - `SmtpConfig(host, port, user, password, to)`
  - `Config(smtp: SmtpConfig, profiles: list[Profile])`

- [ ] **Step 1: Napisz test**

`tests/test_models.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from scrapper.models import Job, Profile, RawJob


def _raw(**overrides) -> RawJob:
    data = {
        "source": "justjoinit",
        "external_id": "abc123",
        "title": "Frontend Developer",
        "company": "Acme",
        "city": "Szczecin",
        "remote": False,
        "url": "https://example.com/oferta",
        "salary": "12 000 - 16 000 PLN",
        "posted_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return RawJob(**data)


def test_rawjob_holds_all_fields():
    job = _raw()

    assert job.company == "Acme"
    assert job.remote is False


def test_rawjob_allows_missing_optional_fields():
    job = _raw(city=None, salary=None, posted_at=None)

    assert job.city is None
    assert job.salary is None


def test_rawjob_rejects_missing_url():
    with pytest.raises(ValidationError):
        RawJob(source="justjoinit", external_id="x", title="t", company="c", remote=False)


def test_job_defaults_alt_urls_to_empty_list():
    job = Job(**_raw().model_dump(), key="acme|frontend-developer|szczecin",
              first_seen=datetime(2026, 8, 6, tzinfo=timezone.utc))

    assert job.alt_urls == []


def test_profile_defaults():
    profile = Profile(name="frontend", keywords=["react"])

    assert profile.exclude == []
    assert profile.include_remote is True
    assert profile.max_age_days == 14
```

- [ ] **Step 2: Uruchom test, potwierdź porażkę**

Run: `.venv/Scripts/pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapper.models'`

- [ ] **Step 3: Zaimplementuj modele**

`src/scrapper/models.py`:

```python
from datetime import datetime

from pydantic import BaseModel, Field


class RawJob(BaseModel):
    """Oferta w postaci zwróconej przez źródło, przed dedup i filtrowaniem."""

    source: str
    external_id: str
    title: str
    company: str
    city: str | None = None
    remote: bool = False
    url: str
    salary: str | None = None
    posted_at: datetime | None = None


class Job(RawJob):
    """Oferta po deduplikacji, gotowa do zapisu i wysyłki."""

    key: str
    alt_urls: list[str] = Field(default_factory=list)
    first_seen: datetime


class Profile(BaseModel):
    name: str
    keywords: list[str]
    exclude: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    include_remote: bool = True
    max_age_days: int = 14


class SmtpConfig(BaseModel):
    host: str
    port: int = 587
    user: str
    password: str
    to: str


class Config(BaseModel):
    smtp: SmtpConfig
    profiles: list[Profile]
```

- [ ] **Step 4: Uruchom testy**

Run: `.venv/Scripts/pytest tests/test_models.py -v`
Expected: PASS, 5 testów

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/models.py tests/test_models.py
git commit -m "feat: modele danych ofert i konfiguracji"
```

---

### Task 3: Wczytywanie konfiguracji

**Files:**
- Create: `src/scrapper/config.py`, `config.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `Config`, `Profile`, `SmtpConfig` z Task 2
- Produces: `load_config(path: Path, env: Mapping[str, str]) -> Config`

Podstawianie `${NAZWA}` ze zmiennych środowiskowych dzieje się przy wczytywaniu.
Brakująca zmienna to twardy błąd — lepiej wysypać się na starcie niż wysłać maila
z pustym hasłem.

- [ ] **Step 1: Napisz test**

`tests/test_config.py`:

```python
import pytest

from scrapper.config import MissingEnvVar, load_config

CONFIG_YAML = """
smtp:
  host: smtp.gmail.com
  port: 587
  user: ${SMTP_USER}
  password: ${SMTP_PASSWORD}
  to: olosolo16@gmail.com

profiles:
  - name: frontend-szczecin
    keywords: [frontend, react]
    exclude: [senior]
    locations: [szczecin]
    include_remote: true
    max_age_days: 14
"""


def test_loads_profiles_and_smtp(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_YAML, encoding="utf-8")

    config = load_config(path, env={"SMTP_USER": "me@gmail.com", "SMTP_PASSWORD": "sekret"})

    assert config.smtp.user == "me@gmail.com"
    assert config.smtp.password == "sekret"
    assert len(config.profiles) == 1
    assert config.profiles[0].keywords == ["frontend", "react"]


def test_missing_env_var_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_YAML, encoding="utf-8")

    with pytest.raises(MissingEnvVar, match="SMTP_PASSWORD"):
        load_config(path, env={"SMTP_USER": "me@gmail.com"})


def test_literal_values_pass_through(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_YAML.replace("${SMTP_USER}", "stale@example.com"), encoding="utf-8")

    config = load_config(path, env={"SMTP_PASSWORD": "sekret"})

    assert config.smtp.user == "stale@example.com"
```

- [ ] **Step 2: Uruchom test, potwierdź porażkę**

Run: `.venv/Scripts/pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapper.config'`

- [ ] **Step 3: Zaimplementuj**

`src/scrapper/config.py`:

```python
import re
from collections.abc import Mapping
from pathlib import Path

import yaml

from scrapper.models import Config

ENV_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


class MissingEnvVar(RuntimeError):
    """Konfiguracja odwołuje się do zmiennej środowiskowej, której nie ma."""


def _expand(value, env: Mapping[str, str]):
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            name = match.group(1)
            if name not in env:
                raise MissingEnvVar(f"Brak zmiennej środowiskowej: {name}")
            return env[name]

        return ENV_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {k: _expand(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v, env) for v in value]
    return value


def load_config(path: Path, env: Mapping[str, str]) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Config(**_expand(raw, env))
```

- [ ] **Step 4: Uruchom testy**

Run: `.venv/Scripts/pytest tests/test_config.py -v`
Expected: PASS, 3 testy

- [ ] **Step 5: Utwórz realny `config.yaml` w katalogu głównym**

Treść dokładnie jak `CONFIG_YAML` w teście, z zachowanymi `${SMTP_USER}` i
`${SMTP_PASSWORD}`. Ten plik trafia do repo — nie zawiera sekretów.

- [ ] **Step 6: Commit**

```bash
git add src/scrapper/config.py tests/test_config.py config.yaml
git commit -m "feat: wczytywanie konfiguracji z podstawianiem zmiennych środowiskowych"
```

---

### Task 4: Matcher — filtrowanie wg profilu

**Files:**
- Create: `src/scrapper/matcher.py`
- Test: `tests/test_matcher.py`

**Interfaces:**
- Consumes: `RawJob`, `Profile` z Task 2
- Produces:
  - `matches(job: RawJob, profile: Profile, now: datetime) -> bool`
  - `filter_jobs(jobs: list[RawJob], profile: Profile, now: datetime) -> list[RawJob]`

Reguły, w kolejności sprawdzania: odrzuć jeśli tytuł zawiera słowo z `exclude`;
odrzuć jeśli żadne słowo z `keywords` nie występuje w tytule; odrzuć jeśli
lokalizacja nie pasuje (miasto spoza `locations` i oferta nie jest zdalna, albo
jest zdalna a `include_remote` jest wyłączone); odrzuć jeśli oferta starsza niż
`max_age_days`. Oferta bez `posted_at` przechodzi kontrolę wieku — nie znamy
daty, więc zakładamy świeżość.

Porównania są bez uwzględniania wielkości liter i dopasowują **całe słowa**, żeby
`exclude: [lead]` nie ubiło oferty „Team **Lead**ership Tools Developer" przez
przypadkowy fragment innego wyrazu.

- [ ] **Step 1: Napisz test**

`tests/test_matcher.py`:

```python
from datetime import datetime, timedelta, timezone

from scrapper.matcher import filter_jobs, matches
from scrapper.models import Profile, RawJob

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)

PROFILE = Profile(
    name="frontend-szczecin",
    keywords=["frontend", "react"],
    exclude=["senior", "lead"],
    locations=["szczecin"],
    include_remote=True,
    max_age_days=14,
)


def _job(**overrides) -> RawJob:
    data = {
        "source": "justjoinit",
        "external_id": "1",
        "title": "Frontend Developer",
        "company": "Acme",
        "city": "Szczecin",
        "remote": False,
        "url": "https://example.com/1",
        "posted_at": NOW - timedelta(days=1),
    }
    data.update(overrides)
    return RawJob(**data)


def test_accepts_matching_job():
    assert matches(_job(), PROFILE, NOW) is True


def test_keyword_match_is_case_insensitive():
    assert matches(_job(title="REACT Engineer"), PROFILE, NOW) is True


def test_rejects_job_without_any_keyword():
    assert matches(_job(title="Backend Developer"), PROFILE, NOW) is False


def test_rejects_excluded_title():
    assert matches(_job(title="Senior Frontend Developer"), PROFILE, NOW) is False


def test_exclude_matches_whole_words_only():
    assert matches(_job(title="Frontend Developer - Leadership Tools"), PROFILE, NOW) is True


def test_rejects_other_city_when_not_remote():
    assert matches(_job(city="Kraków"), PROFILE, NOW) is False


def test_accepts_remote_job_from_other_city():
    assert matches(_job(city="Kraków", remote=True), PROFILE, NOW) is True


def test_rejects_remote_when_profile_excludes_remote():
    profile = PROFILE.model_copy(update={"include_remote": False})

    assert matches(_job(city="Kraków", remote=True), profile, NOW) is False


def test_rejects_job_older_than_max_age():
    assert matches(_job(posted_at=NOW - timedelta(days=30)), PROFILE, NOW) is False


def test_accepts_job_without_posted_at():
    assert matches(_job(posted_at=None), PROFILE, NOW) is True


def test_filter_jobs_keeps_only_matching():
    jobs = [_job(external_id="1"), _job(external_id="2", title="Backend Developer")]

    result = filter_jobs(jobs, PROFILE, NOW)

    assert [j.external_id for j in result] == ["1"]
```

- [ ] **Step 2: Uruchom test, potwierdź porażkę**

Run: `.venv/Scripts/pytest tests/test_matcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapper.matcher'`

- [ ] **Step 3: Zaimplementuj**

`src/scrapper/matcher.py`:

```python
import re
from datetime import datetime, timedelta

from scrapper.models import Profile, RawJob


def _contains_word(haystack: str, needle: str) -> bool:
    """Dopasowanie całego słowa, odporne na wielkość liter.

    'lead' nie trafia w 'Leadership', ale 'next.js' trafia w 'Next.js Developer'.
    """
    pattern = r"(?<!\w)" + re.escape(needle) + r"(?!\w)"
    return re.search(pattern, haystack, flags=re.IGNORECASE) is not None


def _location_ok(job: RawJob, profile: Profile) -> bool:
    if job.remote:
        return profile.include_remote
    if not profile.locations:
        return True
    city = (job.city or "").casefold()
    return any(loc.casefold() in city for loc in profile.locations)


def _age_ok(job: RawJob, profile: Profile, now: datetime) -> bool:
    if job.posted_at is None:
        return True
    return job.posted_at >= now - timedelta(days=profile.max_age_days)


def matches(job: RawJob, profile: Profile, now: datetime) -> bool:
    if any(_contains_word(job.title, word) for word in profile.exclude):
        return False
    if not any(_contains_word(job.title, word) for word in profile.keywords):
        return False
    if not _location_ok(job, profile):
        return False
    return _age_ok(job, profile, now)


def filter_jobs(jobs: list[RawJob], profile: Profile, now: datetime) -> list[RawJob]:
    return [job for job in jobs if matches(job, profile, now)]
```

- [ ] **Step 4: Uruchom testy**

Run: `.venv/Scripts/pytest tests/test_matcher.py -v`
Expected: PASS, 11 testów

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/matcher.py tests/test_matcher.py
git commit -m "feat: filtrowanie ofert wg profilu szukania"
```

---

### Task 5: Deduper

**Files:**
- Create: `src/scrapper/deduper.py`
- Test: `tests/test_deduper.py`

**Interfaces:**
- Consumes: `RawJob`, `Job` z Task 2
- Produces:
  - `dedup_key(job: RawJob) -> str`
  - `deduplicate(jobs: list[RawJob], now: datetime) -> list[Job]`
  - `SOURCE_PRIORITY: dict[str, int]`, `priority_of(source: str) -> int`

Klucz to `slug(company)|slug(title)|slug(city)`. Oferta zdalna bez miasta używa
stałej `remote`, żeby ta sama oferta zdalna z dwóch portali nie przeszła jako
dwie różne. Przy kolizji wygrywa wpis o wyższym priorytecie źródła; URL-e
przegranych trafiają do `alt_urls`.

- [ ] **Step 1: Napisz test**

`tests/test_deduper.py`:

```python
from datetime import datetime, timezone

from scrapper.deduper import dedup_key, deduplicate, priority_of
from scrapper.models import RawJob

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


def _job(**overrides) -> RawJob:
    data = {
        "source": "justjoinit",
        "external_id": "1",
        "title": "Frontend Developer",
        "company": "Acme Sp. z o.o.",
        "city": "Szczecin",
        "remote": False,
        "url": "https://justjoin.it/1",
    }
    data.update(overrides)
    return RawJob(**data)


def test_key_normalizes_case_and_punctuation():
    a = dedup_key(_job(company="Acme Sp. z o.o.", title="Frontend Developer"))
    b = dedup_key(_job(company="ACME  sp. z o.o.", title="frontend developer"))

    assert a == b


def test_key_differs_for_different_title():
    assert dedup_key(_job()) != dedup_key(_job(title="Backend Developer"))


def test_remote_job_without_city_uses_remote_marker():
    key = dedup_key(_job(city=None, remote=True))

    assert key.endswith("|remote")


def test_same_remote_job_from_two_sources_shares_key():
    a = dedup_key(_job(source="justjoinit", city=None, remote=True))
    b = dedup_key(_job(source="nofluffjobs", city="", remote=True))

    assert a == b


def test_company_source_has_highest_priority():
    assert priority_of("company:blstream") > priority_of("nofluffjobs")
    assert priority_of("nofluffjobs") > priority_of("justjoinit")


def test_unknown_source_has_lowest_priority():
    assert priority_of("cokolwiek") == 0


def test_deduplicate_merges_and_prefers_company_source():
    jobs = [
        _job(source="justjoinit", url="https://justjoin.it/1"),
        _job(source="nofluffjobs", url="https://nofluffjobs.com/1"),
        _job(source="company:acme", url="https://acme.com/kariera/1"),
    ]

    result = deduplicate(jobs, NOW)

    assert len(result) == 1
    assert result[0].source == "company:acme"
    assert result[0].url == "https://acme.com/kariera/1"
    assert sorted(result[0].alt_urls) == ["https://justjoin.it/1", "https://nofluffjobs.com/1"]


def test_deduplicate_keeps_distinct_jobs():
    jobs = [_job(external_id="1"), _job(external_id="2", title="React Native Developer")]

    result = deduplicate(jobs, NOW)

    assert len(result) == 2


def test_deduplicate_sets_first_seen():
    result = deduplicate([_job()], NOW)

    assert result[0].first_seen == NOW
```

- [ ] **Step 2: Uruchom test, potwierdź porażkę**

Run: `.venv/Scripts/pytest tests/test_deduper.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapper.deduper'`

- [ ] **Step 3: Zaimplementuj**

`src/scrapper/deduper.py`:

```python
import re
import unicodedata
from datetime import datetime

from scrapper.models import Job, RawJob

SOURCE_PRIORITY = {"nofluffjobs": 50, "justjoinit": 40}
COMPANY_PRIORITY = 100

# Sufiksy form prawnych — 'Acme' i 'Acme Sp. z o.o.' to ta sama firma.
LEGAL_SUFFIXES = ("sp z o o", "sp z oo", "sa", "sp j", "sp k", "z o o")


def priority_of(source: str) -> int:
    if source.startswith("company:"):
        return COMPANY_PRIORITY
    return SOURCE_PRIORITY.get(source, 0)


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-z0-9]+", " ", ascii_only.casefold()).strip()
    return re.sub(r"\s+", "-", cleaned)


def _company_slug(company: str) -> str:
    slug = _slug(company)
    spaced = slug.replace("-", " ")
    for suffix in LEGAL_SUFFIXES:
        if spaced.endswith(" " + suffix):
            spaced = spaced[: -len(suffix) - 1]
    return _slug(spaced)


def dedup_key(job: RawJob) -> str:
    city = _slug(job.city or "") or ("remote" if job.remote else "")
    return f"{_company_slug(job.company)}|{_slug(job.title)}|{city}"


def deduplicate(jobs: list[RawJob], now: datetime) -> list[Job]:
    best: dict[str, Job] = {}
    for raw in jobs:
        key = dedup_key(raw)
        candidate = Job(**raw.model_dump(), key=key, first_seen=now)
        existing = best.get(key)
        if existing is None:
            best[key] = candidate
            continue
        if priority_of(candidate.source) > priority_of(existing.source):
            candidate.alt_urls = [*existing.alt_urls, existing.url]
            best[key] = candidate
        else:
            existing.alt_urls.append(candidate.url)
    return list(best.values())
```

- [ ] **Step 4: Uruchom testy**

Run: `.venv/Scripts/pytest tests/test_deduper.py -v`
Expected: PASS, 9 testów

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/deduper.py tests/test_deduper.py
git commit -m "feat: deduplikacja ofert między źródłami"
```

---

### Task 6: Store — stan w jobs.jsonl

**Files:**
- Create: `src/scrapper/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `Job` z Task 2
- Produces:
  - `load_seen(path: Path) -> set[str]`
  - `select_new(jobs: list[Job], seen: set[str]) -> list[Job]`
  - `append(path: Path, jobs: list[Job]) -> None`

Plik nie musi istnieć przy pierwszym uruchomieniu — wtedy zbiór widzianych jest
pusty. `append` tworzy katalog nadrzędny, jeśli trzeba, i zapisuje po jednej
ofercie na linię w UTF-8 z `\n` (nie `\r\n`, żeby diffy były czyste niezależnie
od systemu).

- [ ] **Step 1: Napisz test**

`tests/test_store.py`:

```python
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
```

- [ ] **Step 2: Uruchom test, potwierdź porażkę**

Run: `.venv/Scripts/pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapper.store'`

- [ ] **Step 3: Zaimplementuj**

`src/scrapper/store.py`:

```python
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
```

- [ ] **Step 4: Uruchom testy**

Run: `.venv/Scripts/pytest tests/test_store.py -v`
Expected: PASS, 6 testów

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/store.py tests/test_store.py
git commit -m "feat: stan ofert w append-only jobs.jsonl"
```

---

### Task 7: Protokół źródła i klient HTTP

**Files:**
- Create: `src/scrapper/sources/__init__.py`, `src/scrapper/sources/base.py`
- Test: `tests/test_sources_base.py`

**Interfaces:**
- Consumes: `RawJob` z Task 2
- Produces:
  - `class Source(Protocol)` z `name: str` i `fetch(client: httpx.Client) -> list[RawJob]`
  - `SourceResult(name: str, jobs: list[RawJob], error: str | None)`
  - `collect(sources: list[Source], client: httpx.Client) -> list[SourceResult]`
  - `build_client(timeout: float = 20.0) -> httpx.Client`
  - `AllSourcesFailed(RuntimeError)`

`collect` to serce odporności systemu: łapie każdy wyjątek pojedynczego źródła i
zamienia go na `SourceResult` z ustawionym `error`, żeby przebieg trwał dalej.
Wyjątkiem jest sytuacja, w której **wszystkie** źródła padły — wtedy `collect`
rzuca `AllSourcesFailed`, bo to nie jest częściowa awaria, tylko zepsuty system,
o którym musisz się dowiedzieć przez powiadomienie GitHuba o failed run.

Źródła celowo **nie przyjmują profilu**. Pobierają szeroko, a całe filtrowanie
żyje w matcherze. Dzięki temu dwa profile nie powodują dwóch identycznych
requestów do tego samego API.

- [ ] **Step 1: Napisz test**

`tests/test_sources_base.py`:

```python
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
```

Ostatni test pilnuje ważnego rozróżnienia: źródło, które zwróciło zero ofert,
zadziałało poprawnie — po prostu nic nie pasowało. To ostrzeżenie w mailu, a nie
awaria.

- [ ] **Step 2: Uruchom test, potwierdź porażkę**

Run: `.venv/Scripts/pytest tests/test_sources_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapper.sources'`

- [ ] **Step 3: Zaimplementuj**

`src/scrapper/sources/__init__.py` — pusty plik.

`src/scrapper/sources/base.py`:

```python
import logging
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from scrapper.models import Profile, RawJob

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class AllSourcesFailed(RuntimeError):
    """Żadne źródło nie odpowiedziało — system jest zepsuty, nie tylko pusty."""


class Source(Protocol):
    name: str

    def fetch(self, client: httpx.Client) -> list[RawJob]: ...


@dataclass
class SourceResult:
    name: str
    jobs: list[RawJob] = field(default_factory=list)
    error: str | None = None


def build_client(timeout: float = 20.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "pl,en;q=0.8"},
    )


def collect(sources: list[Source], client: httpx.Client) -> list[SourceResult]:
    """Odpytuje każde źródło. Awaria jednego nie przerywa pozostałych.

    Rzuca AllSourcesFailed, gdy padły wszystkie — wtedy przebieg ma się wysypać.
    """
    results = []
    for source in sources:
        try:
            results.append(SourceResult(name=source.name, jobs=source.fetch(client)))
        except Exception as exc:  # noqa: BLE001 - celowo łapiemy wszystko
            logger.warning("Źródło %s padło: %s", source.name, exc)
            results.append(SourceResult(name=source.name, error=f"{type(exc).__name__}: {exc}"))

    if results and all(result.error for result in results):
        raise AllSourcesFailed("Wszystkie źródła zwróciły błąd")
    return results
```

- [ ] **Step 4: Uruchom testy**

Run: `.venv/Scripts/pytest tests/test_sources_base.py -v`
Expected: PASS, 5 testów

- [ ] **Step 5: Commit**

```bash
git add src/scrapper/sources tests/test_sources_base.py
git commit -m "feat: protokół źródeł z izolacją awarii"
```

---

### Task 8: Zdobądź fixture JustJoinIT

**Files:**
- Create: `tests/fixtures/justjoinit.json`, `docs/sources.md`

**Interfaces:**
- Consumes: nic
- Produces: realny fixture i udokumentowany endpoint dla Task 9

To zadanie jest **researchowe, nie kodowe**. Nie zgaduj kształtu API — endpointy
JustJoinIT zmieniały się wielokrotnie i parser napisany pod wymyślony JSON nie
zadziała. Zapisz to, co serwis realnie zwraca **dzisiaj**.

- [ ] **Step 1: Ustal aktualny endpoint**

Otwórz `https://justjoin.it/job-offers/szczecin/frontend` w przeglądarce z
otwartym DevTools → zakładka Network → filtr XHR/Fetch. Przeładuj stronę.
Znajdź request zwracający JSON z listą ofert (szukaj odpowiedzi zawierającej
tytuły ofert). Zanotuj pełny URL wraz z parametrami zapytania oraz nagłówki,
które wyglądają na wymagane (często `version` albo podobny).

- [ ] **Step 2: Pobierz odpowiedź do pliku**

```bash
curl -s -H "User-Agent: Mozilla/5.0" "<URL_Z_KROKU_1>" -o tests/fixtures/justjoinit.json
```

- [ ] **Step 3: Sprawdź, że fixture zawiera oferty**

```bash
python -c "import json;d=json.load(open('tests/fixtures/justjoinit.json',encoding='utf-8'));print(type(d));print(json.dumps(d,ensure_ascii=False)[:1500])"
```

Expected: widoczne tytuły ofert i nazwy firm. Jeśli plik zawiera stronę błędu
albo challenge Cloudflare — endpoint wymaga dodatkowych nagłówków; wróć do kroku 1
i skopiuj request przez „Copy as cURL".

- [ ] **Step 4: Przytnij fixture do 3 ofert**

Zostaw w pliku maksymalnie 3 oferty. Wybierz tak, żeby pokrywały warianty:
jedna stacjonarna ze Szczecina, jedna zdalna, jedna bez podanych widełek. Duże
fixture'y są nieczytelne w diffach i spowalniają testy.

- [ ] **Step 5: Udokumentuj w `docs/sources.md`**

```markdown
# Źródła — endpointy i kształt odpowiedzi

## JustJoinIT

- Endpoint: `<URL_Z_KROKU_1>`
- Wymagane nagłówki: `<lista lub "brak">`
- Data weryfikacji: 2026-08-06
- Mapowanie pól → `RawJob`:
  | Pole w API | Pole w RawJob |
  | --- | --- |
  | `<nazwa>` | `external_id` |
  | `<nazwa>` | `title` |
  | `<nazwa>` | `company` |
  | `<nazwa>` | `city` |
  | `<nazwa>` | `remote` |
  | `<nazwa>` | `posted_at` |

Fixture: `tests/fixtures/justjoinit.json` (przycięty do 3 ofert).
```

Wypełnij nazwy pól na podstawie realnej odpowiedzi. Ta tabela jest wejściem do
Task 9 — bez niej implementer parsera zgaduje.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/justjoinit.json docs/sources.md
git commit -m "chore: fixture i dokumentacja API JustJoinIT"
```

---

### Task 9: Źródło JustJoinIT

**Files:**
- Create: `src/scrapper/sources/justjoinit.py`
- Test: `tests/test_justjoinit.py`
- Read: `docs/sources.md` (mapowanie pól z Task 8), `tests/fixtures/justjoinit.json`

**Interfaces:**
- Consumes: `RawJob` z Task 2, `Source` z Task 7
- Produces:
  - `class JustJoinIt` z `name = "justjoinit"` i `fetch(client) -> list[RawJob]`
  - `parse(payload: dict | list) -> list[RawJob]` — czysta funkcja, testowalna bez sieci

Rozdzielenie `fetch` (sieć) od `parse` (transformacja) jest celowe: cała logika
mapowania jest testowana na fixture, bez ani jednego requestu.

- [ ] **Step 1: Napisz test**

`tests/test_justjoinit.py`:

```python
import json
from pathlib import Path

from scrapper.sources.justjoinit import JustJoinIt, parse

FIXTURE = Path(__file__).parent / "fixtures" / "justjoinit.json"


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_returns_jobs():
    jobs = parse(_payload())

    assert len(jobs) >= 1


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
```

Uwaga dla implementera: jeśli fixture ma inny kształt korzenia niż `{"data": [...]}`,
dostosuj `test_parse_handles_empty_payload` do realnego kształtu z `docs/sources.md`.

- [ ] **Step 2: Uruchom test, potwierdź porażkę**

Run: `.venv/Scripts/pytest tests/test_justjoinit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapper.sources.justjoinit'`

- [ ] **Step 3: Zaimplementuj**

`src/scrapper/sources/justjoinit.py` — poniższy szkielet zakłada odpowiedź
`{"data": [...]}` z polami `slug`, `title`, `companyName`, `city`,
`workplaceType`, `publishedAt`, `employmentTypes`. **Skoryguj nazwy pól zgodnie z
tabelą z `docs/sources.md`** — reszta struktury zostaje bez zmian.

```python
from datetime import datetime

import httpx

from scrapper.models import RawJob
from scrapper.sources.base import Source  # noqa: F401 - dokumentuje implementowany protokół

API_URL = "https://api.justjoin.it/v2/user-panel/offers"
OFFER_URL = "https://justjoin.it/offers/{slug}"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _salary(entry: dict) -> str | None:
    types = entry.get("employmentTypes") or []
    for item in types:
        low, high, currency = item.get("from"), item.get("to"), item.get("currency")
        if low and high:
            return f"{low} - {high} {(currency or '').upper()}".strip()
    return None


def parse(payload: dict | list) -> list[RawJob]:
    entries = payload.get("data", []) if isinstance(payload, dict) else payload
    jobs = []
    for entry in entries:
        slug = entry.get("slug")
        if not slug:
            continue
        jobs.append(
            RawJob(
                source="justjoinit",
                external_id=slug,
                title=entry.get("title", ""),
                company=entry.get("companyName", ""),
                city=entry.get("city"),
                remote=(entry.get("workplaceType") == "remote"),
                url=OFFER_URL.format(slug=slug),
                salary=_salary(entry),
                posted_at=_parse_datetime(entry.get("publishedAt")),
            )
        )
    return jobs


class JustJoinIt:
    name = "justjoinit"

    def fetch(self, client: httpx.Client) -> list[RawJob]:
        response = client.get(API_URL, params={"perPage": 100, "sortBy": "published"})
        response.raise_for_status()
        return parse(response.json())
```

Filtrowanie po mieście i słowach kluczowych świadomie zostawiamy matcherowi.
Źródło pobiera szeroko, a jedna reguła filtrowania żyje w jednym miejscu.

- [ ] **Step 4: Uruchom testy**

Run: `.venv/Scripts/pytest tests/test_justjoinit.py -v`
Expected: PASS, 4 testy

- [ ] **Step 5: Zweryfikuj na żywo**

```bash
.venv/Scripts/python -c "from scrapper.sources.base import build_client; from scrapper.sources.justjoinit import JustJoinIt; c=build_client(); jobs=JustJoinIt().fetch(c); print(len(jobs)); print(jobs[0] if jobs else 'BRAK')"
```

Expected: liczba > 0 i wypisana sensowna oferta. Jeśli 0 albo wyjątek HTTP —
endpoint z Task 8 jest nieaktualny lub wymaga nagłówków; popraw `API_URL` i
`fetch`, zaktualizuj `docs/sources.md`.

- [ ] **Step 6: Commit**

```bash
git add src/scrapper/sources/justjoinit.py tests/test_justjoinit.py docs/sources.md
git commit -m "feat: źródło JustJoinIT"
```

---

### Task 10: Notifier — render i wysyłka maila

**Files:**
- Create: `src/scrapper/notifier.py`, `templates/email.html.j2`
- Test: `tests/test_notifier.py`

**Interfaces:**
- Consumes: `Job`, `SmtpConfig` z Task 2, `SourceResult` z Task 7
- Produces:
  - `render(jobs: list[Job], warnings: list[str]) -> str`
  - `subject_for(jobs: list[Job]) -> str`
  - `send(smtp: SmtpConfig, subject: str, html: str, sender=smtplib.SMTP) -> None`
  - `warnings_from(results: list[SourceResult]) -> list[str]`

`send` przyjmuje klasę SMTP jako parametr, żeby test mógł wstrzyknąć atrapę i
sprawdzić wysyłkę bez sieci i bez konta pocztowego.

- [ ] **Step 1: Napisz test**

`tests/test_notifier.py`:

```python
from datetime import datetime, timezone

from scrapper.models import Job, SmtpConfig
from scrapper.notifier import render, send, subject_for, warnings_from
from scrapper.sources.base import SourceResult

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)

SMTP = SmtpConfig(host="smtp.example.com", port=587, user="me@example.com",
                  password="sekret", to="olosolo16@gmail.com")


def _job(**overrides) -> Job:
    data = {
        "source": "justjoinit", "external_id": "1", "title": "Frontend Developer",
        "company": "Acme", "city": "Szczecin", "remote": False,
        "url": "https://justjoin.it/1", "salary": "12 000 - 16 000 PLN",
        "key": "acme|frontend-developer|szczecin", "first_seen": NOW,
    }
    data.update(overrides)
    return Job(**data)


class FakeSMTP:
    instances = []

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.started_tls = False
        self.logged_in_as = None
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in_as = user

    def send_message(self, message):
        self.sent.append(message)


def test_render_includes_title_company_and_link():
    html = render([_job()], warnings=[])

    assert "Frontend Developer" in html
    assert "Acme" in html
    assert "https://justjoin.it/1" in html


def test_render_shows_salary_when_present():
    assert "12 000 - 16 000 PLN" in render([_job()], warnings=[])


def test_render_handles_missing_salary():
    html = render([_job(salary=None)], warnings=[])

    assert "Frontend Developer" in html
    assert "None" not in html


def test_render_includes_alt_urls():
    html = render([_job(alt_urls=["https://nofluffjobs.com/1"])], warnings=[])

    assert "https://nofluffjobs.com/1" in html


def test_render_includes_warnings():
    html = render([_job()], warnings=["JustJoinIT zwrócił 0 ofert"])

    assert "JustJoinIT zwrócił 0 ofert" in html


def test_subject_reports_count():
    assert "2" in subject_for([_job(), _job(key="inny")])


def test_warnings_from_flags_zero_results():
    results = [SourceResult(name="justjoinit", jobs=[])]

    assert any("justjoinit" in w and "0" in w for w in warnings_from(results))


def test_warnings_from_flags_errors():
    results = [SourceResult(name="nofluffjobs", error="Timeout")]

    assert any("nofluffjobs" in w and "Timeout" in w for w in warnings_from(results))


def test_warnings_from_silent_on_healthy_source():
    results = [SourceResult(name="justjoinit", jobs=[_job()])]

    assert warnings_from(results) == []


def test_send_uses_tls_login_and_sends(monkeypatch):
    FakeSMTP.instances.clear()

    send(SMTP, subject="Temat", html="<p>cześć</p>", sender=FakeSMTP)

    smtp = FakeSMTP.instances[0]
    assert smtp.host == "smtp.example.com"
    assert smtp.started_tls is True
    assert smtp.logged_in_as == "me@example.com"
    assert len(smtp.sent) == 1
    assert smtp.sent[0]["To"] == "olosolo16@gmail.com"
    assert smtp.sent[0]["Subject"] == "Temat"
```

- [ ] **Step 2: Uruchom test, potwierdź porażkę**

Run: `.venv/Scripts/pytest tests/test_notifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapper.notifier'`

- [ ] **Step 3: Utwórz szablon**

`templates/email.html.j2`:

```jinja
<html>
  <body style="font-family: -apple-system, Segoe UI, sans-serif; color: #1a1a1a;">
    <h2 style="margin-bottom: 4px;">Nowe oferty: {{ jobs|length }}</h2>
    {% for job in jobs %}
      <div style="border: 1px solid #e3e3e3; border-radius: 8px; padding: 12px; margin: 12px 0;">
        <a href="{{ job.url }}" style="font-size: 16px; font-weight: 600; color: #0b5cd5; text-decoration: none;">
          {{ job.title }}
        </a>
        <div style="margin-top: 4px; color: #555;">
          {{ job.company }}
          &middot; {% if job.remote %}zdalnie{% else %}{{ job.city or "brak lokalizacji" }}{% endif %}
          {% if job.salary %}&middot; {{ job.salary }}{% endif %}
        </div>
        <div style="margin-top: 4px; font-size: 12px; color: #888;">
          źródło: {{ job.source }}
          {% for alt in job.alt_urls %}
            &middot; <a href="{{ alt }}" style="color: #888;">także tutaj</a>
          {% endfor %}
        </div>
      </div>
    {% endfor %}
    {% if warnings %}
      <div style="margin-top: 20px; padding: 10px; background: #fff6e5; border-radius: 8px; font-size: 13px;">
        <strong>Ostrzeżenia:</strong>
        <ul style="margin: 6px 0 0 16px; padding: 0;">
          {% for warning in warnings %}<li>{{ warning }}</li>{% endfor %}
        </ul>
      </div>
    {% endif %}
  </body>
</html>
```

- [ ] **Step 4: Zaimplementuj notifier**

`src/scrapper/notifier.py`:

```python
import smtplib
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scrapper.models import Job, SmtpConfig
from scrapper.sources.base import SourceResult

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates"


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
    )


def render(jobs: list[Job], warnings: list[str]) -> str:
    template = _environment().get_template("email.html.j2")
    return template.render(jobs=jobs, warnings=warnings)


def subject_for(jobs: list[Job]) -> str:
    return f"[praca] {len(jobs)} nowych ofert"


def warnings_from(results: list[SourceResult]) -> list[str]:
    warnings = []
    for result in results:
        if result.error:
            warnings.append(f"Źródło {result.name} padło: {result.error}")
        elif not result.jobs:
            warnings.append(f"Źródło {result.name} zwróciło 0 ofert — sprawdź parser")
    return warnings


def send(smtp: SmtpConfig, subject: str, html: str, sender=smtplib.SMTP) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp.user
    message["To"] = smtp.to
    message.set_content("Ta wiadomość wymaga klienta obsługującego HTML.")
    message.add_alternative(html, subtype="html")

    with sender(smtp.host, smtp.port) as server:
        server.starttls()
        server.login(smtp.user, smtp.password)
        server.send_message(message)
```

- [ ] **Step 5: Uruchom testy**

Run: `.venv/Scripts/pytest tests/test_notifier.py -v`
Expected: PASS, 10 testów

- [ ] **Step 6: Commit**

```bash
git add src/scrapper/notifier.py templates/email.html.j2 tests/test_notifier.py
git commit -m "feat: render i wysyłka powiadomienia mailowego"
```

---

### Task 11: Orkiestracja przebiegu

**Files:**
- Create: `src/scrapper/run.py`
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: wszystko z Task 2–10
- Produces:
  - `run(config: Config, sources: list[Source], store_path: Path, client, now, sender) -> int` — zwraca liczbę wysłanych ofert
  - `main() -> None` — punkt wejścia CLI

Źródła są odpytywane **raz na przebieg**, nie raz na profil — dwa profile nie
mogą oznaczać dwóch identycznych requestów do tego samego API. Dopiero pobrane
oferty przepuszczamy przez każdy profil osobno.

Kolejność jest krytyczna: **najpierw wysyłka, dopiero potem zapis stanu.** Gdy
SMTP padnie, wyjątek propaguje w górę, `append` się nie wykonuje i te same oferty
zostaną zgłoszone w kolejnym przebiegu. Nic nie ginie.

Gdy nowych ofert nie ma, mail nie leci — cisza oznacza brak nowości.

- [ ] **Step 1: Napisz test**

`tests/test_run.py`:

```python
from datetime import datetime, timezone

import pytest

from scrapper.models import Config, Profile, RawJob, SmtpConfig
from scrapper.run import run
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

    def starttls(self):
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
```

- [ ] **Step 2: Uruchom test, potwierdź porażkę**

Run: `.venv/Scripts/pytest tests/test_run.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapper.run'`

- [ ] **Step 3: Zaimplementuj**

`src/scrapper/run.py`:

```python
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
```

- [ ] **Step 4: Uruchom testy**

Run: `.venv/Scripts/pytest tests/test_run.py -v`
Expected: PASS, 7 testów

- [ ] **Step 5: Uruchom cały zestaw**

Run: `.venv/Scripts/pytest -v`
Expected: PASS, wszystkie testy z Task 1–11

- [ ] **Step 6: Commit**

```bash
git add src/scrapper/run.py tests/test_run.py
git commit -m "feat: orkiestracja przebiegu z zapisem stanu po wysyłce"
```

---

### Task 12: GitHub Actions i README

**Files:**
- Create: `.github/workflows/scrape.yml`, `.github/workflows/tests.yml`, `README.md`

**Interfaces:**
- Consumes: `scrapper.run:main` z Task 11
- Produces: działający cron; po tym zadaniu system pracuje samodzielnie

- [ ] **Step 1: Utwórz workflow testów**

`.github/workflows/tests.yml`:

```yaml
name: tests

on:
  push:
  pull_request:

jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: pytest -v
```

- [ ] **Step 2: Utwórz workflow scrapowania**

`.github/workflows/scrape.yml`:

```yaml
name: scrape

on:
  schedule:
    - cron: "7 * * * *"      # co godzinę; nierówna minuta = mniejsza kolejka u GitHuba
  workflow_dispatch:          # ręczne uruchomienie z zakładki Actions

concurrency:
  group: scrape
  cancel-in-progress: false

permissions:
  contents: write             # potrzebne do commitowania data/jobs.jsonl

jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e .

      - name: Uruchom scraper
        env:
          SMTP_USER: ${{ secrets.SMTP_USER }}
          SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
        run: python -m scrapper.run

      - name: Zapisz stan
        run: |
          if [[ -n "$(git status --porcelain data/)" ]]; then
            git config user.name "github-actions[bot]"
            git config user.email "github-actions[bot]@users.noreply.github.com"
            git add data/
            git commit -m "chore: aktualizacja stanu ofert [skip ci]"
            git pull --rebase --autostash
            git push
          else
            echo "Brak zmian w stanie."
          fi
```

`concurrency` blokuje równoległe przebiegi — dwa naraz zrobiłyby konflikt przy
pushu stanu. `git pull --rebase` przed pushem chroni przed odrzuceniem, gdyby w
międzyczasie coś trafiło na gałąź.

- [ ] **Step 3: Napisz README**

`README.md`:

```markdown
# work-scrapper

Agreguje oferty pracy z portali i stron firm, wysyła mailem tylko nowe.

## Jak działa

Co godzinę GitHub Actions uruchamia `python -m scrapper.run`. Skrypt pobiera
oferty ze skonfigurowanych źródeł, filtruje wg profili z `config.yaml`,
deduplikuje, porównuje z `data/jobs.jsonl` i wysyła maila wyłącznie o nowych
znaleziskach. Stan zapisuje dopiero po udanej wysyłce, więc awaria poczty nie
powoduje przegapienia ofert.

## Konfiguracja

1. Ustaw sekrety w repo: **Settings → Secrets and variables → Actions**
   - `SMTP_USER` — Twój adres Gmail
   - `SMTP_PASSWORD` — hasło aplikacji (nie hasło do konta!), wygenerowane na
     https://myaccount.google.com/apppasswords przy włączonym 2FA
2. Dostosuj `config.yaml` — słowa kluczowe, miasta, wykluczenia.
3. Dostosuj `companies.yaml` — lista firm do sprawdzania stron karier.

## Uruchomienie lokalne

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/pytest
SMTP_USER=... SMTP_PASSWORD=... .venv/Scripts/python -m scrapper.run
```

## Pierwszy przebieg

Pierwszy przebieg zgłosi wszystkie pasujące oferty z ostatnich `max_age_days`
dni naraz — to normalne. Kolejne będą już tylko przyrostowe.

## Gdy przestaną przychodzić oferty

Sprawdź stopkę ostatniego maila — ostrzeżenie „zwróciło 0 ofert" oznacza, że
portal zmienił format odpowiedzi. Odśwież fixture wg `docs/sources.md` i popraw
parser.
```

- [ ] **Step 4: Zweryfikuj lokalnie pełny przebieg**

```bash
SMTP_USER=<twój-gmail> SMTP_PASSWORD=<hasło-aplikacji> .venv/Scripts/python -m scrapper.run
```

Expected: w skrzynce ląduje mail z ofertami, a `data/jobs.jsonl` zawiera tyle
linii, ile ofert było w mailu. **To pierwszy realny dowód, że system działa
end-to-end.** Jeśli mail nie dotarł: sprawdź spam, potem czy `SMTP_PASSWORD` to
hasło aplikacji, a nie hasło do konta.

- [ ] **Step 5: Commit i push**

```bash
git add .github README.md data/jobs.jsonl
git commit -m "feat: cron w GitHub Actions i dokumentacja uruchomienia"
```

- [ ] **Step 6: Uruchom workflow ręcznie**

Wypchnij repo na GitHub, ustaw sekrety wg README, wejdź w **Actions → scrape →
Run workflow**. Expected: workflow zielony, a jeśli pojawiły się nowe oferty —
nowy commit `chore: aktualizacja stanu ofert`.

---

# Faza 2 — drugie źródło

---

### Task 13: Fixture i źródło NoFluffJobs

**Files:**
- Create: `tests/fixtures/nofluffjobs.json`, `src/scrapper/sources/nofluffjobs.py`
- Modify: `src/scrapper/run.py` (lista źródeł w `main`), `docs/sources.md`
- Test: `tests/test_nofluffjobs.py`

**Interfaces:**
- Consumes: `RawJob` z Task 2, `Source` z Task 7
- Produces: `class NoFluffJobs` z `name = "nofluffjobs"` i `fetch(client) -> list[RawJob]`,
  `parse(payload) -> list[RawJob]`

- [ ] **Step 1: Zdobądź fixture**

Tak samo jak w Task 8, ale dla `https://nofluffjobs.com/pl/frontend?criteria=city%3Dszczecin`.
W DevTools → Network → XHR znajdź request zwracający listę ofert (NoFluffJobs
używa zapytania POST do endpointu wyszukiwania — jeśli tak jest nadal, zanotuj
też **body requestu**, bo bez niego nie odtworzysz zapytania).

```bash
curl -s -H "User-Agent: Mozilla/5.0" "<URL>" -o tests/fixtures/nofluffjobs.json
```

Przytnij do 3 ofert i dopisz sekcję „NoFluffJobs" w `docs/sources.md` w tym samym
formacie co JustJoinIT — z tabelą mapowania pól i datą weryfikacji.

- [ ] **Step 2: Napisz test**

`tests/test_nofluffjobs.py`:

```python
import json
from pathlib import Path

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
```

- [ ] **Step 3: Uruchom test, potwierdź porażkę**

Run: `.venv/Scripts/pytest tests/test_nofluffjobs.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Zaimplementuj**

`src/scrapper/sources/nofluffjobs.py` — szkielet zakłada `{"postings": [...]}` z
polami `id`, `url`, `title`, `name`, `location`, `salary`, `posted`. **Skoryguj
nazwy pól wg tabeli z `docs/sources.md`.**

```python
from datetime import datetime, timezone

import httpx

from scrapper.models import RawJob

API_URL = "https://nofluffjobs.com/api/search/posting"
OFFER_URL = "https://nofluffjobs.com/pl/job/{url}"


def _location(entry: dict) -> tuple[str | None, bool]:
    location = entry.get("location") or {}
    places = location.get("places") or []
    remote = bool(location.get("fullyRemote")) or any(p.get("city") == "Zdalnie" for p in places)
    city = next((p.get("city") for p in places if p.get("city")), None)
    return city, remote


def _salary(entry: dict) -> str | None:
    salary = entry.get("salary") or {}
    low, high, currency = salary.get("from"), salary.get("to"), salary.get("currency")
    if low and high:
        return f"{low} - {high} {(currency or '').upper()}".strip()
    return None


def _posted_at(entry: dict) -> datetime | None:
    value = entry.get("posted")
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def parse(payload: dict | list) -> list[RawJob]:
    entries = payload.get("postings", []) if isinstance(payload, dict) else payload
    jobs = []
    for entry in entries:
        slug = entry.get("url") or entry.get("id")
        if not slug:
            continue
        city, remote = _location(entry)
        jobs.append(
            RawJob(
                source="nofluffjobs",
                external_id=str(entry.get("id") or slug),
                title=entry.get("title", ""),
                company=entry.get("name", ""),
                city=city,
                remote=remote,
                url=OFFER_URL.format(url=slug),
                salary=_salary(entry),
                posted_at=_posted_at(entry),
            )
        )
    return jobs


class NoFluffJobs:
    name = "nofluffjobs"

    def fetch(self, client: httpx.Client) -> list[RawJob]:
        response = client.post(API_URL, json={"criteriaSearch": {}}, params={"limit": 100})
        response.raise_for_status()
        return parse(response.json())
```

- [ ] **Step 5: Uruchom testy**

Run: `.venv/Scripts/pytest tests/test_nofluffjobs.py -v`
Expected: PASS, 4 testy

- [ ] **Step 6: Podłącz do przebiegu**

W `src/scrapper/run.py` zmień import i listę źródeł w `main`:

```python
from scrapper.sources.nofluffjobs import NoFluffJobs
```

```python
        count = run(config, [JustJoinIt(), NoFluffJobs()], STORE_PATH, client,
                    datetime.now(timezone.utc))
```

- [ ] **Step 7: Zweryfikuj na żywo i uruchom cały zestaw**

```bash
.venv/Scripts/python -c "from scrapper.sources.base import build_client; from scrapper.sources.nofluffjobs import NoFluffJobs; c=build_client(); jobs=NoFluffJobs().fetch(c); print(len(jobs))"
.venv/Scripts/pytest -v
```

Expected: liczba > 0, wszystkie testy zielone.

- [ ] **Step 8: Commit**

```bash
git add src/scrapper/sources/nofluffjobs.py tests/test_nofluffjobs.py tests/fixtures/nofluffjobs.json src/scrapper/run.py docs/sources.md
git commit -m "feat: źródło NoFluffJobs"
```

---

# Faza 3 — oferty ze stron firm

---

### Task 14: Rejestr firm i parser Recruitee

**Files:**
- Create: `src/scrapper/sources/ats/__init__.py`, `src/scrapper/sources/ats/recruitee.py`, `src/scrapper/sources/companies.py`, `companies.yaml`, `tests/fixtures/recruitee.json`
- Test: `tests/test_recruitee.py`, `tests/test_companies.py`

**Interfaces:**
- Consumes: `RawJob` z Task 2, `Source` z Task 7
- Produces:
  - `parse_recruitee(payload: dict, company: str, slug: str) -> list[RawJob]`
  - `fetch_recruitee(entry: CompanyEntry, client) -> list[RawJob]`
  - `CompanyEntry(name: str, ats: str, slug: str | None, url: str | None, parser: str | None)`
  - `load_companies(path: Path) -> list[CompanyEntry]`
  - `class CompaniesSource` z `name = "companies"` i `fetch(client) -> list[RawJob]` —
    jedno źródło obsługujące wszystkie firmy

`CompaniesSource` łapie wyjątki **per firma**: padnięta strona jednej firmy nie
może zabrać ze sobą pozostałych pięćdziesięciu.

Wszystkie oferty firmowe mają `source = f"company:{slug}"`, dzięki czemu
`priority_of` z Task 5 przyzna im najwyższy priorytet w deduplikacji.

- [ ] **Step 1: Zdobądź fixture Recruitee**

Recruitee wystawia publiczny endpoint per firma:
`https://<slug>.recruitee.com/api/offers/`. Znajdź firmę ze Szczecina, która go
używa (sprawdź stronę karier — jeśli adres oferty zawiera `recruitee.com`, to ta).

```bash
curl -s "https://<slug>.recruitee.com/api/offers/" -o tests/fixtures/recruitee.json
python -c "import json;d=json.load(open('tests/fixtures/recruitee.json',encoding='utf-8'));print(len(d.get('offers',[])));print(json.dumps(d['offers'][0],ensure_ascii=False)[:800])"
```

Expected: liczba ofert > 0 i widoczne pola `title`, `city`, `careers_url`.
Przytnij do 2–3 ofert. Dopisz sekcję „Recruitee" w `docs/sources.md`.

- [ ] **Step 2: Napisz test parsera**

`tests/test_recruitee.py`:

```python
import json
from pathlib import Path

from scrapper.sources.ats.recruitee import parse_recruitee

FIXTURE = Path(__file__).parent / "fixtures" / "recruitee.json"


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_returns_jobs():
    assert len(parse_recruitee(_payload(), company="Acme", slug="acme")) >= 1


def test_source_is_prefixed_with_company():
    jobs = parse_recruitee(_payload(), company="Acme", slug="acme")

    assert all(job.source == "company:acme" for job in jobs)


def test_company_name_comes_from_registry_not_payload():
    jobs = parse_recruitee(_payload(), company="Acme", slug="acme")

    assert all(job.company == "Acme" for job in jobs)


def test_parse_handles_empty_payload():
    assert parse_recruitee({"offers": []}, company="Acme", slug="acme") == []
```

- [ ] **Step 3: Uruchom test, potwierdź porażkę**

Run: `.venv/Scripts/pytest tests/test_recruitee.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Zaimplementuj parser**

`src/scrapper/sources/ats/__init__.py` — pusty plik.

`src/scrapper/sources/ats/recruitee.py`:

```python
from datetime import datetime

import httpx

from scrapper.models import RawJob

API_URL = "https://{slug}.recruitee.com/api/offers/"

REMOTE_MARKERS = ("remote", "zdalnie", "zdalna")


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_recruitee(payload: dict, company: str, slug: str) -> list[RawJob]:
    jobs = []
    for offer in payload.get("offers", []):
        url = offer.get("careers_url") or offer.get("careers_apply_url")
        if not url:
            continue
        city = offer.get("city")
        location_text = " ".join(filter(None, [city, offer.get("country"), offer.get("location")]))
        jobs.append(
            RawJob(
                source=f"company:{slug}",
                external_id=str(offer.get("id") or url),
                title=offer.get("title", ""),
                company=company,
                city=city,
                remote=any(marker in location_text.casefold() for marker in REMOTE_MARKERS),
                url=url,
                salary=None,
                posted_at=_parse_datetime(offer.get("published_at")),
            )
        )
    return jobs


def fetch_recruitee(entry, client: httpx.Client) -> list[RawJob]:
    response = client.get(API_URL.format(slug=entry.slug))
    response.raise_for_status()
    return parse_recruitee(response.json(), company=entry.name, slug=entry.slug)
```

- [ ] **Step 5: Uruchom testy parsera**

Run: `.venv/Scripts/pytest tests/test_recruitee.py -v`
Expected: PASS, 4 testy

- [ ] **Step 6: Napisz test rejestru firm**

`tests/test_companies.py`:

```python
from scrapper.models import RawJob
from scrapper.sources.companies import CompaniesSource, CompanyEntry, load_companies

COMPANIES_YAML = """
- name: Acme
  ats: recruitee
  slug: acme
- name: Beta
  ats: recruitee
  slug: beta
- name: Gamma
  ats: custom
  url: https://gamma.example.com/kariera
  parser: skip
"""


def _job(slug: str) -> RawJob:
    return RawJob(source=f"company:{slug}", external_id="1", title="React Dev",
                  company=slug, url=f"https://{slug}.example.com/1")


def test_load_companies_parses_entries(tmp_path):
    path = tmp_path / "companies.yaml"
    path.write_text(COMPANIES_YAML, encoding="utf-8")

    entries = load_companies(path)

    assert [e.name for e in entries] == ["Acme", "Beta", "Gamma"]
    assert entries[0].ats == "recruitee"


def test_fetches_all_supported_companies():
    entries = [CompanyEntry(name="Acme", ats="recruitee", slug="acme"),
               CompanyEntry(name="Beta", ats="recruitee", slug="beta")]
    fetchers = {"recruitee": lambda entry, client: [_job(entry.slug)]}

    jobs = CompaniesSource(entries, fetchers=fetchers).fetch(client=None)

    assert {job.source for job in jobs} == {"company:acme", "company:beta"}


def test_one_failing_company_does_not_stop_others():
    entries = [CompanyEntry(name="Acme", ats="recruitee", slug="acme"),
               CompanyEntry(name="Beta", ats="recruitee", slug="beta")]

    def fetcher(entry, client):
        if entry.slug == "acme":
            raise RuntimeError("500")
        return [_job(entry.slug)]

    jobs = CompaniesSource(entries, fetchers={"recruitee": fetcher}).fetch(client=None)

    assert [job.source for job in jobs] == ["company:beta"]


def test_entries_with_parser_skip_are_ignored():
    entries = [CompanyEntry(name="Gamma", ats="custom", url="https://x", parser="skip")]

    jobs = CompaniesSource(entries, fetchers={}).fetch(client=None)

    assert jobs == []


def test_unknown_ats_is_ignored_not_fatal():
    entries = [CompanyEntry(name="Delta", ats="nieznany-system", slug="delta")]

    jobs = CompaniesSource(entries, fetchers={}).fetch(client=None)

    assert jobs == []


def test_source_name():
    assert CompaniesSource([], fetchers={}).name == "companies"
```

- [ ] **Step 7: Uruchom test, potwierdź porażkę**

Run: `.venv/Scripts/pytest tests/test_companies.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapper.sources.companies'`

- [ ] **Step 8: Zaimplementuj rejestr**

`src/scrapper/sources/companies.py`:

```python
import logging
from pathlib import Path

import httpx
import yaml
from pydantic import BaseModel

from scrapper.models import RawJob
from scrapper.sources.ats.recruitee import fetch_recruitee

logger = logging.getLogger(__name__)


class CompanyEntry(BaseModel):
    name: str
    ats: str
    slug: str | None = None
    url: str | None = None
    parser: str | None = None


def load_companies(path: Path) -> list[CompanyEntry]:
    path = Path(path)
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [CompanyEntry(**entry) for entry in raw]


DEFAULT_FETCHERS = {"recruitee": fetch_recruitee}


class CompaniesSource:
    """Jedno źródło obejmujące wszystkie firmy z companies.yaml.

    Wyjątek jednej firmy jest logowany i pomijany — pozostałe firmy są odpytane.
    """

    name = "companies"

    def __init__(self, entries: list[CompanyEntry], fetchers: dict | None = None):
        self.entries = entries
        self.fetchers = DEFAULT_FETCHERS if fetchers is None else fetchers

    def fetch(self, client: httpx.Client) -> list[RawJob]:
        jobs: list[RawJob] = []
        for entry in self.entries:
            if entry.parser == "skip":
                logger.info("Pomijam %s (parser: skip)", entry.name)
                continue
            fetcher = self.fetchers.get(entry.ats)
            if fetcher is None:
                logger.info("Pomijam %s — brak parsera dla ATS '%s'", entry.name, entry.ats)
                continue
            try:
                jobs.extend(fetcher(entry, client))
            except Exception as exc:  # noqa: BLE001 - jedna firma nie może ubić reszty
                logger.warning("Firma %s padła: %s", entry.name, exc)
        return jobs
```

- [ ] **Step 9: Uruchom testy**

Run: `.venv/Scripts/pytest tests/test_companies.py tests/test_recruitee.py -v`
Expected: PASS, 10 testów

- [ ] **Step 10: Utwórz `companies.yaml` z realnymi firmami**

Zbuduj listę firm IT ze Szczecina i ustal ATS każdej z nich. Metoda: wejdź na
stronę karier firmy, kliknij dowolną ofertę i spójrz na domenę w adresie —
zdradza system. `*.recruitee.com` → `recruitee`, `*.traffit.com` → `traffit`,
`jobs.lever.co/*` → `lever`, `boards.greenhouse.io/*` → `greenhouse`,
`apply.workable.com/*` → `workable`. Cokolwiek innego → `ats: custom` z
`parser: skip`.

Punkt startowy do sprawdzenia (zweryfikuj każdą — firmy zmieniają systemy):
BLStream, Tieto­EVRY Szczecin, Espeo Software, SoftwareMill, Unity Group,
Netguru, Spartez/Atlassian Szczecin, Coderivium, Home.pl, Arvato Systems,
BrightCode, Solwit, Lyra Network, Cyfrowy Polsat Szczecin, Zaneta Software.

Zacznij od kilkunastu potwierdzonych wpisów — pełna lista nie jest warunkiem
działania, a dopisanie firmy to jedna linijka. Format:

```yaml
- name: BLStream
  ats: recruitee
  slug: blstream
- name: SoftwareMill
  ats: custom
  url: https://softwaremill.com/join-us/
  parser: skip
```

- [ ] **Step 11: Podłącz do przebiegu**

W `src/scrapper/run.py` dodaj obok istniejących importów i ścieżek:

```python
from scrapper.sources.companies import CompaniesSource, load_companies
```

```python
COMPANIES_PATH = ROOT / "companies.yaml"
```

i zmień listę źródeł w `main`:

```python
        sources = [JustJoinIt(), NoFluffJobs(), CompaniesSource(load_companies(COMPANIES_PATH))]
        count = run(config, sources, STORE_PATH, client, datetime.now(timezone.utc))
```

- [ ] **Step 12: Zweryfikuj na żywo i uruchom cały zestaw**

```bash
.venv/Scripts/python -c "from scrapper.sources.base import build_client; from scrapper.sources.companies import CompaniesSource, load_companies; c=build_client(); jobs=CompaniesSource(load_companies('companies.yaml')).fetch(c); print(len(jobs)); [print(j.company, '|', j.title) for j in jobs[:10]]"
.venv/Scripts/pytest -v
```

Expected: wypisane realne oferty z firm z listy; wszystkie testy zielone.

- [ ] **Step 13: Commit**

```bash
git add src/scrapper/sources/ats src/scrapper/sources/companies.py companies.yaml tests/test_recruitee.py tests/test_companies.py tests/fixtures/recruitee.json src/scrapper/run.py docs/sources.md
git commit -m "feat: oferty ze stron firm przez Recruitee"
```

---

### Task 15: Pozostałe parsery ATS

**Files:**
- Create: `src/scrapper/sources/ats/lever.py`, `greenhouse.py`, `workable.py`, `traffit.py`
- Create: `tests/fixtures/{lever,greenhouse,workable,traffit}.json`
- Modify: `src/scrapper/sources/companies.py` (`DEFAULT_FETCHERS`), `companies.yaml`, `docs/sources.md`
- Test: `tests/test_ats_parsers.py`

**Interfaces:**
- Consumes: `CompanyEntry` z Task 14
- Produces: `parse_lever`, `fetch_lever`, `parse_greenhouse`, `fetch_greenhouse`,
  `parse_workable`, `fetch_workable`, `parse_traffit`, `fetch_traffit` — każdy o
  sygnaturze identycznej z odpowiednikiem Recruitee z Task 14

Każdy parser powstaje tym samym cyklem: fixture → test → implementacja. Lever,
Greenhouse i Workable mają udokumentowane publiczne API. Traffit bywa
niepubliczny — jeśli nie ma endpointu JSON, parsuj HTML przez `selectolax`.

Endpointy do weryfikacji (sprawdź aktualność, jak w Task 8):
- Lever: `https://api.lever.co/v0/postings/<slug>?mode=json` — lista obiektów z `text`, `hostedUrl`, `categories.location`, `createdAt` (ms).
- Greenhouse: `https://boards-api.greenhouse.io/v1/boards/<slug>/jobs` — `{"jobs": [...]}` z `title`, `absolute_url`, `location.name`, `updated_at`.
- Workable: `https://apply.workable.com/api/v1/widget/accounts/<slug>?details=true` — `{"jobs": [...]}` z `title`, `url`, `city`, `telecommuting`, `published_on`.

- [ ] **Step 1: Zdobądź cztery fixture'y**

Dla każdego systemu znajdź firmę, która go używa (metoda z Task 14, krok 10):

```bash
curl -s "https://api.lever.co/v0/postings/<slug>?mode=json" -o tests/fixtures/lever.json
curl -s "https://boards-api.greenhouse.io/v1/boards/<slug>/jobs" -o tests/fixtures/greenhouse.json
curl -s "https://apply.workable.com/api/v1/widget/accounts/<slug>?details=true" -o tests/fixtures/workable.json
```

Traffit: otwórz stronę karier firmy używającej Traffit z DevTools → Network, znajdź
request z listą ofert. Jeśli to JSON — zapisz jak wyżej. Jeśli oferty są w HTML —
zapisz stronę: `curl -s "<URL>" -o tests/fixtures/traffit.html` i w teście
parsuj przez `selectolax`.

Każdy fixture przytnij do 2–3 ofert. Dopisz sekcje w `docs/sources.md`.

- [ ] **Step 2: Napisz testy**

`tests/test_ats_parsers.py`:

```python
import json
from pathlib import Path

import pytest

from scrapper.sources.ats.greenhouse import parse_greenhouse
from scrapper.sources.ats.lever import parse_lever
from scrapper.sources.ats.workable import parse_workable

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


PARSERS = [
    (parse_lever, "lever.json"),
    (parse_greenhouse, "greenhouse.json"),
    (parse_workable, "workable.json"),
]


@pytest.mark.parametrize("parser,fixture", PARSERS)
def test_parser_returns_jobs(parser, fixture):
    assert len(parser(_load(fixture), company="Acme", slug="acme")) >= 1


@pytest.mark.parametrize("parser,fixture", PARSERS)
def test_parsed_jobs_have_required_fields(parser, fixture):
    for job in parser(_load(fixture), company="Acme", slug="acme"):
        assert job.source == "company:acme"
        assert job.company == "Acme"
        assert job.title
        assert job.url.startswith("https://")
        assert job.external_id


def test_lever_handles_empty_payload():
    assert parse_lever([], company="Acme", slug="acme") == []


def test_greenhouse_handles_empty_payload():
    assert parse_greenhouse({"jobs": []}, company="Acme", slug="acme") == []


def test_workable_handles_empty_payload():
    assert parse_workable({"jobs": []}, company="Acme", slug="acme") == []
```

Dla Traffit dopisz analogiczne testy po ustaleniu w kroku 1, czy źródłem jest
JSON czy HTML — kształt testu zależy od tego, co realnie zwraca serwis.

- [ ] **Step 3: Uruchom testy, potwierdź porażkę**

Run: `.venv/Scripts/pytest tests/test_ats_parsers.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Zaimplementuj Lever**

`src/scrapper/sources/ats/lever.py`:

```python
from datetime import datetime, timezone

import httpx

from scrapper.models import RawJob

API_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"
REMOTE_MARKERS = ("remote", "zdalnie")


def parse_lever(payload: list | dict, company: str, slug: str) -> list[RawJob]:
    entries = payload if isinstance(payload, list) else payload.get("data", [])
    jobs = []
    for entry in entries:
        url = entry.get("hostedUrl")
        if not url:
            continue
        location = (entry.get("categories") or {}).get("location") or ""
        created = entry.get("createdAt")
        posted_at = (
            datetime.fromtimestamp(created / 1000, tz=timezone.utc)
            if isinstance(created, (int, float)) else None
        )
        jobs.append(
            RawJob(
                source=f"company:{slug}",
                external_id=str(entry.get("id") or url),
                title=entry.get("text", ""),
                company=company,
                city=location or None,
                remote=any(m in location.casefold() for m in REMOTE_MARKERS),
                url=url,
                posted_at=posted_at,
            )
        )
    return jobs


def fetch_lever(entry, client: httpx.Client) -> list[RawJob]:
    response = client.get(API_URL.format(slug=entry.slug))
    response.raise_for_status()
    return parse_lever(response.json(), company=entry.name, slug=entry.slug)
```

- [ ] **Step 5: Zaimplementuj Greenhouse**

`src/scrapper/sources/ats/greenhouse.py`:

```python
from datetime import datetime

import httpx

from scrapper.models import RawJob

API_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
REMOTE_MARKERS = ("remote", "zdalnie")


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_greenhouse(payload: dict, company: str, slug: str) -> list[RawJob]:
    jobs = []
    for entry in payload.get("jobs", []):
        url = entry.get("absolute_url")
        if not url:
            continue
        location = (entry.get("location") or {}).get("name") or ""
        jobs.append(
            RawJob(
                source=f"company:{slug}",
                external_id=str(entry.get("id") or url),
                title=entry.get("title", ""),
                company=company,
                city=location or None,
                remote=any(m in location.casefold() for m in REMOTE_MARKERS),
                url=url,
                posted_at=_parse_datetime(entry.get("updated_at")),
            )
        )
    return jobs


def fetch_greenhouse(entry, client: httpx.Client) -> list[RawJob]:
    response = client.get(API_URL.format(slug=entry.slug))
    response.raise_for_status()
    return parse_greenhouse(response.json(), company=entry.name, slug=entry.slug)
```

- [ ] **Step 6: Zaimplementuj Workable**

`src/scrapper/sources/ats/workable.py`:

```python
from datetime import datetime

import httpx

from scrapper.models import RawJob

API_URL = "https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_workable(payload: dict, company: str, slug: str) -> list[RawJob]:
    jobs = []
    for entry in payload.get("jobs", []):
        url = entry.get("url") or entry.get("application_url")
        if not url:
            continue
        jobs.append(
            RawJob(
                source=f"company:{slug}",
                external_id=str(entry.get("shortcode") or entry.get("id") or url),
                title=entry.get("title", ""),
                company=company,
                city=entry.get("city"),
                remote=bool(entry.get("telecommuting")),
                url=url,
                posted_at=_parse_datetime(entry.get("published_on")),
            )
        )
    return jobs


def fetch_workable(entry, client: httpx.Client) -> list[RawJob]:
    response = client.get(API_URL.format(slug=entry.slug))
    response.raise_for_status()
    return parse_workable(response.json(), company=entry.name, slug=entry.slug)
```

- [ ] **Step 7: Zaimplementuj Traffit**

Napisz `src/scrapper/sources/ats/traffit.py` z funkcjami `parse_traffit(payload,
company, slug)` i `fetch_traffit(entry, client)` — sygnatury identyczne z
powyższymi. Jeśli Traffit zwraca HTML zamiast JSON, `parse_traffit` przyjmuje
`str` z HTML-em i wyciąga oferty przez `selectolax`:

```python
from selectolax.parser import HTMLParser

def parse_traffit(html: str, company: str, slug: str) -> list[RawJob]:
    tree = HTMLParser(html)
    jobs = []
    for node in tree.css("<SELEKTOR_KONTENERA_OFERTY>"):
        link = node.css_first("a")
        if link is None:
            continue
        url = link.attributes.get("href", "")
        ...
    return jobs
```

Selektory ustal, oglądając zapisany fixture. Jeśli okaże się, że Traffit renderuje
oferty dopiero JavaScriptem i w HTML-u ich nie ma, oznacz go w `docs/sources.md`
jako niewspierany, a firmy używające Traffit zostaw w `companies.yaml` z
`parser: skip`. To akceptowalny wynik — nie dodawaj Playwrighta dla jednego ATS-u.

- [ ] **Step 8: Zarejestruj parsery**

W `src/scrapper/sources/companies.py`:

```python
from scrapper.sources.ats.greenhouse import fetch_greenhouse
from scrapper.sources.ats.lever import fetch_lever
from scrapper.sources.ats.recruitee import fetch_recruitee
from scrapper.sources.ats.workable import fetch_workable
```

```python
DEFAULT_FETCHERS = {
    "recruitee": fetch_recruitee,
    "lever": fetch_lever,
    "greenhouse": fetch_greenhouse,
    "workable": fetch_workable,
}
```

Dopisz `"traffit": fetch_traffit` tylko jeśli krok 7 zakończył się działającym
parserem.

- [ ] **Step 9: Uruchom cały zestaw**

Run: `.venv/Scripts/pytest -v`
Expected: PASS, wszystkie testy

- [ ] **Step 10: Uzupełnij `companies.yaml`**

Przejdź ponownie listę firm z Task 14 i przenieś z `parser: skip` do właściwego
ATS-u te, które używają Lever, Greenhouse, Workable lub Traffit.

- [ ] **Step 11: Zweryfikuj pełny przebieg na żywo**

```bash
SMTP_USER=<gmail> SMTP_PASSWORD=<hasło-aplikacji> .venv/Scripts/python -m scrapper.run
```

Expected: mail zawiera oferty z etykietą `company:*` obok ofert z portali.
Jeśli ta sama oferta występuje na portalu i stronie firmy — w mailu jest jedna
pozycja z linkiem firmowym jako głównym i portalowym w „także tutaj". To
potwierdza, że deduplikacja z Task 5 działa na realnych danych.

- [ ] **Step 12: Commit**

```bash
git add src/scrapper/sources/ats tests/test_ats_parsers.py tests/fixtures companies.yaml src/scrapper/sources/companies.py docs/sources.md
git commit -m "feat: parsery Lever, Greenhouse, Workable i Traffit"
```

---

## Definicja ukończenia

- [ ] `pytest` przechodzi w całości
- [ ] Workflow `scrape` chodzi co godzinę i kończy się zielono
- [ ] Mail z ofertami dociera na `olosolo16@gmail.com`
- [ ] Drugi przebieg pod rząd nie wysyła maila (brak nowych ofert)
- [ ] `data/jobs.jsonl` rośnie przyrostowo, commitowany przez bota
- [ ] W mailu są oferty zarówno z portali, jak i ze stron firm
