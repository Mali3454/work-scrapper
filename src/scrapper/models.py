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


class SmtpConfig(BaseModel):
    host: str
    port: int = 587
    user: str
    password: str
    to: str


class Config(BaseModel):
    smtp: SmtpConfig
    profiles: list[Profile]
