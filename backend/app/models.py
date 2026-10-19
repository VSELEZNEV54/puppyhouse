"""Database schema (PostgreSQL 16). One database; every request from every form lands in `leads`.

Per-breed «bases» are SQL views with readable columns: leads_maltipu, leads_buldog, leads_pudel, leads_kolli
(one per breed key in src/data/breeds.json), leads_general (no breed chosen) and leads_all (everything, with the
breed name). They are rebuilt by `python -m app migrate` and `python -m app sync-catalog` (app/services/views.py).
The admin API gives the same split: /admin/leads?breed=maltipu and /admin/leads/counts?group_by=breed.

    consent_versions ─┐
    breeds ─ puppies ─┼─ leads ─ contacts ─ contact_aliases
                      │    ├─ lead_history (status, assignment, comments, repeat requests)
                      │    └─ outbox (Telegram / webhook notifications with retries)
    visitors ─ sessions ─ site_events          (leads.visitor_id links a request to the visits before it)
    reviews · admin_users ─ admin_tokens · audit_log · rate_limits

Every timestamp is timestamptz. updated_at is kept by a trigger (see migrations/versions/0001_initial.py).
Rows of the catalog are never deleted (soft deactivation); admin users are deactivated, not deleted.
"""
from __future__ import annotations

import datetime as dt
import decimal
import uuid

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint,
                        Identity, Index, Integer, MetaData, Numeric, SmallInteger, String, Text, UniqueConstraint,
                        func)
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .enums import (Channel, HistoryAction, LeadKind, LeadStatus, LostReason, Origin, PuppyStatus, ReviewStatus, Role,
                    SpamReason, check)

TZ = DateTime(timezone=True)
PHONE_CHECK = "phone ~ '^\\+[1-9][0-9]{7,14}$'"  # E.164; the API accepts Russian numbers only (+7 and 10 digits)

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _now():
    return mapped_column(TZ, nullable=False, server_default=func.now())


def _json_object(column: str) -> str:
    return f"jsonb_typeof({column}) = 'object'"


# ---------------------------------------------------------------- consent (152-ФЗ)
class ConsentVersion(Base):
    """Published consent documents (a separate document since the 01.09.2025 amendments to 152-ФЗ). Loaded from
    src/data/consent.json by `python -m app sync-catalog`; a published version is never edited, only superseded."""
    __tablename__ = "consent_versions"
    version: Mapped[str] = mapped_column(String(40), primary_key=True)  # «processing-2026-10-16»
    kind: Mapped[str] = mapped_column(String(16))   # processing (requests) | review | distribution | marketing
    title: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(300))
    checkbox_text: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(String(64))
    effective_from: Mapped[dt.datetime] = _now()
    __table_args__ = (CheckConstraint("kind IN ('processing', 'review', 'distribution', 'marketing')", name="kind"),)


class Consent(Base):
    """Proof of one consent: who, which document, when, from which page and IP. Kept until the person is erased
    (not wiped with the IPs of old requests)."""
    __tablename__ = "consents"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    given_at: Mapped[dt.datetime] = _now()
    version: Mapped[str] = mapped_column(ForeignKey("consent_versions.version", ondelete="RESTRICT"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"), index=True)
    review_id: Mapped[int | None] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True)
    page_path: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(400))
    withdrawn_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    __table_args__ = (CheckConstraint("num_nonnulls(contact_id, review_id) >= 1", name="has_subject"),)


# ---------------------------------------------------------------- catalog (synced from src/data/*.json)
class Breed(Base):
    __tablename__ = "breeds"
    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True)           # buldog — stable: view name, Telegram chat
    slug: Mapped[str] = mapped_column(String(64), unique=True)          # francuzskij-buldog (URL)
    name: Mapped[str] = mapped_column(String(100))                      # Французский бульдог
    sort: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=sql("true"))
    first_seen_at: Mapped[dt.datetime] = _now()
    deactivated_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    synced_at: Mapped[dt.datetime] = _now()
    __table_args__ = (
        CheckConstraint("key ~ '^[a-z][a-z0-9_]{0,31}$'", name="key_format"),
        Index("uq_breeds_lower_name", func.lower(sql("name")), unique=True),
    )


