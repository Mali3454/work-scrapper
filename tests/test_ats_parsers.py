import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from scrapper.deduper import dedup_key
from scrapper.matcher import matches
from scrapper.models import Profile
from scrapper.sources.ats.greenhouse import fetch_greenhouse, parse_greenhouse
from scrapper.sources.ats.lever import fetch_lever, parse_lever
from scrapper.sources.ats.location import extract_city
from scrapper.sources.ats.workable import fetch_workable, parse_workable
from scrapper.sources.companies import CompanyEntry

FIXTURES = Path(__file__).parent / "fixtures"


def _payload(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------

GH_PAYLOAD = "greenhouse.json"


def test_greenhouse_parse_returns_jobs():
    jobs = parse_greenhouse(_payload(GH_PAYLOAD), company="home.pl", slug="homepl")

    assert len(jobs) == 2


def test_greenhouse_stettin_is_normalized_to_szczecin():
    jobs = parse_greenhouse(_payload(GH_PAYLOAD), company="home.pl", slug="homepl")

    assert all(job.city == "Szczecin" for job in jobs)


def test_greenhouse_stettin_offer_matches_szczecin_profile_end_to_end():
    """Test regresyjny na sedno Task 15 (patrz task-15-brief.md).

    Bez normalizacji "Stettin" -> "Szczecin" w parserze, `matcher._location_ok`
    (`"szczecin" in "ul. zbożowa 4, 70-653 stettin"`) zwraca False i jedyna
    szczecińska firma z żywym ATS-em w projekcie zostaje odfiltrowana.
    """
    jobs = parse_greenhouse(_payload(GH_PAYLOAD), company="home.pl", slug="homepl")
    profile = Profile(name="frontend-szczecin", keywords=[jobs[0].title.split()[0]],
                       locations=["szczecin"], include_remote=True, max_age_days=3650)
    now = datetime(2026, 8, 7, tzinfo=timezone.utc)

    assert matches(jobs[0], profile, now)


def test_greenhouse_uses_first_published_not_updated_at():
    """`updated_at` jest identyczne dla WSZYSTKICH ofert home.pl (zbiorcze
    odświeżenie boarda), więc branie go dałoby fałszywie świeże daty. Fixture
    ma różne `first_published` dla obu ofert mimo identycznego `updated_at`.
    """
    jobs = {job.title: job for job in parse_greenhouse(_payload(GH_PAYLOAD), company="home.pl",
                                                        slug="homepl")}
    payload = _payload(GH_PAYLOAD)
    updated_at_values = {job["updated_at"] for job in payload["jobs"]}
    assert len(updated_at_values) == 1  # potwierdza założenie fixture'a

    posted_dates = {job.posted_at.date().isoformat() for job in jobs.values()}
    assert posted_dates == {"2026-04-07", "2026-06-15"}


def test_greenhouse_city_extraction_strips_street_and_postal_code():
    assert extract_city("ul. Zbożowa 4, 70-653 Stettin") == "Szczecin"


def test_greenhouse_city_extraction_handles_missing_location():
    assert extract_city(None) is None
    assert extract_city("") is None


@pytest.mark.parametrize("location_name,expected", [
    # Format home.pl (adres pocztowy + niemiecki egzonim) — miasto PO kodzie.
    ("ul. Zbożowa 4, 70-653 Stettin", "Szczecin"),
    # Najpowszechniejszy format Greenhouse — miasto PRZED krajem. Reguła
    # "weź ostatni segment" dawała tu "Poland", czyli ciche zero ofert.
    ("Szczecin, Poland", "Szczecin"),
    ("Warsaw, Poland", "Warsaw"),
    ("San Francisco, CA", "San Francisco"),
    ("London, UK", "London"),
    # Format Levera (kraj PRZED miastem) — ta sama reguła musi go ogarnąć.
    ("Portugal, Lisbon", "Lisbon"),
    ("UK, London", "London"),
    ("Estonia, Tallinn", "Tallinn"),
    # Pojedynczy segment.
    ("Kraków", "Kraków"),
    # Adres bez polskiego kodu pocztowego — miasto nie może wyjść ulicą.
    ("ul. Zbożowa 4, Szczecin", "Szczecin"),
    ("Musterstrasse 1, 10115 Berlin", "Berlin"),
    ("10115 Berlin", "Berlin"),
    ("1 Infinite Loop, Cupertino, CA", "Cupertino"),
    # Sam kod pocztowy to nie miasto.
    ("70-653", None),
    ("   ", None),
    # "Remote" to nie miasto — w obu wariantach zapisu.
    ("Remote", None),
    ("Remote - Europe", None),
    ("Remote, Poland", None),
    # Miasta-państwa i nazwy dwuznaczne NIE mogą zostać odrzucone jako kraj.
    ("Singapore", "Singapore"),
    ("Mexico", "Mexico"),
    ("Luxembourg", "Luxembourg"),
    ("Atlanta, Georgia", "Atlanta"),
])
def test_city_extraction_handles_every_observed_format(location_name, expected):
    assert extract_city(location_name) == expected


@pytest.mark.parametrize("exonym,expected", [
    ("Stettin", "Szczecin"),   # POTWIERDZONE realnymi danymi (home.pl)
    ("Warschau", "Warszawa"),  # poniższe dopisane defensywnie, niepotwierdzone
    ("Krakau", "Kraków"),
    ("Danzig", "Gdańsk"),
    ("Breslau", "Wrocław"),
    ("Posen", "Poznań"),
])
def test_every_exonym_maps_to_polish_name(exonym, expected):
    """Literówka w wartości mapy (np. "Wroclaw" bez diakrytyku) rozjechałaby
    klucz deduplikacji względem portali, które zwracają nazwy polskie."""
    assert extract_city(exonym) == expected
    assert extract_city(f"{exonym}, Poland") == expected


def test_remote_offer_gets_same_city_from_greenhouse_and_lever():
    """Ta sama oferta zdalna z dwóch ATS-ów musi dać ten sam klucz dedup.

    Gdy zerowanie "Remote" siedziało tylko w greenhouse.py, Lever zostawiał
    `city="Remote - Europe"` i klucze się rozjeżdżały (`|remote` vs
    `|remote-europe`), więc oferta pokazywała się w mailu dwa razy.
    """
    gh = parse_greenhouse(
        {"jobs": [{"id": 1, "title": "Dev", "absolute_url": "https://x/1",
                   "location": {"name": "Remote - Europe"}}]},
        company="Acme", slug="acme")[0]
    lv = parse_lever(
        [{"id": "1", "text": "Dev", "hostedUrl": "https://y/1",
          "workplaceType": "remote", "categories": {"location": "Remote - Europe"}}],
        company="Acme", slug="acme")[0]

    assert gh.city is None and lv.city is None
    assert dedup_key(gh) == dedup_key(lv)


def test_greenhouse_remote_offer_is_marked_remote_and_matches_profile():
    """Greenhouse nie ma pola bool dla pracy zdalnej — jest tylko tekst w
    `location.name`. Bez `is_remote` taka oferta dostawała `remote=False` i
    `city="Remote"`, więc matcher szukał miasta z profilu w słowie "remote"
    i odrzucał KAŻDĄ ofertę zdalną, także przy `include_remote: true`.
    """
    payload = {"jobs": [{"id": 1, "title": "Frontend Developer",
                         "absolute_url": "https://x/1", "location": {"name": "Remote"},
                         "first_published": "2026-08-01T10:00:00-04:00"}]}

    job = parse_greenhouse(payload, company="Acme", slug="acme")[0]

    assert job.remote is True
    assert job.city is None  # "Remote" nie jest miastem i nie może trafić do klucza dedup

    profile = Profile(name="frontend-szczecin", keywords=["frontend"],
                      locations=["szczecin"], include_remote=True, max_age_days=3650)
    assert matches(job, profile, datetime(2026, 8, 7, tzinfo=timezone.utc)) is True


def test_greenhouse_stationary_offer_is_not_marked_remote():
    payload = {"jobs": [{"id": 1, "title": "Dev", "absolute_url": "https://x/1",
                         "location": {"name": "ul. Zbożowa 4, 70-653 Stettin"}}]}

    job = parse_greenhouse(payload, company="Acme", slug="acme")[0]

    assert job.remote is False
    assert job.city == "Szczecin"


def test_greenhouse_offer_without_url_is_skipped():
    payload = {"jobs": [{"id": 1, "title": "Bez URL", "location": {"name": "Warszawa"}}]}

    assert parse_greenhouse(payload, company="Acme", slug="acme") == []


def test_greenhouse_unparseable_dates_give_none():
    payload = {"jobs": [{"id": 1, "title": "Dev", "absolute_url": "https://x/1",
                          "location": {"name": "Warszawa"},
                          "first_published": "wczoraj", "updated_at": "wczoraj"}]}

    assert parse_greenhouse(payload, company="Acme", slug="acme")[0].posted_at is None


def test_greenhouse_fetch_hits_boards_api():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, json={"jobs": []})

    entry = CompanyEntry(name="home.pl", ats="greenhouse", slug="homepl")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetch_greenhouse(entry, client)

    assert requested == ["https://boards-api.greenhouse.io/v1/boards/homepl/jobs"]


