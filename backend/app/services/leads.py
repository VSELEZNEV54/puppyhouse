"""Creating requests (from the site forms and by managers) — the one write path into `leads`.

Guarantees:
- a request is never lost because of an optional field: only name / phone / contact / consent can fail validation;
  unknown breed, puppy, colour or kind are kept as raw text;
- one transaction: contact upsert (INSERT … ON CONFLICT, which also locks the person's row so two parallel requests
  of one person are serialised), lead insert (ON CONFLICT on the idempotency key), history, consent proof, outbox;
- the same idempotency key with the same payload returns the first request (200), with another payload → 409;
- a repeat request of the same person and breed while an earlier one is open becomes a child (`parent_id`, status
  `duplicate`) of that lead, so managers work one card per person and breed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..enums import OPEN_STATUSES, Channel, HistoryAction, LeadKind, LeadStatus, Origin, SpamReason
from ..errors import ApiError
from ..models import AdminUser, Breed, Contact, ContactAlias, Lead, LeadHistory, Puppy
from . import attribution, catalog, consent, notify, sanitize, tracking
from .security import same_client

log = logging.getLogger("dsh.leads")
UTC = dt.timezone.utc
COLOUR_SLUG = re.compile(r"^[a-z][a-z-]{0,39}$")
PUPPY_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,119}$")
SYSTEM = "Сайт"


@dataclass
class RequestCtx:
    ip: str | None = None
    user_agent: str | None = None
    origin_missing: bool = False


@dataclass
class Created:
    lead: Lead
    created: bool                      # False: idempotent replay of an earlier request
    notified: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- helpers
def _hist(db: Session, lead_id: int, action: HistoryAction, *, actor_id=None, actor_label=SYSTEM, old=None,
          new=None, comment=None) -> None:
    db.add(LeadHistory(lead_id=lead_id, action=action.value, actor_id=actor_id, actor_label=actor_label[:100],
                       old_value=None if old is None else str(old)[:300],
                       new_value=None if new is None else str(new)[:300], comment=comment))


def request_hash(payload: dict) -> str:
    keys = ("kind", "name", "phone", "contact", "breed", "puppy", "colour", "note")
    canon = json.dumps({k: payload.get(k) for k in keys}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canon.encode()).hexdigest()


def lock_phone(db: Session, phone: str | None) -> None:
    """Transaction-level lock on one phone number (requests, merges and erasures of the same person serialise)."""
    if phone:
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": "phone:" + phone})


def upsert_contact(db: Session, phone: str, name: str, channel: str | None) -> tuple[int, bool]:
    """(contact id, created?) — atomic; an alias phone of a merged contact resolves to the surviving contact.
    A form never renames an existing contact (anyone who knows a number could otherwise rename that person)."""
    lock_phone(db, phone)  # a merge or an erasure of this number cannot interleave with this request
    alias = db.scalar(select(ContactAlias.contact_id).where(ContactAlias.phone == phone))
    if alias:
        n = db.execute(update(Contact).where(Contact.id == alias)
                       .values(last_seen_at=func.now(),
                               preferred_channel=func.coalesce(channel, Contact.preferred_channel))).rowcount
        if n:
            return alias, False
        # the alias pointed at a contact deleted a moment ago (erased): its alias row went with it — start afresh
    stmt = insert(Contact).values(phone=phone, name=name, preferred_channel=channel)
    stmt = stmt.on_conflict_do_update(index_elements=[Contact.phone], set_={
        "last_seen_at": func.now(),
        "preferred_channel": func.coalesce(stmt.excluded.preferred_channel, Contact.preferred_channel),
    }).returning(Contact.id, text("(xmax = 0) AS created"))
    row = db.execute(stmt).one()
    return row[0], bool(row[1])


def resolve_catalog(db: Session, breed: str | None, puppy: str | None) -> tuple[Breed | None, Puppy | None]:
    """Best effort: a puppy slug wins (its breed is used); then a breed slug, key or Russian name."""
    pup = None
    if puppy and PUPPY_SLUG.match(puppy):
        pup = db.scalar(select(Puppy).where(Puppy.slug == puppy))
    if pup is not None:
        return pup.breed, pup
    k = catalog.norm(breed)
    if not k or k in ("undecided", catalog.norm(catalog.UNDECIDED)):
        return None, None
    b = db.scalar(select(Breed).where((Breed.slug == k) | (Breed.key == k) | (func.lower(Breed.name) == k)))
    if b is None:  # «ё» and spacing variants of the Russian name
        for row in db.scalars(select(Breed)):
            if catalog.norm(row.name) == k:
                return row, None
    return b, None


def find_open_parent(db: Session, contact_id: int, breed_id: int | None, before: dt.datetime) -> Lead | None:
    s = get_settings()
    q = (select(Lead).where(Lead.contact_id == contact_id, Lead.parent_id.is_(None),
                            Lead.status.in_([x.value for x in OPEN_STATUSES]),
                            Lead.created_at >= before - dt.timedelta(days=s.repeat_window_days))
         .order_by(Lead.created_at.desc()).limit(1))
    q = q.where(Lead.breed_id.is_(None) if breed_id is None else Lead.breed_id == breed_id)
    # FOR UPDATE: a parent a manager is closing right now is re-checked after their commit and skipped
    return db.scalars(q.with_for_update(of=Lead)).first()


def _count(db: Session, *where) -> int:
    return db.scalar(select(func.count()).select_from(Lead).where(*where)) or 0


# ---------------------------------------------------------------- public create
def create_from_site(db: Session, data, ctx: RequestCtx) -> Created:
    """data: schemas_public.LeadIn (already validated). Commits."""
    s = get_settings()
    now = dt.datetime.now(UTC)
    payload = data.model_dump()
    key = data.idempotency_key or uuid.uuid4()
    rhash = request_hash(payload)

    existing = db.scalar(select(Lead).where(Lead.idempotency_key == key))
    if existing is not None:
        if existing.request_sha256 and existing.request_sha256 != rhash:
            raise ApiError(409, "idempotency_conflict", "Эта заявка уже отправлена с другими данными")
        return Created(existing, False)

    details: dict = {}
    try:
        kind = LeadKind(data.kind) if data.kind else LeadKind.price
    except ValueError:
        kind = LeadKind.other
        details["kind_raw"] = sanitize.clean(str(data.kind), 40)

    breed_input = sanitize.clean(data.breed, 100)
    puppy_slug = sanitize.clean(data.puppy, 120)
    breed, pup = resolve_catalog(db, breed_input, puppy_slug)
    colour = sanitize.clean(data.colour, 60)
    if colour and not COLOUR_SLUG.match(colour):
        details["colour_raw"] = colour
        colour = None
    if data.quiz:
        q = {k: sanitize.clean(str(v), 40) for k, v in data.quiz.items() if k in ("winner", "second") and v}
        if q:
            details["quiz"] = q

    flags: list[str] = []
    if data.elapsed_ms is not None and data.elapsed_ms < s.min_fill_ms:
        flags.append("too_fast")
    if ctx.origin_missing:
        flags.append("no_origin")
    if ctx.ip and _count(db, same_client(Lead.ip, ctx.ip),
                         Lead.created_at > now - dt.timedelta(minutes=10)) >= s.leads_per_ip_10min:
        flags.append("rate_ip")

    consent_ver = consent.current("processing")
    if data.consent_version and data.consent_version != consent_ver:
        doc = consent.load()["versions"].get(data.consent_version)
        if doc and doc["kind"] == "processing":
            consent_ver = data.consent_version  # an older page the person actually saw
        else:
            flags.append("consent_version_fallback")

    name = sanitize.clean(data.name, 100) or "—"
    channel = Channel(data.contact).value
    contact_id, contact_created = upsert_contact(db, data.phone, name, channel)
    contact = db.get(Contact, contact_id)

    status, spam_reason, parent = LeadStatus.new, None, None
    if contact.is_blocked:
        status, spam_reason = LeadStatus.spam, SpamReason.blocked_contact
    else:
        recent_hour = _count(db, Lead.contact_id == contact_id, Lead.created_at > now - dt.timedelta(hours=1))
        recent_day = _count(db, Lead.contact_id == contact_id, Lead.created_at > now - dt.timedelta(days=1))
        if recent_hour >= s.leads_per_phone_hour or recent_day >= s.leads_per_phone_day:
            flags.append("rate_phone")
        parent = find_open_parent(db, contact_id, breed.id if breed else None, now)
        if parent is not None:
            status = LeadStatus.duplicate

    utm = attribution.clean_utm(data.utm)
    ref_host = sanitize.host(data.referrer)
    if ref_host and any(ref_host == h or ref_host.endswith("." + h) for h in s.own_hosts):
        ref_host = None
    source, medium = attribution.classify(utm, f"https://{ref_host}/" if ref_host else None, tuple(s.own_hosts))
    page_path = sanitize.path(data.page.path, s.site_base_paths)

    visitor_id = data.visitor_id if s.link_site_activity else None
    session_id = data.session_id if s.link_site_activity else None
    if visitor_id:
        tracking.touch_visitor(db, visitor_id, landing=sanitize.path(data.first_landing or data.landing,
                                                                     s.site_base_paths),
                               referrer_host=sanitize.host(data.first_referrer) or ref_host,
                               utm=attribution.clean_utm(data.first_utm) or utm, ym_uid=data.ym_uid)

    values = dict(
        origin=Origin.site_form.value, kind=kind.value, parent_id=parent.id if parent else None,
        breed_id=breed.id if breed else None, breed_input=breed_input,
        puppy_id=pup.id if pup else None, puppy_slug=puppy_slug, puppy_name=sanitize.clean(data.puppy_name, 100)
        or (pup.name if pup else None),
        colour=colour, note=sanitize.clean(data.note, 300), form_title=sanitize.clean(data.form_title, 200),
        details=details, contact_id=contact_id, name=name, phone=data.phone, channel=channel,
        is_repeat=not contact_created,
        page_path=page_path, page_title=sanitize.clean(data.page.title, 200), referrer_host=ref_host,
        landing_path=sanitize.path(data.landing, s.site_base_paths), utm=utm, source=source, medium=medium,
        visitor_id=visitor_id, session_id=session_id,
        consent_at=now, consent_version=consent_ver, ip=ctx.ip, user_agent=sanitize.clean(ctx.user_agent, 400),
        idempotency_key=key, request_sha256=rhash, spam_reason=spam_reason.value if spam_reason else None,
        flags=flags, status=status.value,
    )
    row = db.execute(insert(Lead).values(**values).on_conflict_do_nothing(index_elements=[Lead.idempotency_key])
                     .returning(Lead.id)).first()
    if row is None:  # a parallel request with the same key won the race
        db.rollback()
        existing = db.scalar(select(Lead).where(Lead.idempotency_key == key))
        if existing is None:
            raise ApiError(409, "idempotency_conflict", "Повторите отправку")
        if existing.request_sha256 and existing.request_sha256 != rhash:
            raise ApiError(409, "idempotency_conflict", "Эта заявка уже отправлена с другими данными")
        return Created(existing, False)
    lead_id = row[0]

    _hist(db, lead_id, HistoryAction.created, new=status.value,
          comment=f"Заявка №{parent.id}: повторный запрос" if parent else None)
    if parent is not None:
        parent.last_activity_at = now
        what = " · ".join(x for x in (kind.value, pup.name if pup else None, colour) if x)
        _hist(db, parent.id, HistoryAction.repeat, new=f"№{lead_id}", comment=f"Повторный запрос: {what}")
    consent.record(db, version=consent_ver, contact_id=contact_id, lead_id=lead_id, page_path=page_path,
                   ip=ctx.ip, user_agent=ctx.user_agent)
    db.flush()
    lead = db.get(Lead, lead_id)
    notified = []
    event = {LeadStatus.new: "lead.created", LeadStatus.duplicate: "lead.repeat"}.get(status)
    if event and "rate_phone" not in flags:
        try:  # a broken notification setting must never cost the request itself
            with db.begin_nested():
                notified = notify.enqueue_lead(db, lead, event)
        except Exception:  # noqa: BLE001
            log.exception("could not queue notifications for lead %s", lead_id)
            notified = []
    db.commit()
    return Created(lead, True, notified)


# ---------------------------------------------------------------- manual create (admin)
def create_manual(db: Session, data, actor_id: int, actor_label: str) -> Lead:
    """A request a manager took by phone / in a messenger. No consent row: answering a request the person made
    needs no consent (ст. 6 ч. 1 п. 5 152-ФЗ)."""
    if data.assignee_id is not None:
        who = db.get(AdminUser, data.assignee_id)
        if who is None or not who.is_active or who.is_service:
            raise ApiError(422, "validation", "Нет такого менеджера", {"assignee_id": "Неизвестный менеджер"})
    breed, pup = resolve_catalog(db, data.breed, data.puppy)
    contact_id, created = upsert_contact(db, data.phone, data.name, data.channel)
    now = dt.datetime.now(UTC)
    parent = find_open_parent(db, contact_id, breed.id if breed else None, now)
    status = LeadStatus.duplicate if parent and data.attach_to_open else LeadStatus.new
    lead = Lead(origin=data.origin, kind=data.kind, parent_id=parent.id if status == LeadStatus.duplicate else None,
                breed_id=breed.id if breed else None, breed_input=data.breed, puppy_id=pup.id if pup else None,
                puppy_slug=data.puppy, puppy_name=pup.name if pup else None, colour=data.colour, note=data.note,
                details={}, contact_id=contact_id, name=data.name, phone=data.phone, channel=data.channel,
                is_repeat=not created, status=status.value, assignee_id=data.assignee_id or actor_id,
                first_response_at=now, flags=[])
    db.add(lead)
    db.flush()
    _hist(db, lead.id, HistoryAction.created, actor_id=actor_id, actor_label=actor_label, new=status.value,
          comment=f"Добавлена вручную: {data.origin}")
    if parent is not None and status == LeadStatus.duplicate:
        parent.last_activity_at = now
        _hist(db, parent.id, HistoryAction.repeat, actor_id=actor_id, actor_label=actor_label, new=f"№{lead.id}")
    notify.enqueue_lead(db, lead, "lead.created", channels=("webhook",))
    db.commit()
    return db.get(Lead, lead.id)