class Puppy(Base):
    """Puppy status is owned by puppies.json (the site); the admin panel reads it, never edits it here."""
    __tablename__ = "puppies"
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True)         # maltipu-f1-krem-2026-08
    breed_id: Mapped[int] = mapped_column(ForeignKey("breeds.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    sex: Mapped[str | None] = mapped_column(String(10))
    colour: Mapped[str | None] = mapped_column(String(60))
    generation: Mapped[str | None] = mapped_column(String(20))
    birth_date: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=sql("true"))
    first_seen_at: Mapped[dt.datetime] = _now()
    deactivated_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    synced_at: Mapped[dt.datetime] = _now()
    breed: Mapped[Breed] = relationship(lazy="joined")
    __table_args__ = (
        CheckConstraint(check("status", PuppyStatus), name="status"),
        CheckConstraint("sex IS NULL OR sex IN ('male', 'female')", name="sex"),
        UniqueConstraint("id", "breed_id", name="uq_puppies_id_breed"),  # target of the leads (puppy, breed) FK
    )


# ---------------------------------------------------------------- people
class Contact(Base):
    """One person, deduplicated by phone (E.164) with an atomic INSERT … ON CONFLICT. Leads keep their own copy of
    the name and phone as typed; the contact name is never overwritten by a form (manager edits survive)."""
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    phone: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    preferred_channel: Mapped[str | None] = mapped_column(String(16))
    telegram_username: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    is_blocked: Mapped[bool] = mapped_column(Boolean, server_default=sql("false"))
    first_seen_at: Mapped[dt.datetime] = _now()
    last_seen_at: Mapped[dt.datetime] = _now()
    updated_at: Mapped[dt.datetime] = _now()
    __table_args__ = (
        CheckConstraint(PHONE_CHECK, name="phone_e164"),
        CheckConstraint(check("preferred_channel", Channel, nullable=True), name="channel"),
        CheckConstraint("char_length(name) <= 100", name="name_len"),
        Index("ix_contacts_last_seen", sql("last_seen_at DESC")),
    )


class ContactAlias(Base):
    """Old phone numbers of merged contacts: a new request from such a number goes to the surviving contact."""
    __tablename__ = "contact_aliases"
    phone: Mapped[str] = mapped_column(String(16), primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[dt.datetime] = _now()
    __table_args__ = (CheckConstraint(PHONE_CHECK, name="phone_e164"),)


# ---------------------------------------------------------------- visits (anonymous until a form is sent)
class Visitor(Base):
    """A browser: random uuid kept in localStorage by main.js. First touch = where the person first came from."""
    __tablename__ = "visitors"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    first_seen_at: Mapped[dt.datetime] = _now()
    last_seen_at: Mapped[dt.datetime] = _now()
    first_landing: Mapped[str | None] = mapped_column(String(300))
    first_referrer_host: Mapped[str | None] = mapped_column(String(200))
    first_utm: Mapped[dict | None] = mapped_column(JSONB)
    first_source: Mapped[str | None] = mapped_column(String(60))
    first_medium: Mapped[str | None] = mapped_column(String(60))
    ym_uid: Mapped[str | None] = mapped_column(String(40))              # Yandex Metrika ClientID (Webvisor link)


class Visit(Base):
    """A browsing session (main.js starts a new one after 30 minutes without activity). No IP and no user agent here
    (152-ФЗ minimisation): only a coarse device type."""
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    visitor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visitors.id", ondelete="CASCADE"))
    started_at: Mapped[dt.datetime] = _now()
    last_seen_at: Mapped[dt.datetime] = _now()
    landing_path: Mapped[str | None] = mapped_column(String(300))
    referrer_host: Mapped[str | None] = mapped_column(String(200))
    utm: Mapped[dict | None] = mapped_column(JSONB)
    source: Mapped[str | None] = mapped_column(String(60))
    medium: Mapped[str | None] = mapped_column(String(60))
    device: Mapped[str | None] = mapped_column(String(10))             # mobile | tablet | desktop | bot
    events_count: Mapped[int] = mapped_column(Integer, server_default="0")
    __table_args__ = (Index("ix_sessions_visitor_started", "visitor_id", "started_at"),
                      Index("ix_sessions_started", "started_at"))


class SiteEvent(Base):
    """What happened on the site. Breed and puppy are plain text (no FK): a beacon must never fail on the catalog."""
    __tablename__ = "site_events"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    visitor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visitors.id", ondelete="CASCADE"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(32))
    path: Mapped[str | None] = mapped_column(String(300))
    breed_key: Mapped[str | None] = mapped_column(String(32))
    puppy_slug: Mapped[str | None] = mapped_column(String(120))
    data: Mapped[dict] = mapped_column(JSONB, server_default=sql("'{}'::jsonb"))
    occurred_at: Mapped[dt.datetime] = mapped_column(TZ)                # browser clock, clamped by the server
    received_at: Mapped[dt.datetime] = _now()
    __table_args__ = (
        CheckConstraint("type ~ '^[a-z_]{1,32}$'", name="type_format"),  # allowlist lives in the app (EventType)
        CheckConstraint(_json_object("data"), name="data_object"),
        Index("ix_site_events_visitor_occurred", "visitor_id", "occurred_at"),
        Index("ix_site_events_session", "session_id"),
        Index("ix_site_events_type_received", "type", "received_at"),
        Index("ix_site_events_received", "received_at"),
    )


# ---------------------------------------------------------------- admin users
class AdminUser(Base):
    __tablename__ = "admin_users"
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    login: Mapped[str] = mapped_column(String(100))                     # unique case-insensitively
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str | None] = mapped_column(String(300))      # NULL for service accounts (API keys only)
    role: Mapped[str] = mapped_column(String(16))
    is_service: Mapped[bool] = mapped_column(Boolean, server_default=sql("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=sql("true"))
    created_at: Mapped[dt.datetime] = _now()
    last_login_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    __table_args__ = (
        CheckConstraint(check("role", Role), name="role"),
        Index("uq_admin_users_lower_login", func.lower(sql("login")), unique=True),
    )


class AdminToken(Base):
    """Login sessions (expire) and service API keys (no expiry, revocable). Only SHA-256 of the token is stored."""
    __tablename__ = "admin_tokens"
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(10))                       # session | api_key
    label: Mapped[str | None] = mapped_column(String(100))              # «Админ-панель», for API keys
    user_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[dt.datetime] = _now()
    expires_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    user: Mapped[AdminUser] = relationship(lazy="joined")
    __table_args__ = (
        CheckConstraint("kind IN ('session', 'api_key')", name="kind"),
        CheckConstraint("char_length(token_hash) = 64", name="hash_len"),
    )


# ---------------------------------------------------------------- leads
class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)   # «Заявка №123» for managers
    public_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True,
                                                 server_default=sql("gen_random_uuid()"))
    created_at: Mapped[dt.datetime] = _now()
    updated_at: Mapped[dt.datetime] = _now()
    version: Mapped[int] = mapped_column(Integer, server_default="1")  # optimistic locking for the admin panel
    origin: Mapped[str] = mapped_column(String(16), server_default=Origin.site_form.value)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))

    # what the person asked for (raw inputs are kept even when the catalog does not know them)
    kind: Mapped[str] = mapped_column(String(16))
    breed_id: Mapped[int | None] = mapped_column(ForeignKey("breeds.id", ondelete="RESTRICT"))
    breed_input: Mapped[str | None] = mapped_column(String(100))
    puppy_id: Mapped[int | None] = mapped_column(Integer)
    puppy_slug: Mapped[str | None] = mapped_column(String(120))
    puppy_name: Mapped[str | None] = mapped_column(String(100))
    colour: Mapped[str | None] = mapped_column(String(40))              # colour slug from breedsub.json: kremovyj
    note: Mapped[str | None] = mapped_column(String(300))               # hidden note of the button
    form_title: Mapped[str | None] = mapped_column(String(200))         # title of the modal the person saw
    details: Mapped[dict] = mapped_column(JSONB, server_default=sql("'{}'::jsonb"))  # quiz result, extras

    # who (NULL only after the person was erased: the request stays in the statistics without personal data)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="RESTRICT"))
    name: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(16))
    anonymised_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    channel: Mapped[str] = mapped_column(String(16))
    is_repeat: Mapped[bool] = mapped_column(Boolean, server_default=sql("false"))  # the contact existed before

    # where from (visitor/session are soft links: no FK, an analytics row must never block a lead)
    page_path: Mapped[str | None] = mapped_column(String(300))
    page_title: Mapped[str | None] = mapped_column(String(200))
    referrer_host: Mapped[str | None] = mapped_column(String(200))
    landing_path: Mapped[str | None] = mapped_column(String(300))      # first page of the visit
    utm: Mapped[dict | None] = mapped_column(JSONB)
    source: Mapped[str | None] = mapped_column(String(60))              # last touch: yandex / google / (direct) …
    medium: Mapped[str | None] = mapped_column(String(60))              # organic / cpc / referral / social …
    visitor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    # consent (152-ФЗ): the document version the form showed; the proof row is in `consents`.
    # Manual leads (a phone call) have none: processing to answer a request needs no consent (ст. 6 ч. 1 п. 5).
    consent_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    consent_version: Mapped[str | None] = mapped_column(ForeignKey("consent_versions.version", ondelete="RESTRICT"))
    ip: Mapped[str | None] = mapped_column(INET)                        # wiped after keep_ip_days
    user_agent: Mapped[str | None] = mapped_column(String(400))

    # dedup / anti-spam
    idempotency_key: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True)
    request_sha256: Mapped[str | None] = mapped_column(String(64))
    spam_reason: Mapped[str | None] = mapped_column(String(20))         # why status = spam
    flags: Mapped[list] = mapped_column(JSONB, server_default=sql("'[]'::jsonb"))  # soft signals: too_fast, no_origin…

    # work
    status: Mapped[str] = mapped_column(String(16), server_default=LeadStatus.new.value)
    status_changed_at: Mapped[dt.datetime] = _now()
    last_activity_at: Mapped[dt.datetime] = _now()                     # new request attached, comment, status
    first_response_at: Mapped[dt.datetime | None] = mapped_column(TZ)  # first manager action
    next_contact_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    closed_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    lost_reason: Mapped[str | None] = mapped_column(String(20))
    sale_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(12, 2))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))

    contact: Mapped[Contact] = relationship(lazy="joined")
    breed: Mapped[Breed | None] = relationship(lazy="joined")
    puppy: Mapped[Puppy | None] = relationship(lazy="joined", viewonly=True,
                                               primaryjoin="Lead.puppy_id == Puppy.id",
                                               foreign_keys="Lead.puppy_id")
    assignee: Mapped[AdminUser | None] = relationship(lazy="joined")

    __table_args__ = (
        # a puppy always belongs to the lead's breed, so the lead sits in the right per-breed base
        # ON UPDATE CASCADE: when puppies.json moves a puppy to another breed, its requests move with it
        ForeignKeyConstraint(["puppy_id", "breed_id"], ["puppies.id", "puppies.breed_id"], ondelete="RESTRICT",
                             onupdate="CASCADE", name="fk_leads_puppy_breed"),
        CheckConstraint("puppy_id IS NULL OR breed_id IS NOT NULL", name="puppy_needs_breed"),
        CheckConstraint(check("kind", LeadKind), name="kind"),
        CheckConstraint(check("status", LeadStatus), name="status"),
        CheckConstraint(check("origin", Origin), name="origin"),
        CheckConstraint(check("channel", Channel), name="channel"),
        CheckConstraint(check("lost_reason", LostReason, nullable=True), name="lost_reason"),
        CheckConstraint(check("spam_reason", SpamReason, nullable=True), name="spam_reason"),
        CheckConstraint("phone IS NULL OR " + PHONE_CHECK, name="phone_e164"),
        CheckConstraint("anonymised_at IS NOT NULL OR (contact_id IS NOT NULL AND name IS NOT NULL "
                        "AND phone IS NOT NULL)", name="person_or_anonymised"),
        CheckConstraint("jsonb_typeof(flags) = 'array'", name="flags_array"),
        CheckConstraint("colour IS NULL OR colour ~ '^[a-z][a-z-]{0,39}$'", name="colour_slug"),
        CheckConstraint(_json_object("details"), name="details_object"),
        CheckConstraint("origin <> 'site_form' OR (consent_at IS NOT NULL AND consent_version IS NOT NULL)",
                        name="site_form_consent"),
        CheckConstraint("sale_amount IS NULL OR sale_amount >= 0", name="sale_amount"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="parent_not_self"),
        Index("ix_leads_created", sql("created_at DESC"), sql("id DESC")),
        Index("ix_leads_breed_created", "breed_id", sql("created_at DESC")),
        Index("ix_leads_status_created", "status", sql("created_at DESC")),
        Index("ix_leads_contact_created", "contact_id", sql("created_at DESC")),
        Index("ix_leads_puppy", "puppy_id", postgresql_where=sql("puppy_id IS NOT NULL")),
        Index("ix_leads_assignee_status", "assignee_id", "status", postgresql_where=sql("assignee_id IS NOT NULL")),
        Index("ix_leads_parent", "parent_id", postgresql_where=sql("parent_id IS NOT NULL")),
        Index("ix_leads_visitor", "visitor_id", postgresql_where=sql("visitor_id IS NOT NULL")),
        Index("ix_leads_next_contact", "next_contact_at", postgresql_where=sql("next_contact_at IS NOT NULL")),
        Index("ix_leads_ip_created", "ip", "created_at"),
    )


