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


def test_render_escapes_script_tag_in_title():
    html = render([_job(title="<script>alert(1)</script>")], warnings=[])

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_escapes_html_injection_in_company():
    html = render([_job(company='"><img src=x onerror=alert(1)>')], warnings=[])

    assert "<img" not in html


def test_render_strips_javascript_url_but_keeps_title():
    html = render([_job(url="javascript:alert(1)")], warnings=[])

    assert "javascript:" not in html
    assert "Frontend Developer" in html


def test_render_strips_javascript_alt_url_but_keeps_safe_one():
    html = render(
        [_job(alt_urls=["javascript:alert(1)", "https://example.com/ok"])],
        warnings=[],
    )

    assert "javascript:" not in html
    assert "https://example.com/ok" in html


def test_render_keeps_normal_https_link_working():
    html = render([_job(url="https://justjoin.it/1")], warnings=[])

    assert 'href="https://justjoin.it/1"' in html


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