def test_greenhouse_fetch_raises_on_http_error():
    def handler(request):
        return httpx.Response(503)

    entry = CompanyEntry(name="home.pl", ats="greenhouse", slug="homepl")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            fetch_greenhouse(entry, client)


# ---------------------------------------------------------------------------
# Lever
# ---------------------------------------------------------------------------

LEVER_PAYLOAD = "lever.json"


def test_lever_parse_returns_jobs():
    assert len(parse_lever(_payload(LEVER_PAYLOAD), company="Pipedrive", slug="pipedrive")) == 3


def test_lever_parses_list_payload_not_object():
    """Payload Levera to LISTA, nie obiekt z kluczem (inaczej niż
    Recruitee/Greenhouse). Asercja musi być o zachowaniu PARSERA na liście —
    `isinstance(fixture, list)` testowałby tylko fixture i przeszedłby nawet
    przy pustym parserze.
    """
    jobs = parse_lever(_payload(LEVER_PAYLOAD), company="Pipedrive", slug="pipedrive")

    assert len(jobs) == 3
    assert all(job.source == "company:pipedrive" for job in jobs)


def test_lever_city_extracted_regardless_of_segment_order():
    jobs = parse_lever(_payload(LEVER_PAYLOAD), company="Pipedrive", slug="pipedrive")

    # Fixture pipedrive ma "Kraj, Miasto" ("Portugal, Lisbon", "UK, London").
    assert {job.city for job in jobs} == {"Lisbon", "London"}


