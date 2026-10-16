"""Contacts in the admin panel: list, card, edit, merge two records of one person, erase a person (152-ФЗ)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from ..enums import OPEN_STATUSES, HistoryAction
from ..errors import ApiError
from ..models import (AdminUser, Consent, Contact, ContactAlias, ErasureLog, Lead, LeadHistory, Outbox, SiteEvent,
                      Visit, Visitor)
from .. import schemas_admin as sa
from . import phone as phones
from .admin_leads import _like, contact_links, to_row
from .auth import audit

UTC = dt.timezone.utc


def _counts(db: Session, ids: list[int]) -> tuple[dict[int, int], dict[int, int]]:
    if not ids:
        return {}, {}
    total = dict(db.execute(select(Lead.contact_id, func.count()).where(Lead.contact_id.in_(ids))
                            .group_by(Lead.contact_id)).all())
    open_ = dict(db.execute(select(Lead.contact_id, func.count())
                            .where(Lead.contact_id.in_(ids), Lead.parent_id.is_(None),
                                   Lead.status.in_([x.value for x in OPEN_STATUSES]))
                            .group_by(Lead.contact_id)).all())
    return total, open_


def _row(c: Contact, total: int = 0, open_: int = 0) -> sa.ContactRow:
    r = sa.ContactRow.model_validate(c)
    r.phone_display, r.leads_count, r.open_leads = phones.display(c.phone), total, open_
    return r


def get(db: Session, contact_id: int) -> Contact:
    c = db.get(Contact, contact_id)
    if c is None:
        raise ApiError(404, "not_found", "Контакт не найден")
    return c


def list_contacts(db: Session, q: str | None, blocked: bool | None, page: int, per_page: int) -> sa.Page:
    cond = []
    if q:
        digits = "".join(ch for ch in q if ch.isdigit())
        sub = [Contact.name.ilike(f"%{_like(q.strip())}%")]
        if len(digits) >= 4:
            sub.append(Contact.phone.like(f"%{digits[-10:]}%"))
            sub.append(Contact.id.in_(select(ContactAlias.contact_id).where(ContactAlias.phone.like(f"%{digits[-10:]}%"))))
        cond.append(or_(*sub))
    if blocked is not None:
        cond.append(Contact.is_blocked.is_(blocked))
    total = db.scalar(select(func.count()).select_from(Contact).where(*cond)) or 0
    rows = db.scalars(select(Contact).where(*cond).order_by(Contact.last_seen_at.desc(), Contact.id.desc())
                      .offset((page - 1) * per_page).limit(per_page)).all()
    t, o = _counts(db, [c.id for c in rows])
    return sa.Page[sa.ContactRow](items=[_row(c, t.get(c.id, 0), o.get(c.id, 0)) for c in rows], total=total,
                                  page=page, per_page=per_page)


def detail(db: Session, contact_id: int, user: AdminUser, ip: str | None, label: str | None = None) -> sa.ContactDetail:
    c = get(db, contact_id)
    leads = db.scalars(select(Lead).where(Lead.contact_id == c.id).order_by(Lead.created_at.desc())).unique().all()
    t, o = _counts(db, [c.id])
    aliases = db.scalars(select(ContactAlias.phone).where(ContactAlias.contact_id == c.id)).all()
    consents = db.execute(select(Consent.version, Consent.given_at, Consent.lead_id, Consent.withdrawn_at)
                          .where(Consent.contact_id == c.id).order_by(Consent.given_at)).all()
    audit(db, user, "view_contact", target=f"contact:{c.id}", ip=ip, actor_label=label)
    db.commit()
    base = _row(c, t.get(c.id, 0), o.get(c.id, 0)).model_dump()
    return sa.ContactDetail(**base, leads=[to_row(l) for l in leads], aliases=list(aliases),
                            consents=[{"version": v, "given_at": g.isoformat(), "lead_id": lid,
                                       "withdrawn_at": w.isoformat() if w else None} for v, g, lid, w in consents],
                            links=contact_links(c.phone, c.preferred_channel, c.telegram_username))


def patch(db: Session, contact_id: int, p: sa.ContactPatch, user: AdminUser, label: str | None = None) -> Contact:
    c = get(db, contact_id)
    for f in p.model_fields_set:
        v = getattr(p, f)
        if f == "preferred_channel" and v is not None:
            v = v.value
        if f == "telegram_username" and v:
            v = v.lstrip("@")
        setattr(c, f, v)
    audit(db, user, "contact_edit", target=f"contact:{c.id}", actor_label=label, fields=sorted(p.model_fields_set))
    db.commit()
    db.refresh(c)
    return c


def events(db: Session, contact_id: int, before_id: int | None, limit: int) -> list[SiteEvent]:
    """Site activity of the person's browsers (cursor pagination: pass the last id as before_id)."""
    get(db, contact_id)
    vids = select(Lead.visitor_id).where(Lead.contact_id == contact_id, Lead.visitor_id.is_not(None))
    q = select(SiteEvent).where(SiteEvent.visitor_id.in_(vids))
    if before_id:
        q = q.where(SiteEvent.id < before_id)
    return db.scalars(q.order_by(SiteEvent.id.desc()).limit(limit)).all()


