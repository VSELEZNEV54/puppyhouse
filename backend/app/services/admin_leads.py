"""Working with requests in the admin panel: lists with filters (the per-breed bases), counts, detail with the
person's other requests and site journey, edits with optimistic locking, «take», comments."""
from __future__ import annotations

import datetime as dt
import zoneinfo
from dataclasses import dataclass, field

from sqlalchemy import Select, and_, case, func, or_, select, update
from sqlalchemy.orm import Session, aliased

from ..config import get_settings
from ..enums import (CLOSED_STATUSES, OPEN_STATUSES, HistoryAction, LeadStatus, LostReason)
from ..errors import ApiError
from ..models import AdminUser, Breed, Lead, LeadHistory, Puppy, SiteEvent, Visit, Visitor
from .. import schemas_admin as sa
from . import notify, phone as phones
from .leads import COLOUR_SLUG, resolve_catalog

UTC = dt.timezone.utc
SORTS = {"created_at": Lead.created_at, "updated_at": Lead.updated_at, "last_activity_at": Lead.last_activity_at,
         "next_contact_at": Lead.next_contact_at, "status": Lead.status, "id": Lead.id}


def tz() -> zoneinfo.ZoneInfo:
    return zoneinfo.ZoneInfo(get_settings().timezone)


def day_start(d: dt.date) -> dt.datetime:
    """Local midnight of a date (Europe/Moscow by default) as an aware datetime."""
    return dt.datetime.combine(d, dt.time.min, tzinfo=tz())


def multi(v: str | list[str] | None) -> list[str]:
    """'new,in_progress' or ['new', 'in_progress'] → ['new', 'in_progress']."""
    if v is None:
        return []
    items = v if isinstance(v, list) else [v]
    return [x.strip() for i in items for x in str(i).split(",") if x.strip()]


@dataclass
class LeadFilter:
    breed: list[str] = field(default_factory=list)      # slug or key; "general" = no breed
    status: list[str] = field(default_factory=list)     # or "open" / "closed"
    kind: list[str] = field(default_factory=list)
    origin: list[str] = field(default_factory=list)
    assignee: str | None = None                         # id | "me" | "none"
    overdue: bool = False
    due_today: bool = False
    q: str | None = None                                # name, phone digits or №
    puppy: str | None = None
    source: list[str] = field(default_factory=list)
    created_from: dt.date | None = None
    created_to: dt.date | None = None
    include_children: bool = False
    contact_id: int | None = None


REPLY_SLA = dt.timedelta(minutes=15)  # the site promises a reply within 15 minutes


def overdue_condition(now: dt.datetime):
    """Open request whose call-back time has passed, or a new one nobody answered within the promised 15 minutes."""
    return and_(Lead.status.in_([x.value for x in OPEN_STATUSES]),
                or_(Lead.next_contact_at < now,
                    and_(Lead.status == LeadStatus.new.value, Lead.created_at < now - REPLY_SLA)),
                Lead.parent_id.is_(None))


