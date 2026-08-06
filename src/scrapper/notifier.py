import smtplib
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scrapper.models import Job, SmtpConfig
from scrapper.sources.base import SourceResult

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates"


def _safe_url(url: str | None) -> str:
    """Przepuszcza wyłącznie adresy http(s), resztę zamienia na pusty string.

    URL-e pochodzą z zewnętrznych API, których nie kontrolujemy. Autoescaping
    Jinja2 chroni przed wstrzyknięciem znaczników HTML, ale nie waliduje
    schematu — `javascript:...` nie zawiera żadnego znaku specjalnego HTML,
    więc trafiłby do `href` bez zmian. To osobna warstwa obrony.
    """
    if not url:
        return ""
    normalized = url.strip().lower()
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return url.strip()
    return ""


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
    )
    env.filters["safe_url"] = _safe_url
    return env


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
