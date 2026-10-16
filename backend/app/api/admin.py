"""Admin API for the internal admin panel: /api/v1/admin/…

Auth: `Authorization: Bearer <token>` — a login session (POST /auth/login) or a service API key
(`python -m app create-api-key`). With an API key, `X-Actor: <name>` tells whose action it is (percent-encoded
UTF-8: encodeURIComponent('Мария')); it goes to the request history and the audit log.
Lists: ?page=1&per_page=50 (≤ 200) → {items, total, page, per_page}; multi-value filters as status=new,in_progress;
dates (created_from / created_to) are local dates in DSH_TIMEZONE (Europe/Moscow).
Edits of a request need its `version` (body or If-Match) — 409 if someone changed it in between."""
from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select

from ..config import get_settings
from ..enums import OPEN_STATUSES, LeadStatus
from ..errors import ApiError
from ..models import Breed, Lead
from .. import schemas_admin as sa
from ..services import admin_leads, admin_misc, admin_people, auth, leads as leads_svc
from .deps import Actor, AdminActor, CurrentActor, Db, ip_of
from .public import health_problems

router = APIRouter(prefix="/admin", tags=["admin"])

PageNo = Annotated[int, Query(ge=1, le=100_000)]
PerPage = Annotated[int, Query(ge=1, le=200)]


def lead_filter(
    breed: Annotated[list[str] | None, Query(description="slug или key породы; general — без породы")] = None,
    status: Annotated[list[str] | None, Query(description="статусы; open / closed — группы")] = None,
    kind: Annotated[list[str] | None, Query()] = None,
    origin: Annotated[list[str] | None, Query()] = None,
    source: Annotated[list[str] | None, Query()] = None,
    assignee: Annotated[str | None, Query(description="id, me или none")] = None,
    overdue: bool = False,
    due_today: bool = False,
    q: Annotated[str | None, Query(max_length=100, description="имя, часть телефона или №")] = None,
    puppy: Annotated[str | None, Query(max_length=120)] = None,
    created_from: dt.date | None = None,
    created_to: dt.date | None = None,
    include_children: bool = False,
    contact_id: int | None = None,
) -> admin_leads.LeadFilter:
    m = admin_leads.multi
    return admin_leads.LeadFilter(breed=m(breed), status=m(status), kind=m(kind), origin=m(origin), source=m(source),
                                  assignee=assignee, overdue=overdue, due_today=due_today, q=q, puppy=puppy,
                                  created_from=created_from, created_to=created_to,
                                  include_children=include_children, contact_id=contact_id)


Filter = Annotated[admin_leads.LeadFilter, Depends(lead_filter)]


# ---------------------------------------------------------------- auth
@router.post("/auth/login", response_model=sa.LoginOut, tags=["admin: auth"])
def login(body: sa.LoginIn, request: Request, db: Db):
    token, user, expires = auth.login(db, body.login, body.password, ip_of(request))
    return sa.LoginOut(token=token, expires_at=expires, user=sa.Me.model_validate(user))


@router.post("/auth/logout", status_code=204, tags=["admin: auth"])
def logout(actor: CurrentActor, db: Db):
    if actor.token.kind == "session":
        auth.logout(db, actor.token)
    return Response(status_code=204)


@router.get("/me", response_model=sa.Me, tags=["admin: auth"])
def me(actor: CurrentActor):
    return sa.Me.model_validate(actor.user)


# ---------------------------------------------------------------- reference data
@router.get("/meta", response_model=sa.MetaOut, tags=["admin: meta"])
def meta(actor: CurrentActor, db: Db):
    """Statuses, kinds, channels, reasons with Russian labels and colours; breeds (with their SQL view names);
    managers. The panel should take every label from here."""
    return admin_misc.meta(db)


@router.get("/managers", tags=["admin: meta"])
def managers(actor: CurrentActor, db: Db):
    return admin_misc.managers(db)


@router.get("/health", tags=["admin: meta"])
def health_details(actor: CurrentActor, db: Db):
    return {"problems": health_problems(db)}


# ---------------------------------------------------------------- leads
@router.get("/leads", response_model=sa.Page[sa.LeadRow], tags=["admin: leads"])
def list_leads(actor: CurrentActor, db: Db, f: Filter, page: PageNo = 1, per_page: PerPage = 50,
               sort: str = "-created_at"):
    """The one big base; with ?breed=maltipu — that breed's base (?breed=general — requests without a breed).
    Repeat requests (children) are hidden unless include_children=true."""
    return admin_leads.list_leads(db, f, actor.user, page, per_page, sort)