def test_lever_city_works_for_opposite_segment_order():
    """`categories.location` to pole tekstowe wpisywane przez firmę, nie enum.
    Reguła dopasowana do jednego boarda ("weź ostatni segment") zwracała
    "Poland" dla "Warsaw, Poland" — czyli ciche zero ofert po lokalizacji.
    """
    payload = [{"id": "1", "text": "Dev", "hostedUrl": "https://x/1",
                "categories": {"location": "Warsaw, Poland"}, "createdAt": 1700000000000},
               {"id": "2", "text": "Dev", "hostedUrl": "https://x/2",
                "categories": {"location": "San Francisco, CA"}, "createdAt": 1700000000000}]

    jobs = parse_lever(payload, company="Acme", slug="acme")

    assert [job.city for job in jobs] == ["Warsaw", "San Francisco"]


def test_lever_uses_workplace_type_field():
    payload = [{"id": "1", "text": "Dev", "hostedUrl": "https://x/1",
                "workplaceType": "remote", "categories": {"location": "Poland, Warsaw"},
                "createdAt": 1700000000000}]

    jobs = parse_lever(payload, company="Acme", slug="acme")

    assert jobs[0].remote is True


def test_lever_on_site_workplace_type_is_not_remote():
    # Lokalizacja zawiera słowo "Remote", więc fallback tekstowy dałby tu True —
    # test przechodzi tylko wtedy, gdy `workplaceType` faktycznie ma pierwszeństwo.
    payload = [{"id": "1", "text": "Dev", "hostedUrl": "https://x/1",
                "workplaceType": "on-site", "categories": {"location": "Remote, Poland"},
                "createdAt": 1700000000000}]

    jobs = parse_lever(payload, company="Acme", slug="acme")

    assert jobs[0].remote is False


def test_lever_created_at_is_epoch_milliseconds():
    # Asercja na konkretną datę: przy potraktowaniu `createdAt` jako sekund
    # wyszedłby rok 58509, a nie 2026 — `is not None` tego nie wyłapie.
    payload = [{"id": "1", "text": "Dev", "hostedUrl": "https://x/1",
                "categories": {"location": "Warsaw, Poland"},
                "createdAt": 1784736705020}]

    posted_at = parse_lever(payload, company="Acme", slug="acme")[0].posted_at

    assert posted_at.year == 2026
    assert posted_at.tzinfo is not None


def test_lever_falls_back_to_apply_url():
    """Fixture jest przycięty także kolumnowo (bez `applyUrl`), więc ten
    fallback nie ma pokrycia w realnych danych — stąd przypadek syntetyczny."""
    payload = [{"id": "1", "text": "Dev", "applyUrl": "https://jobs.lever.co/acme/1/apply",
                "categories": {"location": "Warsaw, Poland"}}]

    assert parse_lever(payload, company="Acme", slug="acme")[0].url.endswith("/apply")


def test_lever_offer_without_url_is_skipped():
    payload = [{"id": "1", "text": "Bez URL"}]

    assert parse_lever(payload, company="Acme", slug="acme") == []


