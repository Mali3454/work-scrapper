from datetime import datetime, timezone

from scrapper.matcher import matches
from scrapper.models import Profile
from scrapper.sources.companies import CompanyEntry
from scrapper.sources.company_pages import parse_company_page
from scrapper.sources.sii import parse_sii
from scrapper.sources.spyrosoft import parse_spyrosoft
from scrapper.sources.successfactors import parse_successfactors


NOW = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)


def test_parses_wordpress_company_cards_with_location():
    entry = CompanyEntry(
        name="BTC",
        ats="html",
        slug="btc",
        url="https://btc.example/jobs/",
        parser="html_cards",
        item_selector="article.job",
        title_selector="h3 a",
        location_selector=".excerpt",
    )
    html = """
    <article class="job"><h3><a href="/java-developer/">Java Developer</a></h3>
    <p class="excerpt">Form: Any, Location: Szczecin, [Ref: JD]</p></article>
    """

    jobs = parse_company_page(html, entry)

    assert len(jobs) == 1
    assert jobs[0].title == "Java Developer"
    assert jobs[0].city == "Szczecin"
    assert jobs[0].url == "https://btc.example/java-developer/"


def test_parses_simple_company_link_list():
    entry = CompanyEntry(
        name="Raynet",
        ats="html",
        slug="raynet",
        url="https://raynet.example/",
        city="Szczecin",
        parser="html_links",
        link_selector="main li a",
    )

    jobs = parse_company_page(
        '<main><ul><li><a href="/software/">Software Developer</a></li></ul></main>',
        entry,
    )

    assert [(job.title, job.city) for job in jobs] == [("Software Developer", "Szczecin")]


def test_card_can_be_its_own_link_and_keep_multicity_text():
    entry = CompanyEntry(
        name="Asseco Data Systems",
        ats="html",
        slug="assecods",
        url="https://asseco.example/",
        parser="html_cards",
        item_selector="a.job",
        title_selector=".label",
        location_selector=".location",
    )
    html = """
    <a class="job" href="/Oferta/7"><span class="label">Software Tester</span>
    <div class="location">Biuro w Szczecinie ul. Testowa 1</div></a>
    """

    job = parse_company_page(html, entry)[0]

    assert job.url == "https://asseco.example/Oferta/7"
    assert "Szczecin" in job.city


def test_parses_successfactors_tile_without_mobile_duplicates():
    entry = CompanyEntry(
        name="Demant",
        ats="successfactors",
        slug="demant",
        url="https://careers.example/go/it/",
    )
    html = """
    <div class="job-row"><div class="sub-section-desktop">
      <a class="jobTitle-link" href="/job/123/">Software Engineer</a>
      <div class="section-field date"><div id="job-date-value">4 Sept 2026</div></div>
      <div class="section-field customfield5"><div id="job-city-value">Szczecin</div></div>
    </div><div class="sub-section-tablet">
      <a class="jobTitle-link" href="/job/123/">Software Engineer</a>
    </div></div>
    """

    jobs = parse_successfactors(html, entry)

    assert len(jobs) == 1
    assert jobs[0].city == "Szczecin"
    assert jobs[0].posted_at == datetime(2026, 9, 4, tzinfo=timezone.utc)


def test_sii_keeps_szczecin_multilocation_and_marks_remote():
    payload = {
        "offers": [{
            "offerId": 42,
            "title": "Java Developer",
            "workModes": [{"name": "Remote"}],
            "locations": [{"name": "Poland", "locations": [
                {"name": "Warsaw"}, {"name": "Szczecin"}
            ]}],
            "publicationDate": "2026-09-04T12:00:00+00:00",
        }]
    }

    job = parse_sii(payload, "Sii Polska", "sii")[0]

    assert job.remote is True
    assert job.city is None
    assert job.url.endswith("/42/")


def test_spyrosoft_description_can_match_revit():
    payload = {
        "jobs": [{
            "id": "7",
            "title": "BIM Automation Specialist",
            "body": "We automate building models using the Revit API and Dynamo.",
            "remote_status": "fully",
            "loc": [{"city": "Wroclaw"}],
            "url": "https://careers.example/jobs/7",
            "skills": [],
        }]
    }
    job = parse_spyrosoft(payload, "Spyrosoft", "spyrosoft")[0]
    profile = Profile(
        name="bim",
        keywords=["revit"],
        locations=["szczecin"],
        include_remote=True,
        search_description=True,
    )

    assert job.remote is True
    assert job.city is None
    assert matches(job, profile, NOW) is True
    assert "search_text" not in job.model_dump()