@router.get("/leads/counts", response_model=list[sa.CountCell], tags=["admin: leads"])
def lead_counts(actor: CurrentActor, db: Db, f: Filter,
                group_by: Annotated[list[str] | None, Query(description="breed, status, kind, origin")] = None):
    """Badges for breed tabs and board columns in one call: ?group_by=breed,status&status=open."""
    return admin_leads.counts(db, f, actor.user, admin_leads.multi(group_by))


@router.post("/leads", response_model=sa.LeadDetail, status_code=201, tags=["admin: leads"])
def create_manual(body: sa.ManualLeadIn, actor: CurrentActor, db: Db):
    """A request taken by phone, in a messenger, on Avito… — into the same base, with the same dedup."""
    lead = leads_svc.create_manual(db, body, actor.user.id, actor.label)
    return admin_leads.detail(db, lead.id)


@router.get("/leads/{lead_id}", response_model=sa.LeadDetail, tags=["admin: leads"])
def lead_detail(lead_id: int, actor: CurrentActor, db: Db):
    """The request, its repeat requests, the person's other requests (all breeds), history and the site journey."""
    return admin_leads.detail(db, lead_id)


@router.patch("/leads/{lead_id}", response_model=sa.LeadDetail, tags=["admin: leads"])
def patch_lead(lead_id: int, body: sa.LeadPatch, actor: CurrentActor, db: Db,
               if_match: Annotated[str | None, Header()] = None):
    version = None
    if if_match:
        try:
            version = int(if_match.strip().strip('W/').strip('"'))
        except ValueError:
            raise ApiError(422, "validation", "If-Match — номер версии", {"version": "Число"})
    admin_leads.patch(db, lead_id, body, version, actor.user, actor.label)
    return admin_leads.detail(db, lead_id)


@router.post("/leads/{lead_id}/take", response_model=sa.LeadDetail, tags=["admin: leads"])
def take(lead_id: int, actor: CurrentActor, db: Db):
    """«Взять в работу»: assigns to me only if nobody has it; 409 otherwise."""
    admin_leads.take(db, lead_id, actor.user, actor.label)
    return admin_leads.detail(db, lead_id)


@router.post("/leads/{lead_id}/comments", response_model=sa.LeadDetail, tags=["admin: leads"])
def comment(lead_id: int, body: sa.CommentIn, actor: CurrentActor, db: Db):
    admin_leads.comment(db, lead_id, body.text, actor.user, actor.label)
    return admin_leads.detail(db, lead_id)


@router.get("/leads/{lead_id}/history", response_model=list[sa.HistoryItem], tags=["admin: leads"])
def lead_history(lead_id: int, actor: CurrentActor, db: Db):
    return admin_leads.history(db, lead_id)


# ---------------------------------------------------------------- breeds (the per-breed bases)
@router.get("/breeds", tags=["admin: leads"])
def breeds(actor: CurrentActor, db: Db):
    """Every breed base with its counters (and the general base for requests without a breed)."""
    now = dt.datetime.now(dt.timezone.utc)
    open_v = [x.value for x in OPEN_STATUSES]
    key = func.coalesce(Breed.key, "general")
    rows = db.execute(
        select(key, func.count(),
               func.count().filter(Lead.status.in_(open_v)),
               func.count().filter(Lead.status == LeadStatus.new.value),
               func.count().filter(Lead.status.in_(open_v), Lead.next_contact_at < now))
        .select_from(Lead).outerjoin(Breed, Breed.id == Lead.breed_id).where(Lead.parent_id.is_(None))
        .group_by(key)).all()
    by = {k: {"total": t, "open": o, "new": n, "overdue": od} for k, t, o, n, od in rows}
    out = []
    for b in db.scalars(select(Breed).order_by(Breed.sort)):
        out.append({"key": b.key, "slug": b.slug, "name": b.name, "is_active": b.is_active, "view": f"leads_{b.key}",
                    **by.get(b.key, {"total": 0, "open": 0, "new": 0, "overdue": 0})})
    out.append({"key": "general", "slug": None, "name": "Без породы", "is_active": True, "view": "leads_general",
                **by.get("general", {"total": 0, "open": 0, "new": 0, "overdue": 0})})
    return out


# ---------------------------------------------------------------- puppies
@router.get("/puppies", response_model=list[sa.PuppyRow], tags=["admin: puppies"])
def puppies(actor: CurrentActor, db: Db, breed: Annotated[list[str] | None, Query()] = None,
            status: Annotated[list[str] | None, Query()] = None, active: bool = True):
    """Puppies from the site catalog with request counters; catalog_mismatch = reserved/sold in the admin
    but still «available» on the site (update puppies.json)."""
    return admin_leads.puppies(db, admin_leads.multi(breed), admin_leads.multi(status), active)


