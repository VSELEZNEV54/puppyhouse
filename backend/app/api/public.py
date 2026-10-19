"""Public endpoints used by the static site: requests, reviews, site events, health."""
from __future__ import annotations

import datetime as dt
import json
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, select, text

from ..config import get_settings
from ..db import session_scope
from ..errors import ApiError
from ..models import AuditLog, ConsentVersion, Outbox
from ..schemas_public import EventsAccepted, EventsIn, LeadAccepted, LeadIn, ReviewAccepted, ReviewIn
from ..services import consent, leads, notify, reviews, sanitize, tracking
from .deps import Db, _origin_ok, ip_of, public_json

log = logging.getLogger("dsh.public")
router = APIRouter(tags=["public"])
UTC = dt.timezone.utc


async def _json_body(request: Request, limit: int) -> object:
    body = await request.body()
    if len(body) > limit:
        raise ApiError(413, "too_large", "Слишком большой запрос")
    try:
        return json.loads(body or b"null", parse_constant=lambda _c: None)  # Infinity / NaN → null
    except ValueError:
        raise ApiError(400, "bad_json", "Тело запроса — не JSON")


def _validate(model, obj):
    try:
        return model.model_validate(obj if isinstance(obj, dict) else {})
    except ValidationError as e:
        raise RequestValidationError(e.errors())


def _deliver_now() -> None:
    """Right after the response: try to send the notifications of this request (the worker retries failures)."""
    try:
        with session_scope() as db:
            notify.deliver_due(db, limit=5)
    except Exception:  # noqa: BLE001 — the worker will pick it up
        log.exception("immediate delivery failed")


@router.post("/leads", status_code=201, response_model=LeadAccepted,
             responses={200: {"description": "Повтор уже принятой заявки (тот же idempotency_key)"},
                        409: {}, 415: {}, 422: {}})
async def create_lead(request: Request, db: Db, background: BackgroundTasks):
    """A request from any form of the site. Only name, phone, contact and consent can fail validation."""
    ctx = public_json(request)
    data = _validate(LeadIn, await _json_body(request, get_settings().max_body_bytes))
    if data.hp_note:  # honeypot filled: a bot. Pretend success, store nothing.
        log.info("honeypot hit from %s", ctx.ip)
        return LeadAccepted(id=uuid.uuid4())
    res = await run_in_threadpool(leads.create_from_site, db, data, ctx)
    if res.notified:
        background.add_task(_deliver_now)
    body = LeadAccepted(id=res.lead.public_id)
    if not res.created:
        return JSONResponse(body.model_dump(mode="json"), status_code=200)
    return body


@router.post("/reviews", status_code=201, response_model=ReviewAccepted, responses={409: {}, 415: {}, 422: {}})
async def create_review(request: Request, db: Db, background: BackgroundTasks):
    ctx = public_json(request)
    data = _validate(ReviewIn, await _json_body(request, get_settings().max_body_bytes))
    if data.hp_note:
        return ReviewAccepted()
    review, created = await run_in_threadpool(reviews.create, db, data, ctx)
    if created:
        background.add_task(_deliver_now)
        return ReviewAccepted()
    return JSONResponse(ReviewAccepted().model_dump(), status_code=200)


@router.post("/events", status_code=202, response_model=EventsAccepted)
async def track(request: Request, db: Db):
    """Beacons (navigator.sendBeacon sends text/plain). Always 202: tracking must never bother a page."""
    s = get_settings()
    nothing = EventsAccepted(accepted=0, dropped=0)
    ok, _ = _origin_ok(request)
    ua = request.headers.get("user-agent")
    if not ok or sanitize.device(ua) == "bot":
        return nothing
    try:
        obj = await _json_body(request, s.max_body_bytes)
        data = EventsIn.model_validate(obj if isinstance(obj, dict) else {})
    except (ApiError, ValidationError):
        return nothing
    if not data.visitor_id or not data.events:
        return EventsAccepted(accepted=0, dropped=len(data.events))

    def work():
        accepted, dropped = tracking.ingest(
            db, visitor_id=data.visitor_id, session_id=data.session_id, landing=data.landing,
            referrer=data.referrer, utm=data.utm, user_agent=ua, events=data.events, ym_uid=data.ym_uid,
            first_landing=data.first_landing, first_referrer=data.first_referrer, first_utm=data.first_utm)
        db.commit()
        return accepted, dropped

    try:
        accepted, dropped = await run_in_threadpool(work)
    except Exception:  # noqa: BLE001
        log.exception("event batch failed")
        db.rollback()
        return EventsAccepted(accepted=0, dropped=len(data.events))
    return EventsAccepted(accepted=accepted, dropped=dropped)


def health_problems(db) -> list[str]:
    problems = []
    db.execute(text("SELECT 1"))
    try:
        ver = consent.current("processing")
        if db.get(ConsentVersion, ver) is None:
            problems.append(f"consent version {ver} is not in the database (run python -m app migrate)")
    except consent.ConsentError as e:
        problems.append(str(e))
    now = dt.datetime.now(UTC)
    oldest = db.scalar(select(func.min(Outbox.created_at)).where(Outbox.status == "pending"))
    if oldest and now - oldest > dt.timedelta(minutes=10):
        problems.append("notifications are stuck for more than 10 minutes (is the worker running?)")
    last_cat = db.execute(select(AuditLog.action, AuditLog.details).where(
        AuditLog.action.in_(["catalog_synced", "catalog_sync_failed"])).order_by(AuditLog.id.desc()).limit(1)).first()
    if last_cat and last_cat[0] == "catalog_sync_failed":
        problems.append("the puppy catalog is not synced: " + str((last_cat[1] or {}).get("detail", ""))[:200]
                        + " — fix puppies.json or run python -m app sync-catalog --force")
    failed = db.scalar(select(func.count()).select_from(Outbox)
                       .where(Outbox.status == "failed", Outbox.created_at > now - dt.timedelta(days=1)))
    if failed:
        problems.append(f"{failed} notification(s) failed in the last 24 h")
    return problems


@router.get("/health")
def health(db: Db):
    """For an uptime monitor: 200 {"ok": true} or 503 {"ok": false}. Details: GET /api/v1/admin/health."""
    try:
        problems = health_problems(db)
    except Exception:  # noqa: BLE001
        log.exception("health check failed")
        problems = ["database"]
    if problems:
        log.warning("health: %s", "; ".join(problems))
        return JSONResponse({"ok": False}, status_code=503)
    return {"ok": True}