def apply_filter(q: Select, f: LeadFilter, me: AdminUser | None) -> Select:
    conds = []
    if f.breed:
        keys = [b for b in f.breed if b != "general"]
        parts = []
        if keys:
            parts.append(Lead.breed_id.in_(select(Breed.id).where(or_(Breed.slug.in_(keys), Breed.key.in_(keys)))))
        if "general" in f.breed:
            parts.append(Lead.breed_id.is_(None))
        conds.append(or_(*parts))
    if f.status:
        st = set()
        for s in f.status:
            st |= {x.value for x in OPEN_STATUSES} if s == "open" else {x.value for x in CLOSED_STATUSES} \
                if s == "closed" else {s}
        conds.append(Lead.status.in_(st))
    if f.kind:
        conds.append(Lead.kind.in_(f.kind))
    if f.origin:
        conds.append(Lead.origin.in_(f.origin))
    if f.source:
        conds.append(Lead.source.in_(f.source))
    if f.assignee == "none":
        conds.append(Lead.assignee_id.is_(None))
    elif f.assignee == "me" and me is not None:
        conds.append(Lead.assignee_id == me.id)
    elif f.assignee and f.assignee.isdigit():
        conds.append(Lead.assignee_id == int(f.assignee))
    now = dt.datetime.now(UTC)
    if f.overdue:
        conds.append(overdue_condition(now))
    if f.due_today:
        today = dt.datetime.now(tz()).date()
        conds.append(and_(Lead.next_contact_at >= day_start(today),
                          Lead.next_contact_at < day_start(today + dt.timedelta(days=1))))
    if f.puppy:
        conds.append(or_(Lead.puppy_slug == f.puppy, Lead.puppy_id.in_(select(Puppy.id).where(Puppy.slug == f.puppy))))
    if f.created_from:
        conds.append(Lead.created_at >= day_start(f.created_from))
    if f.created_to:
        conds.append(Lead.created_at < day_start(f.created_to + dt.timedelta(days=1)))
    if f.contact_id:
        conds.append(Lead.contact_id == f.contact_id)
    if f.q:
        text = f.q.strip()
        digits = "".join(ch for ch in text if ch.isdigit())
        sub = [Lead.name.ilike(f"%{_like(text)}%")]
        if text.lstrip("№#").isdigit():
            sub.append(Lead.id == int(text.lstrip("№#")))
        if len(digits) >= 4:
            sub.append(Lead.phone.like(f"%{digits[-10:]}%"))
        conds.append(or_(*sub))
    if not f.include_children and not f.q and not f.contact_id:
        conds.append(Lead.parent_id.is_(None))
    return q.where(*conds)