class LeadHistory(Base):
    """Append-only activity feed and audit log of a lead."""
    __tablename__ = "lead_history"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    at: Mapped[dt.datetime] = _now()
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    actor_label: Mapped[str] = mapped_column(String(100))              # snapshot: «Анна», «Система», «Админ-панель»
    action: Mapped[str] = mapped_column(String(20))
    old_value: Mapped[str | None] = mapped_column(String(300))
    new_value: Mapped[str | None] = mapped_column(String(300))
    comment: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint(check("action", HistoryAction), name="action"),
        Index("ix_lead_history_lead_at", "lead_id", "at"),
    )


# ---------------------------------------------------------------- reviews
class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    created_at: Mapped[dt.datetime] = _now()
    updated_at: Mapped[dt.datetime] = _now()
    name: Mapped[str | None] = mapped_column(String(100))               # as typed, never published
    display_name: Mapped[str] = mapped_column(String(60))               # «Анна К.» — what the site shows
    phone: Mapped[str | None] = mapped_column(String(16))               # the author's contact, never published
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), index=True)
    city: Mapped[str | None] = mapped_column(String(100))
    breed_id: Mapped[int | None] = mapped_column(ForeignKey("breeds.id", ondelete="RESTRICT"))
    rating: Mapped[int] = mapped_column(SmallInteger)
    text: Mapped[str | None] = mapped_column(Text)                      # NULL once withdrawn (anonymised)
    status: Mapped[str] = mapped_column(String(16), server_default=ReviewStatus.pending.value)
    moderated_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    moderated_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    moderator_note: Mapped[str | None] = mapped_column(String(300))
    withdrawn_at: Mapped[dt.datetime | None] = mapped_column(TZ)        # the author asked to stop publication
    page_path: Mapped[str | None] = mapped_column(String(300))
    visitor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ip: Mapped[str | None] = mapped_column(INET)                        # wiped after keep_ip_days
    user_agent: Mapped[str | None] = mapped_column(String(400))
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    request_sha256: Mapped[str | None] = mapped_column(String(64))
    spam_reason: Mapped[str | None] = mapped_column(String(20))
    breed: Mapped[Breed | None] = relationship(lazy="joined")
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating"),
        CheckConstraint(check("status", ReviewStatus), name="status"),
        CheckConstraint(check("spam_reason", SpamReason, nullable=True), name="spam_reason"),
        CheckConstraint("char_length(text) <= 4000", name="text_len"),
        CheckConstraint("phone IS NULL OR " + PHONE_CHECK, name="phone_e164"),
        CheckConstraint("status = 'withdrawn' OR (name IS NOT NULL AND text IS NOT NULL)", name="content_or_withdrawn"),
        Index("ix_reviews_status_created", "status", sql("created_at DESC")),
        Index("ix_reviews_ip_created", "ip", "created_at"),
    )


