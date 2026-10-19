"""Contacts in the admin panel: list, card, edit, merge two records of one person, erase a person (152-ФЗ)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..enums import OPEN_STATUSES, HistoryAction, LeadStatus
from ..errors import ApiError
from ..models import (AdminUser, Consent, Contact, ContactAlias, ErasureLog, Lead, LeadHistory, Outbox, Review,
                      SiteEvent, Visit, Visitor)
from .. import schemas_admin as sa
from . import phone as phones
from . import phone as phones_mod
from . import security
from .admin_leads import _like, contact_links, to_row
from .auth import audit
from .leads import lock_phone

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
    # only what the person did up to their latest request from that browser: the consent covers pages viewed
    # before a request, not the anonymous visits after it
    last = (select(Lead.visitor_id.label("vid"), func.max(Lead.created_at).label("upto"))
            .where(Lead.contact_id == contact_id, Lead.visitor_id.is_not(None))
            .group_by(Lead.visitor_id).subquery())
    q = select(SiteEvent).join(last, and_(SiteEvent.visitor_id == last.c.vid, SiteEvent.occurred_at <= last.c.upto))
    if before_id:
        q = q.where(SiteEvent.id < before_id)
    return db.scalars(q.order_by(SiteEvent.id.desc()).limit(limit)).all()


def merge(db: Session, contact_id: int, into_id: int, user: AdminUser, label: str) -> Contact:
    """Move everything of `contact_id` into `into_id`; the old phone becomes an alias of the surviving contact."""
    if contact_id == into_id:
        raise ApiError(422, "validation", "Нельзя склеить контакт сам с собой", {"into_id": "Другой контакт"})
    src, dst = get(db, contact_id), get(db, into_id)
    for p in [src.phone, *db.scalars(select(ContactAlias.phone).where(ContactAlias.contact_id == src.id))]:
        lock_phone(db, p)  # a request from the merged number (or its old numbers) waits, then finds the alias
    db.execute(select(Contact.id).where(Contact.id.in_([src.id, dst.id])).order_by(Contact.id).with_for_update())
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
    dst.preferred_channel = dst.preferred_channel or src.preferred_channel
    dst.is_blocked = dst.is_blocked or src.is_blocked  # a blocked number stays blocked behind the alias
    db.delete(src)
    db.flush()
    db.execute(insert(ContactAlias).values(phone=old_phone, contact_id=dst.id)
               .on_conflict_do_update(index_elements=[ContactAlias.phone], set_={"contact_id": dst.id}))
    audit(db, user, "merge", target=f"contact:{dst.id}", actor_label=label, merged=src.id, leads=len(moved))
    db.commit()
    db.refresh(dst)
    return dst


def erase(db: Session, contact_id: int, reason: str, subject: str, user: AdminUser | None, label: str,
          stale_before: dt.datetime | None = None) -> dict | None:  # {"counts", "manual_steps"}
    """Destroy the person's data (withdrawal of consent, a request, end of retention):
    - requests stay in the statistics without personal data (name, phone, note, IP, pages, comments are cleared);
    - the contact, its aliases and consents, the linked browsers with their visits and events, pending
      notifications are deleted;
    - open requests are closed as «Отказ» (nobody can work them any more);
    - an erasure record (акт об уничтожении ПД) is written and kept for 3 years.
    - the person's reviews (linked or with the same phone) and their consents are deleted;
    - an erasure record (акт) with a keyed hash of every destroyed number is written (reapply-erasures).
    stale_before (retention): erase only if the person has not been seen and no request of theirs has moved since
    then — re-checked under the same locks a new request takes; returns None when skipped."""
    c = get(db, contact_id)
    for p in [c.phone, *db.scalars(select(ContactAlias.phone).where(ContactAlias.contact_id == c.id))]:
        lock_phone(db, p)  # requests from the number or an old number of this person wait for the erasure
    c = db.scalars(select(Contact).where(Contact.id == contact_id).with_for_update()).first()
    if c is None:
        raise ApiError(404, "not_found", "Контакт не найден")
    # lock the person's requests before clearing anything: a comment or edit in flight waits and then finds the
    # request anonymised (409) instead of writing text after the history was cleared
    db.execute(select(Lead.id).where(Lead.contact_id == c.id).with_for_update())
    if stale_before is not None:
        recent = db.scalar(select(func.count()).select_from(Lead).where(
            Lead.contact_id == c.id, Lead.last_activity_at >= stale_before)) or 0
        if c.last_seen_at >= stale_before or recent:
            db.rollback()
            return None
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
    open_rows = db.execute(select(Lead.id, Lead.status).where(
        Lead.id.in_(lead_ids), Lead.status.in_([x.value for x in OPEN_STATUSES]))).all()
    open_ids = [lid for lid, _ in open_rows]
    for lid, old in open_rows:  # no comment text: the reason is in erasure_log
        db.add(LeadHistory(lead_id=lid, action=HistoryAction.status.value, actor_id=user.id if user else None,
                           actor_label=label[:100], old_value=old, new_value=LeadStatus.lost.value))
    db.execute(update(Lead).where(Lead.id.in_(open_ids)).values(
        status=LeadStatus.lost.value, lost_reason="other", closed_at=now, status_changed_at=now,
        next_contact_at=None))
    counts["open_requests_closed"] = len(open_ids)
    db.execute(update(Lead).where(Lead.id.in_(lead_ids)).values(
        contact_id=None, name=None, phone=None, note=None, form_title=None, details={}, ip=None, user_agent=None,
        referrer_host=None, page_title=None, visitor_id=None, session_id=None, utm=None, idempotency_key=None,
        request_sha256=None, anonymised_at=now, version=Lead.version + 1))
    counts["consents_deleted"] = db.execute(delete(Consent).where(Consent.contact_id == c.id)).rowcount
    phones = [c.phone] + list(db.scalars(select(ContactAlias.phone).where(ContactAlias.contact_id == c.id)))
    counts["reviews_deleted"] = db.execute(delete(Review).where(
        or_(Review.contact_id == c.id, Review.phone.in_(phones)))).rowcount  # their consents go by CASCADE
    counts["aliases_deleted"] = db.execute(delete(ContactAlias).where(ContactAlias.contact_id == c.id)).rowcount
    if visitor_ids:
        counts["events_deleted"] = db.execute(delete(SiteEvent).where(SiteEvent.visitor_id.in_(visitor_ids))).rowcount
        counts["visits_deleted"] = db.execute(delete(Visit).where(Visit.visitor_id.in_(visitor_ids))).rowcount
        counts["browsers_deleted"] = db.execute(delete(Visitor).where(Visitor.id.in_(visitor_ids))).rowcount
    if reason == "retention" and subject.startswith("контакт №"):
        subject = f"{c.name}, {phones_mod.mask(c.phone)} (контакт №{c.id}; срок хранения истёк)"
    db.delete(c)
    counts["contacts_deleted"] = 1
    db.add(ErasureLog(actor_id=user.id if user else None, actor_label=label[:100], subject=subject[:200],
                      reason=reason, counts=counts, categories=categories(counts),
                      phone_hashes=[security.phone_hash(p) for p in phones]))
    audit(db, user, "erase", target=f"contact:{contact_id}", actor_label=label, reason=reason, **counts)
    db.commit()
    write_tombstones([security.phone_hash(p) for p in phones])
    return {"counts": counts, "manual_steps": manual_steps(lead_ids)}


def write_tombstones(hashes: list[str]) -> None:
    """Append the hashes to the tombstone file (outside the database). Never fails the erasure itself."""
    from ..config import get_settings
    path = get_settings().tombstone_file
    if not path or not hashes:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            for h in hashes:
                f.write(f"{dt.datetime.now(UTC).isoformat()} {h}\n")
    except OSError:
        import logging
        logging.getLogger("dsh.erase").exception("cannot write the tombstone file %s", path)


def read_tombstones() -> set[str]:
    from ..config import get_settings
    path = get_settings().tombstone_file
    try:
        with open(path, encoding="utf-8") as f:
            return {line.split()[-1] for line in f if line.strip()}
    except (OSError, TypeError):
        return set()


def categories(counts: dict) -> list[str]:
    """What was actually destroyed (the act lists only categories that existed)."""
    out = ["имя", "номер телефона"]
    if counts.get("leads_anonymised"):
        out += ["способ связи", "сведения из заявок", "IP-адрес и сведения о браузере"]
    if counts.get("consents_deleted"):
        out.append("записи о согласиях")
    if counts.get("events_deleted") or counts.get("browsers_deleted"):
        out.append("история посещения сайта")
    if counts.get("comments_cleared"):
        out.append("комментарии менеджеров")
    if counts.get("reviews_deleted"):
        out.append("отзывы")
    return out


def manual_steps(lead_ids: list[int]) -> list[str]:
    """What the database cannot destroy by itself (copies outside it)."""
    from ..config import get_settings
    s = get_settings()
    steps = []
    if lead_ids and s.smtp_host and s.notify_emails:
        nums = ", ".join(f"№{i}" for i in sorted(lead_ids)[:20])
        steps.append(f"Удалите из рабочей почты ({', '.join(s.notify_emails)}) письма о заявках {nums}.")
    if lead_ids and s.telegram_include_pd:
        steps.append("Удалите сообщения об этих заявках из чатов Telegram.")
    steps.append("Если позже восстановите базу из резервной копии — выполните python -m app reapply-erasures.")
    return steps


def erase_review(db: Session, review_id: int, subject: str, reason: str, user: AdminUser | None, label: str) -> dict:
    """Destroy one review (the author asked, the publication consent was withdrawn, or retention)."""
    r = db.get(Review, review_id)
    if r is None:
        raise ApiError(404, "not_found", "Отзыв не найден")
    phone = r.phone
    db.delete(r)  # consents of the review go by CASCADE
    counts = {"reviews_deleted": 1}
    db.add(ErasureLog(actor_id=user.id if user else None, actor_label=label[:100], subject=subject[:200],
                      reason=reason, counts=counts, categories=["имя", "номер телефона", "отзыв", "IP-адрес"],
                      phone_hashes=[security.phone_hash(phone)] if phone else []))
    audit(db, user, "erase_review", target=f"review:{review_id}", actor_label=label, reason=reason)
    db.commit()
    if phone:
        write_tombstones([security.phone_hash(phone)])
    return counts