def _like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _children_counts(db: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = db.execute(select(Lead.parent_id, func.count()).where(Lead.parent_id.in_(ids))
                      .group_by(Lead.parent_id)).all()
    return dict(rows)


def to_row(lead: Lead, children: int = 0) -> sa.LeadRow:
    row = sa.LeadRow.model_validate(lead)
    row.phone_display = phones.display(lead.phone) if lead.phone else None
    row.children_count = children
    return row


def list_leads(db: Session, f: LeadFilter, me: AdminUser, page: int, per_page: int, sort: str) -> sa.Page:
    q = apply_filter(select(Lead), f, me)
    total = db.scalar(apply_filter(select(func.count()).select_from(Lead), f, me)) or 0
    desc = sort.startswith("-")
    col = SORTS.get(sort.lstrip("-"))
    if col is None:
        raise ApiError(422, "validation", "Неизвестная сортировка", {"sort": f"Можно: {', '.join(SORTS)}"})
    order = [col.desc().nulls_last() if desc else col.asc().nulls_last(), Lead.id.desc() if desc else Lead.id.asc()]
    leads = db.scalars(q.order_by(*order).offset((page - 1) * per_page).limit(per_page)).unique().all()
    kids = _children_counts(db, [l.id for l in leads])
    return sa.Page[sa.LeadRow](items=[to_row(l, kids.get(l.id, 0)) for l in leads], total=total, page=page,
                               per_page=per_page)


def counts(db: Session, f: LeadFilter, me: AdminUser, group_by: list[str]) -> list[sa.CountCell]:
    allowed = {"breed", "status", "kind", "origin"}
    group_by = [g for g in group_by if g in allowed] or ["breed", "status"]
    cols = {"breed": func.coalesce(Breed.key, "general").label("breed"), "status": Lead.status.label("status"),
            "kind": Lead.kind.label("kind"), "origin": Lead.origin.label("origin")}
    sel = [cols[g] for g in group_by]
    q = select(*sel, func.count().label("n")).select_from(Lead).outerjoin(Breed, Breed.id == Lead.breed_id)
    q = apply_filter(q, f, me).group_by(*sel)
    out = []
    for row in db.execute(q).mappings():
        out.append(sa.CountCell(breed=row.get("breed"), status=row.get("status"), kind=row.get("kind"),
                                origin=row.get("origin"), count=row["n"]))
    return out


def get_lead(db: Session, lead_id: int) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise ApiError(404, "not_found", "Заявка не найдена")
    return lead


def contact_links(phone: str | None, channel: str | None, tg_user: str | None = None) -> dict[str, str]:
    if not phone:
        return {}
    digits = phone.lstrip("+")
    links = {"tel": f"tel:{phone}", "whatsapp": f"https://wa.me/{digits}", "telegram": f"https://t.me/{phone}"}
    if tg_user:
        links["telegram"] = f"https://t.me/{tg_user.lstrip('@')}"
    if channel in links:
        links["preferred"] = links[channel]
    elif channel == "call":
        links["preferred"] = links["tel"]
    return links


def journey(db: Session, lead: Lead) -> sa.Journey | None:
    s = get_settings()
    if not s.link_site_activity or not lead.visitor_id:
        return None
    v = db.get(Visitor, lead.visitor_id)
    j = sa.Journey(quiz=(lead.details or {}).get("quiz"))
    if v is not None:
        j.first_seen_at, j.first_landing = v.first_seen_at, v.first_landing
        j.first_source, j.first_medium, j.ym_uid = v.first_source, v.first_medium, v.ym_uid
        j.days_to_request = max(0, (lead.created_at - v.first_seen_at).days)
    j.visits = db.scalar(select(func.count()).select_from(Visit).where(Visit.visitor_id == lead.visitor_id,
                                                                        Visit.started_at <= lead.created_at)) or 0
    before = (SiteEvent.visitor_id == lead.visitor_id, SiteEvent.occurred_at <= lead.created_at)
    pages = db.execute(select(SiteEvent.path, SiteEvent.occurred_at).where(*before, SiteEvent.type == "page_view")
                       .order_by(SiteEvent.occurred_at.desc()).limit(10)).all()
    j.pages_before = [{"path": p, "at": at.isoformat()} for p, at in pages]
    j.puppies_viewed = [r for (r,) in db.execute(
        select(SiteEvent.puppy_slug).where(*before, SiteEvent.puppy_slug.is_not(None))
        .group_by(SiteEvent.puppy_slug).order_by(func.max(SiteEvent.occurred_at).desc()).limit(10))]
    j.breeds_viewed = [r for (r,) in db.execute(
        select(SiteEvent.breed_key).where(*before, SiteEvent.breed_key.is_not(None))
        .group_by(SiteEvent.breed_key).order_by(func.count().desc()))]
    if j.quiz is None:
        last_quiz = db.scalar(select(SiteEvent.data).where(*before, SiteEvent.type == "quiz_complete")
                              .order_by(SiteEvent.occurred_at.desc()).limit(1))
        if last_quiz:
            j.quiz = {k: last_quiz.get(k) for k in ("winner", "second") if last_quiz.get(k)}
    return j


def detail(db: Session, lead_id: int) -> sa.LeadDetail:
    lead = get_lead(db, lead_id)
    kids = db.scalars(select(Lead).where(Lead.parent_id == lead.id).order_by(Lead.created_at)).unique().all()
    others = []
    if lead.contact_id:
        others = db.scalars(select(Lead).where(Lead.contact_id == lead.contact_id, Lead.id != lead.id,
                                               Lead.parent_id.is_(None))
                            .order_by(Lead.created_at.desc()).limit(50)).unique().all()
    hist = db.scalars(select(LeadHistory).where(LeadHistory.lead_id == lead.id).order_by(LeadHistory.at, LeadHistory.id)).all()
    base = to_row(lead, len(kids)).model_dump()
    d = sa.LeadDetail(**base, page_title=lead.page_title, referrer_host=lead.referrer_host,
                      landing_path=lead.landing_path, utm=lead.utm, details=lead.details or {},
                      consent_at=lead.consent_at, consent_version=lead.consent_version,
                      children=[to_row(k) for k in kids], other_leads=[to_row(o) for o in others],
                      history=[sa.HistoryItem.model_validate(h) for h in hist], journey=journey(db, lead),
                      links=contact_links(lead.phone, lead.channel,
                                          lead.contact.telegram_username if lead.contact else None))
    return d


def _hist(db, lead_id, action, user, label, old=None, new=None, comment=None):
    db.add(LeadHistory(lead_id=lead_id, action=action.value, actor_id=user.id, actor_label=label[:100],
                       old_value=None if old is None else str(old)[:300],
                       new_value=None if new is None else str(new)[:300], comment=comment))


def _touch(lead: Lead, now: dt.datetime) -> None:
    lead.last_activity_at = now
    if lead.first_response_at is None:
        lead.first_response_at = now


def patch(db: Session, lead_id: int, p: sa.LeadPatch, version: int | None, user: AdminUser, label: str) -> Lead:
    lead = get_lead(db, lead_id)
    if lead.anonymised_at is not None:
        raise ApiError(409, "anonymised", "Данные этой заявки удалены по требованию 152-ФЗ")
    want = version if version is not None else p.version
    if want is None:
        raise ApiError(428, "version_required", "Передайте version (или заголовок If-Match) — защита от перезаписи")
    # lock and compare in one statement: two managers saving at once cannot overwrite each other
    locked = db.execute(update(Lead).where(Lead.id == lead_id, Lead.version == want)
                        .values(version=Lead.version + 1).returning(Lead.id)).first()
    if locked is None:
        db.rollback()
        raise ApiError(409, "version_conflict", "Заявку уже изменил другой менеджер — обновите карточку",
                       extra={"current_version": get_lead(db, lead_id).version})
    db.refresh(lead)
    now = dt.datetime.now(UTC)
    fields = p.model_fields_set - {"version"}

    if "breed" in fields or "puppy" in fields:
        new_breed, new_pup = lead.breed, lead.puppy
        if "puppy" in fields and p.puppy:
            b2, pup = resolve_catalog(db, None, p.puppy)
            if pup is None:
                raise ApiError(422, "validation", "Нет такого щенка", {"puppy": "Неизвестный щенок"})
            new_breed, new_pup = b2, pup
        elif "puppy" in fields:
            new_pup = None
        if "breed" in fields and not ("puppy" in fields and p.puppy):
            if p.breed:
                b2, _ = resolve_catalog(db, p.breed, None)
                if b2 is None:
                    raise ApiError(422, "validation", "Нет такой породы", {"breed": "Неизвестная порода"})
                new_breed = b2
            else:
                new_breed = None
            if new_pup is not None and (new_breed is None or new_pup.breed_id != new_breed.id):
                new_pup = None  # a puppy always belongs to the lead's breed
        if (new_breed.id if new_breed else None) != lead.breed_id:
            _hist(db, lead.id, HistoryAction.breed, user, label, lead.breed.name if lead.breed else "—",
                  new_breed.name if new_breed else "—")
        if (new_pup.id if new_pup else None) != lead.puppy_id:
            _hist(db, lead.id, HistoryAction.puppy, user, label, lead.puppy_name or "—",
                  new_pup.name if new_pup else "—")
        lead.breed_id = new_breed.id if new_breed else None
        lead.puppy_id = new_pup.id if new_pup else None
        if new_pup is not None:
            lead.puppy_slug, lead.puppy_name = new_pup.slug, new_pup.name
        else:  # no puppy any more (cleared, or another breed): out of the old puppy's waiting list too
            lead.puppy_slug = lead.puppy_name = None

    if "colour" in fields:
        if p.colour and not COLOUR_SLUG.match(p.colour):
            raise ApiError(422, "validation", "Окрас — латинский код из каталога", {"colour": "Например, kremovyj"})
        if (p.colour or None) != lead.colour:
            _hist(db, lead.id, HistoryAction.edit, user, label, lead.colour or "—", p.colour or "—", comment="окрас")
        lead.colour = p.colour or None

    if "status" in fields and p.status and p.status.value != lead.status:
        st = p.status
        if st == LeadStatus.lost and not (p.lost_reason or lead.lost_reason):
            raise ApiError(422, "validation", "Укажите причину отказа", {"lost_reason": "Обязательно для «Отказ»"})
        if st == LeadStatus.duplicate and lead.parent_id is None:
            raise ApiError(422, "validation", "Дублем становится только повторный запрос",
                           {"status": "Склейте контакты или закройте как «Отказ»"})
        _hist(db, lead.id, HistoryAction.status, user, label, lead.status, st.value)
        lead.status, lead.status_changed_at = st.value, now
        lead.closed_at = now if st in CLOSED_STATUSES else None
        lead.spam_reason = (lead.spam_reason or "manual") if st == LeadStatus.spam else None
        if st != LeadStatus.lost:
            lead.lost_reason = None
    if "lost_reason" in fields:
        new_reason = p.lost_reason.value if p.lost_reason else None
        if new_reason and lead.status != LeadStatus.lost.value:
            raise ApiError(422, "validation", "Причина отказа — только для статуса «Отказ»", {"lost_reason": "—"})
        if new_reason != lead.lost_reason:
            _hist(db, lead.id, HistoryAction.edit, user, label, lead.lost_reason or "—", new_reason or "—",
                  comment="причина отказа")
        lead.lost_reason = new_reason
    if "sale_amount" in fields and p.sale_amount != lead.sale_amount:
        _hist(db, lead.id, HistoryAction.edit, user, label,
              "—" if lead.sale_amount is None else str(lead.sale_amount),
              "—" if p.sale_amount is None else str(p.sale_amount), comment="сумма продажи")
        lead.sale_amount = p.sale_amount
    if "assignee_id" in fields and p.assignee_id != lead.assignee_id:
        new_user = None
        if p.assignee_id is not None:
            new_user = db.get(AdminUser, p.assignee_id)
            if new_user is None or not new_user.is_active or new_user.is_service:
                raise ApiError(422, "validation", "Нет такого менеджера", {"assignee_id": "Неизвестный менеджер"})
        _hist(db, lead.id, HistoryAction.assignee, user, label, lead.assignee.name if lead.assignee else "—",
              new_user.name if new_user else "—")
        lead.assignee_id = p.assignee_id
    if "next_contact_at" in fields:
        nxt = p.next_contact_at
        if nxt is not None and nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=tz())
        _hist(db, lead.id, HistoryAction.next_contact, user, label,
              lead.next_contact_at.isoformat() if lead.next_contact_at else "—", nxt.isoformat() if nxt else "—")
        lead.next_contact_at = nxt
    if "comment" in fields and p.comment:
        _hist(db, lead.id, HistoryAction.comment, user, label, comment=p.comment)
    _touch(lead, now)
    db.flush()
    notify.enqueue_lead(db, lead, "lead.updated", channels=("webhook",))
    db.commit()
    db.refresh(lead)
    return lead


