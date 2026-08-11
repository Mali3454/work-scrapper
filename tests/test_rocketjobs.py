import json
from pathlib import Path

import httpx

from scrapper.matcher import matches
from scrapper.models import Profile
from scrapper.sources.rocketjobs import RocketJobs, parse_rocketjobs

FIXTURE = Path(__file__).parent / "fixtures" / "rocketjobs.json"

from datetime import datetime, timezone

NOW = datetime(2026, 8, 8, tzinfo=timezone.utc)


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_returns_jobs_tagged_as_rocketjobs():
    jobs = parse_rocketjobs(_payload())

    assert len(jobs) == 3
    assert all(job.source == "rocketjobs" for job in jobs)


def test_urls_point_at_rocketjobs_not_justjoinit():
    """RocketJobs dziedziczy parser po JustJoinIT — gdyby `offer_url` nie było
    podmienione, linki w mailu prowadziłyby na justjoin.it i dawały 404."""
    jobs = parse_rocketjobs(_payload())

    assert all(job.url.startswith("https://rocketjobs.pl/oferta-pracy/") for job in jobs)


def test_skills_are_extracted_from_object_list():
    """`requiredSkills` to lista OBIEKTÓW {"name","level"}, nie stringów —
    potraktowanie ich jak stringi wywala się TypeError przy sklejaniu."""
    jobs = {job.title: job for job in parse_rocketjobs(_payload())}
    tekla_job = next(j for j in jobs.values() if any("tekla" in s.casefold() for s in j.skills))

    assert "AutoCAD" in tekla_job.skills
    assert all(isinstance(s, str) for s in tekla_job.skills)


def test_tekla_offer_matches_profile_although_title_lacks_the_word():
    """Sedno tego źródła: "Tekla" NIE występuje w tytule oferty, tylko w
    `requiredSkills`. Matcher szukający po samym tytule gubiłby ją bezpowrotnie
    — a to jedyna oferta z Teklą, jaką w ogóle znaleźliśmy na wszystkich
    portalach (0 trafień w JustJoinIT i NoFluffJobs)."""
    tekla_job = next(j for j in parse_rocketjobs(_payload())
                     if any("tekla" in s.casefold() for s in j.skills))
    assert "tekla" not in tekla_job.title.casefold()  # potwierdza założenie testu

    profile = Profile(name="tekla", keywords=["tekla"], locations=[tekla_job.city or "Kraków"],
                      include_remote=True, max_age_days=3650)

    assert matches(tekla_job, profile, NOW) is True


def test_exclude_ignores_skills_and_looks_only_at_title():
    """`exclude: [senior]` ma odrzucać stanowiska seniorskie, a nie oferty
    juniorskie wymagające np. współpracy z seniorem — dlatego wykluczenia
    celowo NIE patrzą na umiejętności."""
    from scrapper.models import RawJob

    job = RawJob(source="rocketjobs", external_id="1", title="Junior Developer",
                 company="Acme", city="Szczecin", url="https://x/1",
                 skills=["senior mentoring", "react"])
    profile = Profile(name="p", keywords=["react"], exclude=["senior"],
                      locations=["szczecin"], max_age_days=3650)

    assert matches(job, profile, NOW) is True


def test_fetch_hits_rocketjobs_host():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"data": [], "meta": {}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        RocketJobs(cities=["szczecin"]).fetch(client)

    assert all("rocketjobs.pl/api/candidate-api/offers" in u for u in seen)
    assert not any("justjoin.it" in u for u in seen)