@router.get("/puppies/{slug}/leads", response_model=list[sa.LeadRow], tags=["admin: puppies"])
def puppy_leads(slug: str, actor: CurrentActor, db: Db):
    """Who asked about this puppy, in order (the waiting list)."""
    return admin_leads.puppy_queue(db, slug)


# ---------------------------------------------------------------- contacts
@router.get("/contacts", response_model=sa.Page[sa.ContactRow], tags=["admin: contacts"])
def contacts(actor: CurrentActor, db: Db, q: Annotated[str | None, Query(max_length=100)] = None,
             blocked: bool | None = None, page: PageNo = 1, per_page: PerPage = 50):
    return admin_people.list_contacts(db, q, blocked, page, per_page)


@router.get("/contacts/{contact_id}", response_model=sa.ContactDetail, tags=["admin: contacts"])
def contact(contact_id: int, actor: CurrentActor, db: Db):
    return admin_people.detail(db, contact_id, actor.user, actor.ip, actor.label)


@router.patch("/contacts/{contact_id}", response_model=sa.ContactDetail, tags=["admin: contacts"])
def patch_contact(contact_id: int, body: sa.ContactPatch, actor: CurrentActor, db: Db):
    admin_people.patch(db, contact_id, body, actor.user, actor.label)
    return admin_people.detail(db, contact_id, actor.user, actor.ip, actor.label)


@router.get("/contacts/{contact_id}/events", response_model=list[sa.EventRow], tags=["admin: contacts"])
def contact_events(contact_id: int, actor: CurrentActor, db: Db, before_id: int | None = None,
                   limit: Annotated[int, Query(ge=1, le=500)] = 100):
    if not get_settings().link_site_activity:
        return []
    return admin_people.events(db, contact_id, before_id, limit)


@router.post("/contacts/{contact_id}/merge", response_model=sa.ContactDetail, tags=["admin: contacts"])
def merge(contact_id: int, body: sa.MergeIn, actor: CurrentActor, db: Db):
    """Two records of one person (two phones): everything moves into `into_id`, the old phone becomes an alias."""
    c = admin_people.merge(db, contact_id, body.into_id, actor.user, actor.label)
    return admin_people.detail(db, c.id, actor.user, actor.ip, actor.label)


@router.post("/contacts/{contact_id}/erase", tags=["admin: contacts"])
def erase(contact_id: int, body: sa.EraseIn, actor: AdminActor, db: Db):
    """Destroy a person's data (152-ФЗ: consent withdrawn, a request, retention). Admin role only. Requests stay
    in the statistics without personal data; an erasure record is kept for 3 years."""
    return {"erased": True, "counts": admin_people.erase(db, contact_id, body.reason.value, body.subject,
                                                         actor.user, actor.label)}


# ---------------------------------------------------------------- reviews
@router.get("/reviews", response_model=sa.Page[sa.ReviewRow], tags=["admin: reviews"])
def list_reviews(actor: CurrentActor, db: Db, status: Annotated[list[str] | None, Query()] = None,
                 page: PageNo = 1, per_page: PerPage = 50):
    return admin_misc.list_reviews(db, admin_leads.multi(status), page, per_page)


@router.patch("/reviews/{review_id}", response_model=sa.ReviewRow, tags=["admin: reviews"])
def patch_review(review_id: int, body: sa.ReviewPatch, actor: CurrentActor, db: Db):
    """Approve / reject / withdraw (the author asked to remove it: within 3 working days), fix the text."""
    return admin_misc.patch_review(db, review_id, body, actor.user, actor.label)


# ---------------------------------------------------------------- stats & export
@router.get("/stats", response_model=sa.StatsOut, tags=["admin: stats"])
def stats(actor: CurrentActor, db: Db, date_from: Annotated[dt.date | None, Query(alias="from")] = None,
          date_to: Annotated[dt.date | None, Query(alias="to")] = None,
          breed: Annotated[list[str] | None, Query()] = None):
    """Requests by breed / kind / status / origin / source / day (local days), reply time, visits and conversion."""
    return admin_misc.stats(db, date_from, date_to, admin_leads.multi(breed))


@router.get("/export/leads.csv", tags=["admin: stats"], response_class=Response)
def export(actor: AdminActor, db: Db, f: Filter):
    """CSV for Excel (UTF-8 BOM, «;»). Admin only; every export is written to the audit log."""
    body, _ = admin_misc.export_csv(db, f, actor.user, actor.ip, actor.label)
    name = f"zayavki-{dt.date.today().isoformat()}.csv"
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


__all__ = ["router", "Actor"]