def take(db: Session, lead_id: int, user: AdminUser, label: str) -> Lead:
    """Assign to me only if nobody has it (atomic) — two managers pressing «Взять» at once get one winner."""
    now = dt.datetime.now(UTC)
    is_new = Lead.status == LeadStatus.new.value
    old_status = db.scalar(select(Lead.status).where(Lead.id == lead_id))
    row = db.execute(update(Lead).where(Lead.id == lead_id, Lead.assignee_id.is_(None), Lead.anonymised_at.is_(None))
                     .values(assignee_id=user.id, version=Lead.version + 1, last_activity_at=now,
                             first_response_at=func.coalesce(Lead.first_response_at, now),
                             status=case((is_new, LeadStatus.in_progress.value), else_=Lead.status),
                             status_changed_at=case((is_new, now), else_=Lead.status_changed_at))
                     .returning(Lead.id, Lead.status)).first()
    if row is None:
        db.rollback()
        lead = get_lead(db, lead_id)
        raise ApiError(409, "already_taken", "Заявку уже взял другой менеджер",
                       extra={"assignee": lead.assignee.name if lead.assignee else None})
    _hist(db, lead_id, HistoryAction.assignee, user, label, "—", user.name)
    if old_status == LeadStatus.new.value and row[1] != old_status:
        _hist(db, lead_id, HistoryAction.status, user, label, old_status, row[1])
    db.flush()
    lead = get_lead(db, lead_id)
    notify.enqueue_lead(db, lead, "lead.updated", channels=("webhook",))
    db.commit()
    db.refresh(lead)
    return lead


