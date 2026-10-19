"""Request and response bodies of the public API (what assets/js/main.js, trust.js and choice.js send).

Rule: only the fields a person types and must get right (name, phone, «куда написать», consent) can fail
validation; everything else is optional, free-form and trimmed by the service — a cached old page or a catalog gap
must never cost a request."""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, field_validator

from .enums import Channel
from .services import phone as phones
from .services.sanitize import clean


def _opt_str(v: Any) -> str | None:
    """Any scalar → str (trimmed later by the service); dicts / lists / empty → None."""
    if v is None or isinstance(v, (dict, list)):
        return None
    s = str(v)
    return s if s.strip() else None


def _opt_uuid(v: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(v)) if v else None
    except (ValueError, TypeError, AttributeError):
        return None


def _opt_dict(v: Any) -> dict | None:
    if isinstance(v, dict):
        out = {}
        for k, val in list(v.items())[:10]:
            if isinstance(val, (str, int, float)) and not isinstance(val, bool):
                ck, cv = clean(str(k), 20), clean(str(val), 150)
                if ck and cv:
                    out[ck] = cv
        return out or None
    return None


OptStr = Annotated[str | None, BeforeValidator(_opt_str)]
OptUUID = Annotated[uuid.UUID | None, BeforeValidator(_opt_uuid)]
OptDict = Annotated[dict | None, BeforeValidator(_opt_dict)]


def _opt_int(v: Any) -> int | None:
    try:
        n = int(v)
        return n if 0 <= n <= 86_400_000 else None
    except (ValueError, TypeError, OverflowError):
        return None


OptInt = Annotated[int | None, BeforeValidator(_opt_int)]


class PageIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: OptStr = None
    title: OptStr = None


def _page(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


class TrackIn(BaseModel):
    """Browser ids and attribution main.js keeps (visitor in localStorage, session in sessionStorage)."""
    model_config = ConfigDict(extra="ignore")
    visitor_id: OptUUID = None
    session_id: OptUUID = None
    landing: OptStr = None            # first page of this visit
    referrer: OptStr = None           # external referrer of this visit
    utm: OptDict = None               # utm_* / yclid / gclid of this visit
    first_landing: OptStr = None
    first_referrer: OptStr = None
    first_utm: OptDict = None
    ym_uid: OptStr = None             # Yandex Metrika ClientID, if Metrika is on the site


class LeadIn(TrackIn):
    # required — the only fields that can produce 422 (keys = HTML input names)
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    phone: str
    contact: Channel
    consent: bool

    # optional, best effort
    kind: OptStr = None
    breed: OptStr = None              # <select> value: slug, "undecided" or "" (old pages: the Russian name)
    puppy: OptStr = None              # puppy slug
    puppy_name: OptStr = None
    colour: OptStr = None             # colour slug
    note: OptStr = None               # data-modal-note of the button
    form_title: OptStr = None
    quiz: OptDict = None              # {"winner": "maltipu", "second": "toj-pudel"}
    consent_version: OptStr = None
    page: Annotated[PageIn, BeforeValidator(_page)] = Field(default_factory=PageIn)
    idempotency_key: OptUUID = None   # missing → the server makes one
    hp_note: OptStr = None            # honeypot
    elapsed_ms: OptInt = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        e164 = phones.normalize(v)
        if not e164:
            raise ValueError("bad phone")
        return e164

    @field_validator("consent")
    @classmethod
    def _consent(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("consent required")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        cleaned = clean(v, 100)
        if not cleaned:  # only invisible / control characters
            raise ValueError("empty")
        return cleaned


class LeadAccepted(BaseModel):
    id: uuid.UUID = Field(description="Public id of the request (the admin number is not shown to visitors)")
    status: str = "accepted"


class ReviewIn(TrackIn):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    phone: str                         # the author's contact (Приказ РКН № 18), never published
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=4000)]
    rating: int = Field(ge=1, le=5)
    consent: bool
    consent_publish: bool
    city: OptStr = None
    breed: OptStr = None
    consent_version: OptStr = None
    consent_publish_version: OptStr = None
    page: Annotated[PageIn, BeforeValidator(_page)] = Field(default_factory=PageIn)
    idempotency_key: OptUUID = None
    hp_note: OptStr = None
    elapsed_ms: OptInt = None

    @field_validator("consent", "consent_publish")
    @classmethod
    def _consent(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("consent required")
        return v

    @field_validator("phone")
    @classmethod
    def _review_phone(cls, v: str) -> str:
        e164 = phones.normalize(v)
        if not e164:
            raise ValueError("bad phone")
        return e164

    @field_validator("text")
    @classmethod
    def _text(cls, v: str) -> str:
        cleaned = clean(v, 4000, multiline=True) or ""
        if len(cleaned) < 10:  # invisible characters do not count
            raise ValueError("too short")
        return cleaned

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        cleaned = clean(v, 100)
        if not cleaned:
            raise ValueError("empty")
        return cleaned


class ReviewAccepted(BaseModel):
    status: str = "pending"


class EventIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: OptStr = None
    path: OptStr = None
    ts: int | None = None             # ms since epoch, browser clock (clamped by the server)
    data: dict | None = None

    @field_validator("ts", mode="before")
    @classmethod
    def _ts(cls, v):
        try:
            return int(v)
        except (TypeError, ValueError, OverflowError):
            return None

    @field_validator("data", mode="before")
    @classmethod
    def _data(cls, v):
        return v if isinstance(v, dict) else None


class EventsIn(TrackIn):
    events: list[EventIn] = Field(default_factory=list)

    @field_validator("events", mode="before")
    @classmethod
    def _events(cls, v):
        return [e for e in v if isinstance(e, dict)][:50] if isinstance(v, list) else []


class EventsAccepted(BaseModel):
    accepted: int
    dropped: int
