"""Admin API bodies. Every list answers {items, total, page, per_page}; timestamps are ISO 8601 with offset."""
from __future__ import annotations

import datetime as dt
import decimal
import uuid
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from .enums import Channel, ErasureReason, LeadKind, LeadStatus, LostReason, Origin, ReviewStatus
from .services import phone as phones

T = TypeVar("T")
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    per_page: int


class Ref(BaseModel):
    """A catalog or user reference."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class BreedRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    key: str
    slug: str
    name: str


class PuppyRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    name: str
    status: str
    is_active: bool


# ---------------------------------------------------------------- auth
class LoginIn(BaseModel):
    login: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class Me(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    login: str
    name: str
    role: str
    is_service: bool


class LoginOut(BaseModel):
    token: str
    expires_at: dt.datetime
    user: Me


# ---------------------------------------------------------------- leads
class LeadRow(BaseModel):
    """One line of the list (and the base of the detail view)."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    public_id: uuid.UUID
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime
    origin: str
    kind: str
    status: str
    parent_id: int | None
    breed: BreedRef | None
    breed_input: str | None
    puppy: PuppyRef | None
    puppy_slug: str | None
    puppy_name: str | None
    colour: str | None
    note: str | None
    form_title: str | None
    contact_id: int | None
    name: str | None
    phone: str | None
    phone_display: str | None = None
    channel: str
    is_repeat: bool
    page_path: str | None
    source: str | None
    medium: str | None
    assignee: Ref | None
    next_contact_at: dt.datetime | None
    first_response_at: dt.datetime | None
    closed_at: dt.datetime | None
    last_activity_at: dt.datetime
    lost_reason: str | None
    sale_amount: decimal.Decimal | None
    spam_reason: str | None
    flags: list[str]
    anonymised_at: dt.datetime | None
    children_count: int = 0


class HistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    at: dt.datetime
    actor_id: int | None
    actor_label: str
    action: str
    old_value: str | None
    new_value: str | None
    comment: str | None


class Journey(BaseModel):
    """What the person did on the site (only while link_site_activity is on)."""
    first_seen_at: dt.datetime | None = None
    first_landing: str | None = None
    first_source: str | None = None
    first_medium: str | None = None
    visits: int = 0
    days_to_request: int | None = None
    pages_before: list[dict] = Field(default_factory=list)       # last pages before the request: {path, at}
    puppies_viewed: list[str] = Field(default_factory=list)
    breeds_viewed: list[str] = Field(default_factory=list)
    quiz: dict | None = None
    ym_uid: str | None = None


class LeadDetail(LeadRow):
    page_title: str | None
    referrer_host: str | None
    landing_path: str | None
    utm: dict | None
    details: dict
    consent_at: dt.datetime | None
    consent_version: str | None
    children: list[LeadRow] = Field(default_factory=list)
    other_leads: list[LeadRow] = Field(default_factory=list)    # the same person's requests (all breeds)
    history: list[HistoryItem] = Field(default_factory=list)
    journey: Journey | None = None
    links: dict[str, str] = Field(default_factory=dict)          # tel:, wa.me, t.me


class LeadPatch(BaseModel):
    """Send only what changes. `version` must be the version you read (optimistic locking) — or If-Match."""
    model_config = ConfigDict(extra="forbid")
    version: int | None = None
    status: LeadStatus | None = None
    lost_reason: LostReason | None = None
    sale_amount: decimal.Decimal | None = Field(default=None, ge=0)
    assignee_id: int | None = None
    breed: str | None = None          # slug; "" → no breed (moves the request to the general base)
    puppy: str | None = None          # slug; "" → no puppy
    colour: str | None = None
    next_contact_at: dt.datetime | None = None
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] | None = None


class CommentIn(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class ManualLeadIn(BaseModel):
    origin: Origin
    kind: LeadKind = LeadKind.other
    name: Name
    phone: str
    channel: Channel = Channel.call
    breed: str | None = None
    puppy: str | None = None
    colour: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z-]{0,39}$")] | None = None
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None
    assignee_id: int | None = None
    attach_to_open: bool = True       # join the person's open request of the same breed, as the site does

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        e = phones.normalize(v)
        if not e:
            raise ValueError("bad phone")
        return e

    @field_validator("origin")
    @classmethod
    def _not_site(cls, v: Origin) -> Origin:
        if v == Origin.site_form:
            raise ValueError("site_form is only for requests from the site")
        return v


class CountCell(BaseModel):
    breed: str | None          # breed key, or "general" for requests without a breed
    status: str | None
    kind: str | None
    origin: str | None
    count: int


# ---------------------------------------------------------------- contacts
class ContactRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    phone: str
    phone_display: str | None = None
    name: str
    preferred_channel: str | None
    telegram_username: str | None
    notes: str | None
    is_blocked: bool
    first_seen_at: dt.datetime
    last_seen_at: dt.datetime
    leads_count: int = 0
    open_leads: int = 0


class ContactDetail(ContactRow):
    leads: list[LeadRow] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    consents: list[dict] = Field(default_factory=list)
    links: dict[str, str] = Field(default_factory=dict)


class ContactPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name | None = None
    preferred_channel: Channel | None = None
    telegram_username: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^@?[A-Za-z0-9_]{4,32}$")] | None = None
    notes: Annotated[str, StringConstraints(max_length=4000)] | None = None
    is_blocked: bool | None = None


class MergeIn(BaseModel):
    into_id: int


class EraseIn(BaseModel):
    reason: ErasureReason
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = Field(
        description="Whose data, as the request names the person (for the erasure record)")


class EventRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    type: str
    path: str | None
    breed_key: str | None
    puppy_slug: str | None
    data: dict
    occurred_at: dt.datetime
    session_id: uuid.UUID | None


# ---------------------------------------------------------------- reviews
class ReviewRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: dt.datetime
    name: str
    display_name: str
    city: str | None
    breed: BreedRef | None
    rating: int
    text: str
    status: str
    moderated_at: dt.datetime | None
    moderator_note: str | None
    withdrawn_at: dt.datetime | None
    page_path: str | None
    spam_reason: str | None


class ReviewPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ReviewStatus | None = None
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] | None = None
    city: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=4000)] | None = None
    moderator_note: Annotated[str, StringConstraints(max_length=300)] | None = None


# ---------------------------------------------------------------- puppies / stats / meta
class PuppyRow(BaseModel):
    id: int
    slug: str
    name: str
    breed: BreedRef
    sex: str | None
    colour: str | None
    status: str
    is_active: bool
    leads_total: int
    leads_open: int
    leads_by_status: dict[str, int]
    catalog_mismatch: bool     # a request for this puppy is reserved / won, but the site still shows it available


class StatsOut(BaseModel):
    period: dict[str, str]
    totals: dict[str, int]
    by_breed: list[dict]
    by_kind: list[dict]
    by_status: list[dict]
    by_origin: list[dict]
    by_source: list[dict]
    by_day: list[dict]
    response: dict             # median / p90 minutes to the first manager action
    visits: dict               # sessions, visitors, conversion to a request


class MetaOut(BaseModel):
    statuses: list[dict]
    kinds: list[dict]
    origins: list[dict]
    channels: list[dict]
    lost_reasons: list[dict]
    review_statuses: list[dict]
    erasure_reasons: list[dict]
    event_types: list[dict]
    breeds: list[dict]
    managers: list[dict]
    timezone: str
    link_site_activity: bool