def comment(db: Session, lead_id: int, text: str, user: AdminUser, label: str) -> Lead:
    lead = get_lead(db, lead_id)
    if lead.anonymised_at is not None:
        raise ApiError(409, "anonymised", "Данные этой заявки удалены")
    _hist(db, lead.id, HistoryAction.comment, user, label, comment=text)
    _touch(lead, dt.datetime.now(UTC))
    lead.version += 1
    db.commit()
    db.refresh(lead)
    return lead


def history(db: Session, lead_id: int) -> list[LeadHistory]:
    get_lead(db, lead_id)
    return db.scalars(select(LeadHistory).where(LeadHistory.lead_id == lead_id)
                      .order_by(LeadHistory.at, LeadHistory.id)).all()


# ---------------------------------------------------------------- puppies
def puppies(db: Session, breed: list[str], status: list[str], active_only: bool) -> list[sa.PuppyRow]:
    q = select(Puppy).join(Breed, Breed.id == Puppy.breed_id)
    if breed:
        q = q.where(or_(Breed.slug.in_(breed), Breed.key.in_(breed)))
    if status:
        q = q.where(Puppy.status.in_(status))
    if active_only:
        q = q.where(Puppy.is_active.is_(True))
    pups = db.scalars(q.order_by(Breed.sort, Puppy.name)).unique().all()
    ids = [p.id for p in pups]
    by = {}
    if ids:
        for pid, st, n in db.execute(select(Lead.puppy_id, Lead.status, func.count())
                                     .where(Lead.puppy_id.in_(ids)).group_by(Lead.puppy_id, Lead.status)):
            by.setdefault(pid, {})[st] = n
    out = []
    open_v = {x.value for x in OPEN_STATUSES}
    for p in pups:
        m = by.get(p.id, {})
        sold_or_res = m.get(LeadStatus.reserved.value, 0) + m.get(LeadStatus.won.value, 0)
        out.append(sa.PuppyRow(
            id=p.id, slug=p.slug, name=p.name, breed=sa.BreedRef.model_validate(p.breed), sex=p.sex,
            colour=p.colour, status=p.status, is_active=p.is_active, leads_total=sum(m.values()),
            leads_open=sum(n for st, n in m.items() if st in open_v), leads_by_status=m,
            catalog_mismatch=bool(sold_or_res) and p.status == "available"))
    return out


def puppy_queue(db: Session, slug: str) -> list[sa.LeadRow]:
    pup = db.scalar(select(Puppy).where(Puppy.slug == slug))
    if pup is None:
        raise ApiError(404, "not_found", "Щенок не найден")
    leads = db.scalars(select(Lead).where(or_(Lead.puppy_id == pup.id, Lead.puppy_slug == slug))
                       .order_by(Lead.created_at)).unique().all()
    return [to_row(l) for l in leads]


__all__ = ["LeadFilter", "list_leads", "counts", "detail", "patch", "take", "comment", "history", "puppies",
           "puppy_queue", "multi", "day_start", "tz", "to_row", "contact_links", "aliased", "LostReason"]
