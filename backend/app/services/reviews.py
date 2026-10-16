"""Reviews from /otzyvy/: stored for moderation with two consents (processing + publication, ст. 10.1 152-ФЗ).
Only the display name («Анна К.»), city, breed, rating and text are ever published."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..enums import ReviewStatus, SpamReason
from ..errors import ApiError
from ..models import Review
from . import consent, notify, sanitize
from .leads import RequestCtx, resolve_catalog

UTC = dt.timezone.utc


def display_name(name: str) -> str:
    """«Анна Королёва» → «Анна К.»; «анна» → «Анна». The full name is never published."""
    parts = [p for p in name.replace(".", " ").split() if p]
    if not parts:
        return "Покупатель"
    first = parts[0][:30]
    first = first[:1].upper() + first[1:]
    if len(parts) > 1 and parts[1][:1].isalpha():
        return f"{first} {parts[1][:1].upper()}."
    return first


def create(db: Session, data, ctx: RequestCtx) -> tuple[Review, bool]:
    s = get_settings()
    now = dt.datetime.now(UTC)
    key = data.idempotency_key or uuid.uuid4()
    rhash = hashlib.sha256(json.dumps([data.name, data.text, data.rating, data.breed], ensure_ascii=False)
                           .encode()).hexdigest()
    existing = db.scalar(select(Review).where(Review.idempotency_key == key))
    if existing is not None:
        if existing.request_sha256 and existing.request_sha256 != rhash:
            raise ApiError(409, "idempotency_conflict", "Этот отзыв уже отправлен с другим текстом")
        return existing, False

    breed, _ = resolve_catalog(db, sanitize.clean(data.breed, 100), None)
    spam_reason = None
    if ctx.ip:
        n = db.scalar(select(func.count()).select_from(Review)
                      .where(Review.ip == ctx.ip, Review.created_at > now - dt.timedelta(days=1))) or 0
        if n >= s.reviews_per_ip_day:
            spam_reason = SpamReason.rate_limited.value
    if spam_reason is None and data.elapsed_ms is not None and data.elapsed_ms < s.min_fill_ms:
        spam_reason = SpamReason.too_fast.value

    name = sanitize.clean(data.name, 100) or "—"
    page_path = sanitize.path(data.page.path, s.site_base_paths)
    row = db.execute(insert(Review).values(
        name=name, display_name=display_name(name), city=sanitize.clean(data.city, 100),
        breed_id=breed.id if breed else None, rating=data.rating,
        text=sanitize.clean(data.text, 4000, multiline=True) or "", status=ReviewStatus.pending.value,
        page_path=page_path, visitor_id=data.visitor_id if s.link_site_activity else None,
        ip=ctx.ip, user_agent=sanitize.clean(ctx.user_agent, 400), idempotency_key=key, request_sha256=rhash,
        spam_reason=spam_reason,
    ).on_conflict_do_nothing(index_elements=[Review.idempotency_key]).returning(Review.id)).first()
    if row is None:
        db.rollback()
        existing = db.scalar(select(Review).where(Review.idempotency_key == key))
        if existing is None:
            raise ApiError(409, "idempotency_conflict", "Повторите отправку")
        return existing, False
    rid = row[0]
    docs = consent.load()["versions"]
    for kind, sent in (("processing", data.consent_version), ("distribution", data.consent_publish_version)):
        ver = sent if sent in docs and docs[sent]["kind"] == kind else consent.current(kind)
        consent.record(db, version=ver, review_id=rid, page_path=page_path, ip=ctx.ip, user_agent=ctx.user_agent)
    db.flush()
    review = db.get(Review, rid)
    if spam_reason is None:
        notify.enqueue_review(db, review)
    db.commit()
    return review, True
