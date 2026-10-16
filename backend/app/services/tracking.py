"""Anonymous site activity: visitors (browsers), sessions (visits) and events.

Everything here is best effort: a bad beacon is dropped, never an error that could break a page or a lead.
No IP and no user agent are stored (only a coarse device type); paths lose their query string; referrers keep
only the host."""
from __future__ import annotations

import datetime as dt
import re
import uuid

from sqlalchemy import func
from sqlalchemy.exc import DBAPIError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..enums import EventType
from ..models import SiteEvent, Visit, Visitor
from . import attribution, catalog, sanitize

UTC = dt.timezone.utc
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,119}$")

# allowed keys of `data` per event type (anything else is dropped); values are short strings / small ints
EVENT_DATA_KEYS = {
    EventType.page_view: {"title"},
    EventType.form_open: {"kind", "form", "puppy", "colour", "breed"},
    EventType.contact_click: {"channel", "place"},
    EventType.quiz_complete: {"winner", "second", "answers"},
}


def _small(v, limit=120):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        return sanitize.clean(v, limit)
    return None


def clean_data(etype: EventType, data: dict | None) -> dict:
    out: dict = {}
    for k in EVENT_DATA_KEYS.get(etype, set()):
        if not data or k not in data:
            continue
        v = data[k]
        if k == "answers" and isinstance(v, dict):  # quiz: {question key: option key}
            ans = {}
            for a, b in list(v.items())[:12]:
                ka, kb = sanitize.clean(str(a), 20), sanitize.clean(str(b), 20) if isinstance(b, (str, int)) else None
                if ka and kb:
                    ans[ka] = kb
            out[k] = ans
        else:
            sv = _small(v)
            if sv is not None:
                out[k] = sv
    return out


def page_refs(path: str | None) -> tuple[str | None, str | None]:
    """(breed_key, puppy_slug) from a site path: /maltipu/… → maltipu; /shchenki/<slug>/ → its breed and slug."""
    if not path:
        return None, None
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None, None
    try:
        cat = catalog.load()
    except catalog.CatalogError:
        return None, None
    if parts[0] == "shchenki" and len(parts) > 1 and _SLUG.match(parts[1]):
        for p in cat.puppies:
            if p["slug"] == parts[1]:
                b = cat.breed_by_any(p["breed"])
                return (b["key"] if b else None), parts[1]
        return None, parts[1]
    b = cat.breed_by_any(parts[0])
    return (b["key"] if b else None), None


def touch_visitor(db: Session, visitor_id: uuid.UUID, *, landing: str | None, referrer_host: str | None,
                  utm: dict | None, ym_uid: str | None = None) -> None:
    """Create the visitor on first sight (first touch is never overwritten), bump last_seen_at otherwise."""
    s = get_settings()
    src, med = attribution.classify(utm, f"https://{referrer_host}/" if referrer_host else None, tuple(s.own_hosts))
    stmt = insert(Visitor).values(id=visitor_id, first_landing=landing, first_referrer_host=referrer_host,
                                  first_utm=utm, first_source=src, first_medium=med,
                                  ym_uid=sanitize.clean(ym_uid, 40))
    stmt = stmt.on_conflict_do_update(index_elements=[Visitor.id], set_={
        "last_seen_at": func.now(),
        "ym_uid": func.coalesce(Visitor.ym_uid, stmt.excluded.ym_uid),
    })
    db.execute(stmt)


def touch_session(db: Session, session_id: uuid.UUID, visitor_id: uuid.UUID, *, landing: str | None,
                  referrer_host: str | None, utm: dict | None, user_agent: str | None, events: int = 0) -> None:
    s = get_settings()
    src, med = attribution.classify(utm, f"https://{referrer_host}/" if referrer_host else None, tuple(s.own_hosts))
    stmt = insert(Visit).values(id=session_id, visitor_id=visitor_id, landing_path=landing,
                                referrer_host=referrer_host, utm=utm, source=src, medium=med,
                                device=sanitize.device(user_agent), events_count=events)
    stmt = stmt.on_conflict_do_update(index_elements=[Visit.id], set_={
        "last_seen_at": func.now(), "events_count": Visit.events_count + events,
    }, where=Visit.visitor_id == visitor_id)  # a session id reused by another browser is ignored
    db.execute(stmt)


def ingest(db: Session, *, visitor_id: uuid.UUID, session_id: uuid.UUID | None, landing: str | None,
           referrer: str | None, utm: dict | None, user_agent: str | None, events: list, ym_uid: str | None = None,
           first_landing: str | None = None, first_referrer: str | None = None, first_utm: dict | None = None
           ) -> tuple[int, int]:
    """Store a batch of beacons. Returns (accepted, dropped)."""
    s = get_settings()
    now = dt.datetime.now(UTC)
    ref_host = sanitize.host(referrer)
    if ref_host and any(ref_host == h or ref_host.endswith("." + h) for h in s.own_hosts):
        ref_host = None  # internal navigation is not a source
    utm = attribution.clean_utm(utm)
    touch_visitor(db, visitor_id, landing=sanitize.path(first_landing or landing, s.site_base_paths),
                  referrer_host=sanitize.host(first_referrer) or ref_host,
                  utm=attribution.clean_utm(first_utm) or utm, ym_uid=ym_uid)
    rows, dropped = [], 0
    for e in events[: s.max_events_per_batch]:
        try:
            etype = EventType(e.type)
        except ValueError:
            dropped += 1
            continue
        path = sanitize.path(e.path, s.site_base_paths)
        breed_key, puppy_slug = page_refs(path)
        data = clean_data(etype, e.data)
        if etype == EventType.form_open and isinstance(data.get("puppy"), str) and _SLUG.match(data["puppy"]):
            puppy_slug = data["puppy"]
        occurred = now
        if isinstance(e.ts, int) and e.ts > 0:
            try:
                t = dt.datetime.fromtimestamp(e.ts / 1000, UTC)
                occurred = min(max(t, now - dt.timedelta(days=1)), now + dt.timedelta(minutes=5))
            except (OverflowError, OSError, ValueError):
                pass
        rows.append(dict(visitor_id=visitor_id, session_id=session_id, type=etype.value, path=path,
                         breed_key=breed_key, puppy_slug=puppy_slug, data=data, occurred_at=occurred))
    dropped += max(0, len(events) - s.max_events_per_batch)
    if session_id:
        touch_session(db, session_id, visitor_id, landing=sanitize.path(landing, s.site_base_paths),
                      referrer_host=ref_host, utm=utm, user_agent=user_agent, events=len(rows))
        # the session may belong to another visitor (ignored by touch_session): then do not attach events to it
        owner = db.scalar(Visit.__table__.select().with_only_columns(Visit.visitor_id)
                          .where(Visit.id == session_id))
        if owner != visitor_id:
            for r in rows:
                r["session_id"] = None
    if rows:
        try:
            with db.begin_nested():
                db.execute(insert(SiteEvent), rows)
        except DBAPIError:  # one bad row must not lose the batch: insert one by one, skip the bad ones
            ok = 0
            for r in rows:
                try:
                    with db.begin_nested():
                        db.execute(insert(SiteEvent), [r])
                    ok += 1
                except DBAPIError:
                    dropped += 1
            return ok, dropped
    return len(rows), dropped
