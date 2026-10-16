"""Admin: review moderation, statistics, CSV export, reference data (meta) for the panel."""
from __future__ import annotations

import csv
import datetime as dt
import io

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..enums import (CHANNEL_LABELS, ERASURE_REASON_LABELS, EVENT_LABELS, LEAD_KIND_LABELS, LEAD_STATUS_META,
                     LOST_REASON_LABELS, ORIGIN_LABELS, REVIEW_STATUS_LABELS, LeadStatus, ReviewStatus)
from ..errors import ApiError
from ..models import AdminUser, Breed, Lead, Review, Visit
from .. import schemas_admin as sa
from . import phone as phones
from .admin_leads import LeadFilter, apply_filter, day_start, tz
from .auth import audit

UTC = dt.timezone.utc


# ---------------------------------------------------------------- reviews
def list_reviews(db: Session, status: list[str], page: int, per_page: int) -> sa.Page:
    cond = [Review.status.in_(status)] if status else []
    total = db.scalar(select(func.count()).select_from(Review).where(*cond)) or 0
    rows = db.scalars(select(Review).where(*cond).order_by(Review.created_at.desc())
                      .offset((page - 1) * per_page).limit(per_page)).unique().all()
    return sa.Page[sa.ReviewRow](items=[sa.ReviewRow.model_validate(r) for r in rows], total=total, page=page,
                                 per_page=per_page)


def patch_review(db: Session, review_id: int, p: sa.ReviewPatch, user: AdminUser, label: str | None = None) -> Review:
    r = db.get(Review, review_id)
    if r is None:
        raise ApiError(404, "not_found", "Отзыв не найден")
    now = dt.datetime.now(UTC)
    for f in p.model_fields_set:
        v = getattr(p, f)
        if f == "status" and v is not None:
            r.status = v.value
            r.moderated_by, r.moderated_at = user.id, now
            if v == ReviewStatus.withdrawn:
                r.withdrawn_at = now
        elif v is not None or f in ("city", "moderator_note"):
            setattr(r, f, v)
    audit(db, user, "review_edit", target=f"review:{r.id}", actor_label=label, fields=sorted(p.model_fields_set))
    db.commit()
    db.refresh(r)
    return r


def approved_reviews(db: Session) -> list[dict]:
    """What the site may publish (for `python -m app export-reviews`)."""
    rows = db.scalars(select(Review).where(Review.status == ReviewStatus.approved.value)
                      .order_by(Review.created_at.desc())).unique().all()
    return [{"id": r.id, "name": r.display_name, "city": r.city, "breed": r.breed.slug if r.breed else None,
             "rating": r.rating, "text": r.text, "date": r.created_at.astimezone(tz()).date().isoformat()}
            for r in rows]


# ---------------------------------------------------------------- stats
def _period(date_from: dt.date | None, date_to: dt.date | None) -> tuple[dt.date, dt.date]:
    today = dt.datetime.now(tz()).date()
    d_to = date_to or today
    d_from = date_from or (d_to - dt.timedelta(days=29))
    if d_from > d_to:
        raise ApiError(422, "validation", "Начало периода позже конца", {"from": "Проверьте даты"})
    return d_from, d_to


def stats(db: Session, date_from: dt.date | None, date_to: dt.date | None, breed: list[str]) -> sa.StatsOut:
    d_from, d_to = _period(date_from, date_to)
    f = LeadFilter(created_from=d_from, created_to=d_to, breed=breed, include_children=False)
    base = apply_filter(select(Lead), f, None).where(Lead.status != LeadStatus.spam.value).subquery()
    L = base.c

    def group(col, label):
        rows = db.execute(select(col.label("k"), func.count().label("n")).select_from(base)
                          .group_by(col).order_by(func.count().desc())).all()
        return [{label: k, "count": n} for k, n in rows]

    breed_rows = db.execute(select(func.coalesce(Breed.key, "general"), func.coalesce(Breed.name, "Без породы"),
                                   func.count(), func.count().filter(L.status == LeadStatus.won.value),
                                   func.coalesce(func.sum(L.sale_amount), 0))
                            .select_from(base).outerjoin(Breed, Breed.id == L.breed_id)
                            .group_by(Breed.key, Breed.name)).all()
    local_day = func.date(func.timezone(get_settings().timezone, L.created_at))
    by_day = db.execute(select(local_day, func.count()).select_from(base).group_by(local_day)
                        .order_by(local_day)).all()
    resp = db.execute(select(
        func.percentile_cont(0.5).within_group(func.extract("epoch", L.first_response_at - L.created_at) / 60),
        func.percentile_cont(0.9).within_group(func.extract("epoch", L.first_response_at - L.created_at) / 60),
        func.count().filter(L.first_response_at.is_(None)))
        .select_from(base).where(L.origin == "site_form")).one()
    totals = {
        "leads": db.scalar(select(func.count()).select_from(base)) or 0,
        "won": db.scalar(select(func.count()).select_from(base).where(L.status == LeadStatus.won.value)) or 0,
        "repeat_requests": db.scalar(apply_filter(select(func.count()).select_from(Lead),
                                                  LeadFilter(created_from=d_from, created_to=d_to, breed=breed,
                                                             include_children=True), None)
                                     .where(Lead.parent_id.is_not(None))) or 0,
        "spam": db.scalar(apply_filter(select(func.count()).select_from(Lead), f, None)
                          .where(Lead.status == LeadStatus.spam.value)) or 0,
    }
    start, end = day_start(d_from), day_start(d_to + dt.timedelta(days=1))
    sessions = db.scalar(select(func.count()).select_from(Visit)
                         .where(Visit.started_at >= start, Visit.started_at < end,
                                func.coalesce(Visit.device, "") != "bot")) or 0
    visitors = db.scalar(select(func.count(func.distinct(Visit.visitor_id)))
                         .where(Visit.started_at >= start, Visit.started_at < end)) or 0
    return sa.StatsOut(
        period={"from": d_from.isoformat(), "to": d_to.isoformat(), "timezone": get_settings().timezone},
        totals=totals,
        by_breed=[{"breed": k, "name": n, "count": c, "won": w, "revenue": float(r)} for k, n, c, w, r in breed_rows],
        by_kind=group(L.kind, "kind"), by_status=group(L.status, "status"), by_origin=group(L.origin, "origin"),
        by_source=[{"source": s or "(нет данных)", "count": n} for s, n in
                   db.execute(select(L.source, func.count()).select_from(base).group_by(L.source)
                              .order_by(func.count().desc()).limit(20)).all()],
        by_day=[{"date": d.isoformat(), "count": n} for d, n in by_day],
        response={"median_minutes": round(resp[0], 1) if resp[0] is not None else None,
                  "p90_minutes": round(resp[1], 1) if resp[1] is not None else None,
                  "without_response": resp[2]},
        visits={"sessions": sessions, "visitors": visitors,
                "conversion": round(totals["leads"] / sessions, 4) if sessions else None},
    )