# ---------------------------------------------------------------- notifications
class Outbox(Base):
    """Notifications to managers. Written in the same transaction as the lead, sent after commit, retried by the
    worker with backoff. The message is rendered from the lead at send time (no copy of personal data here)."""
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    created_at: Mapped[dt.datetime] = _now()
    channel: Mapped[str] = mapped_column(String(16))                    # telegram | email | webhook
    target: Mapped[str] = mapped_column(String(300))                    # chat id | address | URL
    event: Mapped[str] = mapped_column(String(32))                      # lead.created | lead.repeat | lead.updated …
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    review_id: Mapped[int | None] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    next_attempt_at: Mapped[dt.datetime] = _now()
    last_error: Mapped[str | None] = mapped_column(String(500))
    sent_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'sent', 'failed')", name="status"),
        CheckConstraint("channel IN ('telegram', 'email', 'webhook')", name="channel"),
        CheckConstraint("num_nonnulls(lead_id, review_id) = 1", name="one_subject"),
        CheckConstraint("attempts >= 0", name="attempts"),
        Index("ix_outbox_due", "next_attempt_at", postgresql_where=sql("status = 'pending'")),
        Index("uq_outbox_lead_created", "lead_id", "channel", "target", unique=True,
              postgresql_where=sql("event = 'lead.created'")),
        Index("uq_outbox_review_created", "review_id", "channel", "target", unique=True,
              postgresql_where=sql("event = 'review.created'")),
    )


