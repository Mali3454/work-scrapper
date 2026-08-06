from datetime import datetime

from pydantic import BaseModel, Field


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
