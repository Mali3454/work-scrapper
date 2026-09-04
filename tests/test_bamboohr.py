from types import SimpleNamespace

from scrapper.sources.ats.bamboohr import parse_bamboohr


def test_parse_bamboohr_uses_real_location_and_career_url():
    entry = SimpleNamespace(
        name="Macrobond",
        slug="macrobond",
        url="https://macrobond.bamboohr.com/careers/",
    )
    payload = {
        "result": [
            {
                "id": "317",
                "jobOpeningName": "Data Tools Team Manager",
                "location": {"city": "Szczecin", "state": "PL"},
                "atsLocation": {},
                "isRemote": None,
                "departmentLabel": "Data",
            }
        ]
    }

    jobs = parse_bamboohr(payload, entry)

    assert len(jobs) == 1
    assert jobs[0].city == "Szczecin"
    assert jobs[0].remote is False
    assert jobs[0].url == "https://macrobond.bamboohr.com/careers/317"
    assert jobs[0].source == "company:macrobond"