# ---------------------------------------------------------------- export
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _cell(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s.startswith(_FORMULA) else s  # CSV formula injection guard (Excel)


def export_csv(db: Session, f: LeadFilter, user: AdminUser, ip: str | None, label: str | None = None) -> tuple[bytes, int]:
    """UTF-8 with BOM, «;» separator, Moscow time, Russian headers — opens correctly in Russian Excel."""
    zone = tz()
    leads = db.scalars(apply_filter(select(Lead), f, user).order_by(Lead.created_at.desc()).limit(50_000)).unique().all()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["№", "Дата", "Статус", "Порода", "Что нужно", "Щенок", "Окрас", "Имя", "Телефон", "Куда писать",
                "Откуда", "Источник", "Страница", "Ответственный", "Связаться", "Причина отказа", "Сумма",
                "Повторный запрос к №", "Пометка"])
    for l in leads:
        w.writerow([_cell(x) for x in (
            l.id, l.created_at.astimezone(zone).strftime("%d.%m.%Y %H:%M"),
            LEAD_STATUS_META[LeadStatus(l.status)][0], l.breed.name if l.breed else "Без породы",
            LEAD_KIND_LABELS.get(l.kind, l.kind), l.puppy_name, l.colour, l.name,
            phones.display(l.phone) if l.phone else "", CHANNEL_LABELS.get(l.channel, l.channel),
            ORIGIN_LABELS.get(l.origin, l.origin), " / ".join(x for x in (l.source, l.medium) if x), l.page_path,
            l.assignee.name if l.assignee else "",
            l.next_contact_at.astimezone(zone).strftime("%d.%m.%Y %H:%M") if l.next_contact_at else "",
            LOST_REASON_LABELS.get(l.lost_reason, l.lost_reason or ""), l.sale_amount, l.parent_id, l.note)])
    audit(db, user, "export", ip=ip, actor_label=label, rows=len(leads), filters={k: str(v) for k, v in vars(f).items() if v})
    db.commit()
    return ("\ufeff" + buf.getvalue()).encode("utf-8"), len(leads)


# ---------------------------------------------------------------- meta
def managers(db: Session) -> list[dict]:
    rows = db.scalars(select(AdminUser).where(AdminUser.is_active.is_(True), AdminUser.is_service.is_(False))
                      .order_by(AdminUser.name)).all()
    return [{"id": u.id, "name": u.name, "role": u.role} for u in rows]


def meta(db: Session) -> sa.MetaOut:
    s = get_settings()
    breeds = db.scalars(select(Breed).order_by(Breed.sort)).all()
    return sa.MetaOut(
        statuses=[{"value": k.value, "label": v[0], "color": v[1], "is_closed": v[2], "order": i}
                  for i, (k, v) in enumerate(LEAD_STATUS_META.items())],
        kinds=[{"value": k.value, "label": v} for k, v in LEAD_KIND_LABELS.items()],
        origins=[{"value": k.value, "label": v} for k, v in ORIGIN_LABELS.items()],
        channels=[{"value": k.value, "label": v} for k, v in CHANNEL_LABELS.items()],
        lost_reasons=[{"value": k.value, "label": v} for k, v in LOST_REASON_LABELS.items()],
        review_statuses=[{"value": k.value, "label": v} for k, v in REVIEW_STATUS_LABELS.items()],
        erasure_reasons=[{"value": k.value, "label": v} for k, v in ERASURE_REASON_LABELS.items()],
        event_types=[{"value": k.value, "label": v} for k, v in EVENT_LABELS.items()],
        breeds=[{"id": b.id, "key": b.key, "slug": b.slug, "name": b.name, "is_active": b.is_active,
                 "view": f"leads_{b.key}"} for b in breeds] + [
            {"id": None, "key": "general", "slug": None, "name": "Без породы", "is_active": True,
             "view": "leads_general"}],
        managers=managers(db), timezone=s.timezone, link_site_activity=s.link_site_activity,
    )