def test_lever_fetch_hits_postings_api():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, json=[])

    entry = CompanyEntry(name="Pipedrive", ats="lever", slug="pipedrive")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetch_lever(entry, client)

    assert requested == ["https://api.lever.co/v0/postings/pipedrive?mode=json"]


def test_lever_fetch_raises_on_http_error():
    def handler(request):
        return httpx.Response(503)

    entry = CompanyEntry(name="Pipedrive", ats="lever", slug="pipedrive")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            fetch_lever(entry, client)


# ---------------------------------------------------------------------------
# Workable
# ---------------------------------------------------------------------------

WORKABLE_PAYLOAD = "workable.json"


def test_workable_parse_returns_jobs():
    assert len(parse_workable(_payload(WORKABLE_PAYLOAD), company="Netguru", slug="netguru")) == 3


def test_workable_empty_city_string_becomes_none():
    """Zweryfikowane na żywo: `city` bywa `""`, nie `null`. Bez `or None` w
    parserze klucz deduplikacji dostałby pusty segment zamiast braku miasta.
    """
    jobs = {job.title: job for job in parse_workable(_payload(WORKABLE_PAYLOAD), company="Netguru",
                                                       slug="netguru")}

    assert jobs["(Senior) Data Engineer - Freelance"].city is None
    assert jobs["Business Development Manager"].city is None


def test_workable_non_empty_city_is_kept():
    jobs = {job.title: job for job in parse_workable(_payload(WORKABLE_PAYLOAD), company="Netguru",
                                                       slug="netguru")}

    assert jobs["(Senior) Fullstack Engineer (Node.js + Python + Typescript) - Freelance"].city == "Poznań"


def test_workable_falls_back_to_shortlink_and_url_as_external_id():
    """`shortlink` i brak `shortcode` nie występują w przyciętym fixture —
    obie gałęzie fallbacku pokryte tylko tu."""
    payload = {"jobs": [{"title": "Dev", "shortlink": "https://wrkbl.co/abc",
                         "city": "Szczecin", "telecommuting": False}]}

    job = parse_workable(payload, company="Acme", slug="acme")[0]

    assert job.url == "https://wrkbl.co/abc"
    assert job.external_id == "https://wrkbl.co/abc"


def test_workable_external_id_is_shortcode_not_id():
    jobs = parse_workable(_payload(WORKABLE_PAYLOAD), company="Netguru", slug="netguru")

    assert jobs[0].external_id == "C99A238797"


def test_workable_telecommuting_maps_to_remote():
    """Fixture netguru ma `telecommuting: true` we WSZYSTKICH ofertach, więc
    samo `all(remote is True)` przechodziłoby też przy `remote=True` na
    sztywno. Gałąź `false` musi być sprawdzona osobno, na danych syntetycznych.
    """
    jobs = parse_workable(_payload(WORKABLE_PAYLOAD), company="Netguru", slug="netguru")
    assert all(job.remote is True for job in jobs)

    stationary = {"jobs": [{"shortcode": "X1", "title": "Dev", "url": "https://x/1",
                            "city": "Szczecin", "telecommuting": False,
                            "published_on": "2026-07-14"}]}
    assert parse_workable(stationary, company="Acme", slug="acme")[0].remote is False


def test_workable_published_on_date_only_becomes_utc_datetime():
    """`published_on` to sama data ("2026-07-14"), bez godziny i strefy —
    `fromisoformat` da naive datetime, a walidator w models.py dociąga UTC.
    Asercja na konkretną wartość, nie na `is not None`, żeby test faktycznie
    weryfikował format.
    """
    payload = {"jobs": [{"shortcode": "X1", "title": "Dev", "url": "https://x/1",
                         "city": "Szczecin", "telecommuting": False,
                         "published_on": "2026-07-14"}]}

    posted_at = parse_workable(payload, company="Acme", slug="acme")[0].posted_at

    assert posted_at == datetime(2026, 7, 14, tzinfo=timezone.utc)


def test_workable_offer_without_url_is_skipped():
    payload = {"jobs": [{"shortcode": "X1", "title": "Bez URL"}]}

    assert parse_workable(payload, company="Acme", slug="acme") == []


def test_workable_fetch_hits_widget_api():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, json={"jobs": []})

    entry = CompanyEntry(name="Netguru", ats="workable", slug="netguru")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetch_workable(entry, client)

    assert requested == ["https://apply.workable.com/api/v1/widget/accounts/netguru?details=true"]


def test_workable_fetch_raises_on_http_error():
    def handler(request):
        return httpx.Response(503)

    entry = CompanyEntry(name="Netguru", ats="workable", slug="netguru")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            fetch_workable(entry, client)
