from scrapper.models import RawJob
from scrapper.sources.ats.recruitee import fetch_recruitee
from scrapper.sources.companies import (
    DEFAULT_FETCHERS,
    CompaniesSource,
    CompanyEntry,
    load_companies,
)

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


def test_load_companies_missing_file_returns_empty(tmp_path):
    assert load_companies(tmp_path / "missing.yaml") == []


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


def test_default_fetchers_include_recruitee():
    # Asercja musi być o zawartości rejestru fetcherów, a nie o wyniku fetch():
    # `jobs == []` wychodzi tak samo, gdy fetcher JEST (leci wywołanie, wywala
    # się na `client=None`, błąd łapany per firma) i gdy fetchera NIE MA (wpis
    # pominięty jako nieznany ATS). Taki test przeszedłby po zgubieniu wpisu
    # `recruitee` w refaktorze — czyli nie łapałby dokładnie tego, po co jest.
    assert DEFAULT_FETCHERS["recruitee"] is fetch_recruitee


def test_source_uses_default_fetchers_when_none_given():
    assert CompaniesSource([]).fetchers is DEFAULT_FETCHERS


def test_entry_without_slug_is_skipped_not_fetched():
    entries = [CompanyEntry(name="Acme", ats="recruitee")]  # literówka w rejestrze
    called = []

    def fetcher(entry, client):
        called.append(entry.name)
        return [_job("acme")]

    jobs = CompaniesSource(entries, fetchers={"recruitee": fetcher}).fetch(client=None)

    assert jobs == []
    assert called == []  # fetcher nie może zostać wywołany bez sluga


def test_broken_yaml_yields_empty_registry_not_crash(tmp_path):
    path = tmp_path / "companies.yaml"
    path.write_text("- name: Acme\n   ats: recruitee\n  slug: acme\n", encoding="utf-8")

    assert load_companies(path) == []


def test_yaml_that_is_not_a_list_yields_empty_registry(tmp_path):
    path = tmp_path / "companies.yaml"
    path.write_text("name: Acme\nats: recruitee\n", encoding="utf-8")

    assert load_companies(path) == []


def test_invalid_entry_is_skipped_but_rest_is_loaded(tmp_path):
    path = tmp_path / "companies.yaml"
    path.write_text(
        "- name: Acme\n  ats: recruitee\n  slug: acme\n"
        "- ats: recruitee\n  slug: bezimienna\n"  # brak wymaganego `name`
        "- name: Beta\n  ats: recruitee\n  slug: beta\n",
        encoding="utf-8",
    )

    assert [e.name for e in load_companies(path)] == ["Acme", "Beta"]