# ---------------------------------------------------------------- audit (no personal data)
class AuditLog(Base):
    """Exports, erasures, merges, logins: who did what with personal data (152-ФЗ accountability)."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[dt.datetime] = _now()
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    actor_label: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(32))     # login | login_failed | export | erase | merge | view_contact…
    target: Mapped[str | None] = mapped_column(String(100))            # «lead:12», «contact:5»
    ip: Mapped[str | None] = mapped_column(INET)
    details: Mapped[dict] = mapped_column(JSONB, server_default=sql("'{}'::jsonb"))
    __table_args__ = (Index("ix_audit_log_at", "at"),)


class ErasureLog(Base):
    """Record of destroyed personal data (акт об уничтожении ПД, Приказ РКН № 179), kept for 3 years."""
    __tablename__ = "erasure_log"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[dt.datetime] = _now()
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    actor_label: Mapped[str] = mapped_column(String(100))
    subject: Mapped[str] = mapped_column(String(200))                  # whose data, as the request names the person
    reason: Mapped[str] = mapped_column(String(20))                    # withdrawal | request | retention | not_me
    categories: Mapped[list] = mapped_column(JSONB)                    # what was destroyed
    counts: Mapped[dict] = mapped_column(JSONB)                        # rows per table
    # keyed hashes (HMAC) of the destroyed phone numbers: after restoring an older backup,
    # `python -m app reapply-erasures` destroys these people again (no phone is kept in clear)
    phone_hashes: Mapped[list] = mapped_column(JSONB, server_default=sql("'[]'::jsonb"))
    method: Mapped[str] = mapped_column(String(100), server_default="удаление и обезличивание записей в СУБД")
    __table_args__ = (CheckConstraint("reason IN ('withdrawal', 'request', 'retention', 'not_me')", name="reason"),)


# ---------------------------------------------------------------- rate limiting (UNLOGGED, fixed 1-minute windows)
class RateLimit(Base):
    """Login attempts (per login and per IP). Public forms are limited by nginx and by counts in leads/reviews."""
    __tablename__ = "rate_limits"
    bucket: Mapped[str] = mapped_column(String(160), primary_key=True)  # «lead:203.0.113.5», «login:anna»
    window_start: Mapped[dt.datetime] = mapped_column(TZ, primary_key=True)
    hits: Mapped[int] = mapped_column(Integer)
    __table_args__ = ({"prefixes": ["UNLOGGED"]},)


__all__ = ["Base", "ConsentVersion", "Consent", "ErasureLog", "Breed", "Puppy", "Contact", "ContactAlias", "Visitor", "Visit", "SiteEvent",
           "AdminUser", "AdminToken", "Lead", "LeadHistory", "Review", "Outbox", "AuditLog", "RateLimit"]
