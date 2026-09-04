from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator


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
    # Wymagane technologie/umiejętności, gdy źródło je podaje. Powód: nazwa
    # narzędzia bywa WYŁĄCZNIE tutaj, nigdy w tytule. Zweryfikowane na żywo —
    # jedyna oferta z Teklą na RocketJobs ma tytuł "Asystent/ka Projektanta
    # Konstrukcji", a "Tekla" siedzi w requiredSkills. Szukanie po samym tytule
    # gubiłoby ją bezpowrotnie.
    skills: list[str] = Field(default_factory=list)
    # Dodatkowy tekst uzywany tylko podczas dopasowania (np. opis z firmowego
    # API). Nie zapisujemy go do jobs.jsonl ani nie wysylamy w mailu: opisy sa
    # duze, a ich jedynym zadaniem jest znalezienie technologii takich jak
    # Revit/Tekla, ktore czesto nie wystepuja w tytule stanowiska.
    search_text: str = Field(default="", exclude=True)
    # Metadane geograficzne z globalnych firmowych ATS-ow. Brak kraju nie
    # blokuje oferty, ale jawne "Ukraine" nie moze udawac pracy zdalnej z PL.
    country: str | None = Field(default=None, exclude=True)

    @field_validator("posted_at", mode="before")
    @classmethod
    def normalize_posted_at(cls, value):
        """Normalizuj naiwny posted_at do UTC (zakładamy UTC gdy brakuje strefy)."""
        if value is not None and isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


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
    # Pelny opis latwo daje falszywe trafienia (np. QA wspomina JavaScript).
    # Wlaczamy go tylko dla profili narzedziowych, gdzie Revit/Tekla zwykle sa
    # ukryte w wymaganiach zamiast w tytule.
    search_description: bool = False
    # Kategorie NoFluffJobs zawężające zapytanie PO STRONIE SERWERA.
    # NFJ ma ~21600 ofert ogólnopolsko, nie sortuje po dacie i nie przyjmuje
    # żadnego parametru sortowania (sprawdzone: `sort`, `rawSearch`), więc
    # pobranie budżetowego wycinka daje losowy przekrój, w którym świeże oferty
    # bywają nieobecne. Filtr kategorii zbija pulę do rozmiaru, który da się
    # pobrać W CAŁOŚCI (frontend: 508, fullstack: 1274) — a wtedy kolejność
    # przestaje mieć znaczenie.
    #
    # UWAGA: nieistniejąca kategoria zwraca HTTP 200 i totalCount=0, nie błąd.
    # Literówka cicho wyzeruje źródło — ratunkiem jest ostrzeżenie "0 ofert"
    # w logu Actions i w stopce maila. Pusta lista = bez filtra (stare zachowanie).
    nofluffjobs_categories: list[str] = Field(default_factory=list)


class SmtpConfig(BaseModel):
    host: str
    port: int = 587
    user: str
    password: str
    to: str


class Config(BaseModel):
    smtp: SmtpConfig
    profiles: list[Profile]
