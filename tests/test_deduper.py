from datetime import datetime, timezone

from scrapper.deduper import _company_slug, dedup_key, deduplicate, priority_of
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


def test_lodz_and_lodz_transliteration_produce_same_key():
    """Łódź (Polish spelling) and Lodz (transliterated) should produce same key."""
    a = dedup_key(_job(company="Acme", city="Łódź"))
    b = dedup_key(_job(company="Acme", city="Lodz"))

    assert a == b


def test_company_with_sa_dots_and_without_suffix_produce_same_key():
    """Acme S.A. (with dots) should produce same key as Acme."""
    a = dedup_key(_job(company="Acme S.A."))
    b = dedup_key(_job(company="Acme"))

    assert a == b


def test_company_sp_z_oo_and_without_suffix_produce_same_key():
    """Acme Sp. z o.o. should produce same key as Acme (regression test)."""
    a = dedup_key(_job(company="Acme Sp. z o.o."))
    b = dedup_key(_job(company="Acme"))

    assert a == b


def test_company_slug_sa_is_not_empty_and_differs_from_acme():
    """Company named 'SA' should not reduce to empty string, and differ from 'Acme'."""
    sa_slug = _company_slug("SA")
    acme_slug = _company_slug("Acme")

    assert sa_slug != ""
    assert sa_slug != acme_slug


def test_same_offer_matching_two_profiles_gets_no_self_link():
    """Oferta pasująca do dwóch profili trafia do deduplikacji dwa razy z tym
    samym URL-em — nie może dostać w mailu linku "także tutaj" na siebie."""
    job = _job(source="justjoinit", url="https://justjoin.it/1")

    result = deduplicate([job, job], NOW)

    assert len(result) == 1
    assert result[0].alt_urls == []


def test_alt_urls_do_not_repeat_the_same_source_url():
    portal = _job(source="justjoinit", url="https://justjoin.it/1")
    company = _job(source="company:acme", url="https://acme.com/1")

    result = deduplicate([portal, portal, company], NOW)

    assert result[0].url == "https://acme.com/1"
    assert result[0].alt_urls == ["https://justjoin.it/1"]
