"""Nightly clean-up (`python -m app purge`), matching the retention promised in the privacy policy and consent:

- contacts with no open request and no activity for keep_contacts_days (3 years) → erased like a manual erasure;
- spam requests older than keep_spam_days → deleted;
- IP and user agent on requests and reviews older than keep_ip_days → cleared (consent rows keep theirs);
- anonymous site events and visits older than keep_events_days → deleted; browsers with nothing left → deleted;
- sent notifications older than 30 days, login counters, dead tokens, old audit rows → deleted.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import and_, delete, exists, or_, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..enums import OPEN_STATUSES, LeadStatus
from ..models import (AuditLog, Contact, ErasureLog, Lead, LeadHistory, Outbox, Review, SiteEvent, Visit, Visitor)
from . import admin_people, auth

UTC = dt.timezone.utc


def run(db: Session) -> dict:
    s = get_settings()
    now = dt.datetime.now(UTC)
    out: dict = {}

    # 1. people past retention (no open request, not seen for 3 years)
    cutoff = now - dt.timedelta(days=s.keep_contacts_days)
    open_lead = exists().where(Lead.contact_id == Contact.id, Lead.status.in_([x.value for x in OPEN_STATUSES]))
    stale = db.scalars(select(Contact.id).where(Contact.last_seen_at < cutoff, ~open_lead).limit(500)).all()
    erased = 0
    for cid in stale:  # each one is re-checked under lock: a person who came back meanwhile is kept
        if admin_people.erase(db, cid, "retention", f"контакт №{cid} (срок хранения истёк)", None, "Система",
                              stale_before=cutoff) is not None:
            erased += 1
    out["contacts_erased"] = erased

    # 2. spam
    spam_cut = now - dt.timedelta(days=s.keep_spam_days)
    spam_ids = select(Lead.id).where(Lead.status == LeadStatus.spam.value, Lead.created_at < spam_cut)
    db.execute(delete(LeadHistory).where(LeadHistory.lead_id.in_(spam_ids)))
    db.execute(update(Lead).where(Lead.parent_id.in_(spam_ids)).values(parent_id=None))
    out["spam_deleted"] = db.execute(delete(Lead).where(Lead.status == LeadStatus.spam.value,
                                                        Lead.created_at < spam_cut)).rowcount
    out["spam_reviews_deleted"] = db.execute(delete(Review).where(Review.spam_reason.is_not(None),
                                                                  Review.status == "rejected",
                                                                  Review.created_at < spam_cut)).rowcount

    # 3. IP / user agent
    ip_cut = now - dt.timedelta(days=s.keep_ip_days)
    out["lead_ips_cleared"] = db.execute(update(Lead).where(
        Lead.created_at < ip_cut, or_(Lead.ip.is_not(None), Lead.user_agent.is_not(None)))
        .values(ip=None, user_agent=None)).rowcount
    out["review_ips_cleared"] = db.execute(update(Review).where(
        Review.created_at < ip_cut, or_(Review.ip.is_not(None), Review.user_agent.is_not(None)))
        .values(ip=None, user_agent=None)).rowcount

    # 4. anonymous activity
    ev_cut = now - dt.timedelta(days=s.keep_events_days)
    out["events_deleted"] = db.execute(delete(SiteEvent).where(SiteEvent.received_at < ev_cut)).rowcount
    out["visits_deleted"] = db.execute(delete(Visit).where(Visit.last_seen_at < ev_cut)).rowcount
    linked = exists().where(Lead.visitor_id == Visitor.id)
    out["browsers_deleted"] = db.execute(delete(Visitor).where(
        Visitor.last_seen_at < ev_cut, ~linked,
        ~exists().where(Visit.visitor_id == Visitor.id),
        ~exists().where(SiteEvent.visitor_id == Visitor.id))).rowcount

    # 5. housekeeping
    out["outbox_deleted"] = db.execute(delete(Outbox).where(
        and_(Outbox.status.in_(["sent", "failed"]), Outbox.created_at < now - dt.timedelta(days=30)))).rowcount
    out.update(auth.purge(db))
    out["audit_deleted"] = db.execute(delete(AuditLog).where(
        AuditLog.at < now - dt.timedelta(days=s.keep_audit_days))).rowcount
    out["erasure_records_deleted"] = db.execute(delete(ErasureLog).where(
        ErasureLog.at < now - dt.timedelta(days=3 * 365))).rowcount
    db.commit()
    return out