def merge(db: Session, contact_id: int, into_id: int, user: AdminUser, label: str) -> Contact:
    """Move everything of `contact_id` into `into_id`; the old phone becomes an alias of the surviving contact."""
    if contact_id == into_id:
        raise ApiError(422, "validation", "Нельзя склеить контакт сам с собой", {"into_id": "Другой контакт"})
    src, dst = get(db, contact_id), get(db, into_id)
    db.execute(select(Contact.id).where(Contact.id.in_([src.id, dst.id])).with_for_update())
    moved = db.execute(update(Lead).where(Lead.contact_id == src.id).values(contact_id=dst.id)
                       .returning(Lead.id)).scalars().all()
    db.execute(update(Consent).where(Consent.contact_id == src.id).values(contact_id=dst.id))
    db.execute(update(ContactAlias).where(ContactAlias.contact_id == src.id).values(contact_id=dst.id))
    for lid in moved:
        db.add(LeadHistory(lead_id=lid, action=HistoryAction.merged.value, actor_id=user.id, actor_label=label[:100],
                           old_value=f"контакт {src.id}", new_value=f"контакт {dst.id}"))
    old_phone = src.phone
    dst.first_seen_at = min(dst.first_seen_at, src.first_seen_at)
    dst.last_seen_at = max(dst.last_seen_at, src.last_seen_at)
    if src.notes:
        dst.notes = ((dst.notes + "\n\n") if dst.notes else "") + f"[из контакта {src.id}] {src.notes}"
    dst.telegram_username = dst.telegram_username or src.telegram_username
    db.delete(src)
    db.flush()
    db.add(ContactAlias(phone=old_phone, contact_id=dst.id))
    audit(db, user, "merge", target=f"contact:{dst.id}", actor_label=label, merged=src.id, leads=len(moved))
    db.commit()
    db.refresh(dst)
    return dst


def erase(db: Session, contact_id: int, reason: str, subject: str, user: AdminUser | None, label: str) -> dict:
    """Destroy the person's data (withdrawal of consent, a request, end of retention):
    - requests stay in the statistics without personal data (name, phone, note, IP, pages, comments are cleared);
    - the contact, its aliases and consents, the linked browsers with their visits and events, pending
      notifications are deleted;
    - an erasure record (акт об уничтожении ПД) is written and kept for 3 years."""
    c = get(db, contact_id)
    now = dt.datetime.now(UTC)
    lead_ids = db.scalars(select(Lead.id).where(Lead.contact_id == c.id)).all()
    visitor_ids = [v for v in db.scalars(select(Lead.visitor_id).where(Lead.contact_id == c.id,
                                                                      Lead.visitor_id.is_not(None)).distinct())]
    counts = {"leads_anonymised": len(lead_ids)}
    counts["comments_cleared"] = db.execute(update(LeadHistory).where(LeadHistory.lead_id.in_(lead_ids),
                                                                     LeadHistory.comment.is_not(None))
                                            .values(comment=None)).rowcount
    db.execute(update(LeadHistory).where(LeadHistory.lead_id.in_(lead_ids), LeadHistory.action.in_(["merged"]))
               .values(old_value=None, new_value=None))
    counts["notifications_deleted"] = db.execute(delete(Outbox).where(Outbox.lead_id.in_(lead_ids))).rowcount
    db.execute(update(Lead).where(Lead.id.in_(lead_ids)).values(
        contact_id=None, name=None, phone=None, note=None, form_title=None, details={}, ip=None, user_agent=None,
        referrer_host=None, page_title=None, visitor_id=None, session_id=None, utm=None, idempotency_key=None,
        request_sha256=None, anonymised_at=now, version=Lead.version + 1))
    counts["consents_deleted"] = db.execute(delete(Consent).where(Consent.contact_id == c.id)).rowcount
    counts["aliases_deleted"] = db.execute(delete(ContactAlias).where(ContactAlias.contact_id == c.id)).rowcount
    if visitor_ids:
        counts["events_deleted"] = db.execute(delete(SiteEvent).where(SiteEvent.visitor_id.in_(visitor_ids))).rowcount
        counts["visits_deleted"] = db.execute(delete(Visit).where(Visit.visitor_id.in_(visitor_ids))).rowcount
        counts["browsers_deleted"] = db.execute(delete(Visitor).where(Visitor.id.in_(visitor_ids))).rowcount
    db.delete(c)
    counts["contacts_deleted"] = 1
    db.add(ErasureLog(actor_id=user.id if user else None, actor_label=label[:100], subject=subject[:200],
                      reason=reason, counts=counts,
                      categories=["имя", "номер телефона", "способ связи", "сведения из заявок", "IP-адрес",
                                  "сведения о браузере", "история посещения сайта", "согласия", "комментарии"]))
    audit(db, user, "erase", target=f"contact:{contact_id}", actor_label=label, reason=reason, **counts)
    db.commit()
    return counts
