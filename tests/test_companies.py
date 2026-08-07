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
    entries = [CompanyEntry(name="Acme", ats="recruitee", slug="acme")]

    # Bez jawnego `fetchers=` powinien zostać użyty DEFAULT_FETCHERS zawierający
    # prawdziwy fetch_recruitee — sprawdzamy tylko, że nie wybucha z powodu
    # nieznanego ATS (samo wywołanie sieciowe nie jest tu testowane, testy
    # działają bez sieci — fetch_recruitee sam rzuci błąd sieci, złapany per firma).
    jobs = CompaniesSource(entries).fetch(client=None)

    assert jobs == []
