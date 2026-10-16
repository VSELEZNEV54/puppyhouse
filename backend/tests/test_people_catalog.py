"""People and the catalog: contacts (search, card, edits), merging two records of one person, erasure of a person
(152-ФЗ), the nightly retention clean-up, the catalog sync from the site's JSON with the per-breed SQL views, and
the consent documents sync.

What matters for a kennel: a manager finds a person by name or by any of their numbers; a merge never loses a
request or a consent and later requests from the old number land on the same person; an erasure really destroys
the person's data (names, phones, comments, notifications, browsing history, consents) while the requests stay
counted in the statistics; retention keeps exactly what the privacy policy promises; a broken or truncated catalog
file never wipes the catalog, and every breed always has its own base (SQL view).

Catalog and consent tests run inside the `db` session and never commit: the fixture rolls back, so breeds, puppies,
consent versions and the views stay as migrate built them for the other tests of this process."""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from conftest import lead_payload

A = "/api/v1/admin"
EVENTS = "/api/v1/events"
PUP = "maltipu-f1-krem-2026-08"          # «Пломбир», maltipu, available
PUP_PUDEL = "toj-pudel-abrikos-2026-07"  # «Марго», toj-pudel, available
PROCESSING = "processing-2026-10-16"


# ---------------------------------------------------------------- helpers
def phone(n: int) -> str:
    """A distinct Russian number per person, in the site mask."""
    return f"+7 (9{n:02d}) 555-{n:02d}-{n:02d}"


def e164(n: int) -> str:
    return f"+79{n:02d}555{n:02d}{n:02d}"


def sql(db, stmt: str, **kw):
    """Run SQL in the test session and commit at once (never hold locks the app would wait for)."""
    res = db.execute(text(stmt), kw)
    rows = [dict(r) for r in res.mappings()] if res.returns_rows else None
    db.commit()
    return rows


def one(db, stmt: str, **kw):
    rows = sql(db, stmt, **kw)
    return rows[0] if rows else None


def q(db, stmt: str, **kw):
    """SQL inside the open transaction, no commit (catalog / consent tests)."""
    res = db.execute(text(stmt), kw)
    return [dict(r) for r in res.mappings()] if res.returns_rows else None


def count(db, table: str, where: str = "TRUE", **kw) -> int:
    return one(db, f"SELECT count(*) AS n FROM {table} WHERE {where}", **kw)["n"]


def new_lead(make_lead, db, n: int, **over) -> int:
    """POST a request of person n through the public API; return its admin number (leads.id)."""
    over.setdefault("phone", phone(n))
    pub = make_lead(**over)["id"]
    return one(db, "SELECT id FROM leads WHERE public_id = :p", p=pub)["id"]


def contact_id(db, n: int) -> int | None:
    row = one(db, "SELECT id FROM contacts WHERE phone = :p", p=e164(n))
    return row["id"] if row else None


def beacon(client, visitor_id, n: int = 2, session_id=None) -> None:
    """navigator.sendBeacon from main.js: n page views of one visit."""
    body = {"visitor_id": str(visitor_id), "session_id": str(session_id or uuid.uuid4()), "landing": "/maltipu/",
            "events": [{"type": "page_view", "path": f"/maltipu/{i}/", "data": {"title": "Мальтипу"}}
                       for i in range(n)]}
    r = client.post(EVENTS, content=json.dumps(body).encode(), headers={"Content-Type": "text/plain;charset=UTF-8"})
    assert r.status_code == 202 and r.json()["accepted"] == n, r.text


def merge(client, h, src: int, dst: int):
    return client.post(f"{A}/contacts/{src}/merge", json={"into_id": dst}, headers=h)


def erase(client, h, cid: int, reason="request", subject="Субъект ПД, заявление от 16.10.2026"):
    return client.post(f"{A}/contacts/{cid}/erase", json={"reason": reason, "subject": subject}, headers=h)


def leads_views(db) -> set[str]:
    return {r["viewname"] for r in q(db, "SELECT viewname FROM pg_views WHERE schemaname = current_schema() "
                                         "AND viewname LIKE 'leads\\_%'")}


def view_ids(db, view: str) -> list[int]:
    return sorted(r["lead_id"] for r in q(db, f"SELECT lead_id FROM {view}"))


def site_catalog():
    """A private copy of the site catalog (never mutate the cached catalog.load() result)."""
    from app.services import catalog
    base = catalog.load()
    return catalog.SiteCatalog(breeds=copy.deepcopy(base.breeds), puppies=copy.deepcopy(base.puppies),
                               colours=copy.deepcopy(base.colours))


def active_puppies(db) -> int:
    return q(db, "SELECT count(*) AS n FROM puppies WHERE is_active")[0]["n"]


@pytest.fixture
def webhook(settings, monkeypatch):
    """A configured admin-panel webhook (so requests get outbox rows), with delivery switched off: no network."""
    from app.services import notify
    monkeypatch.setattr(notify, "deliver_due", lambda *a, **k: 0)
    settings.webhook_url = "https://panel.example/hook"
    settings.webhook_secret = "s" * 32
    return settings


# ================================================================ contacts: list / card / edit
def test_contact_search_by_name_and_by_phone_in_any_format(client, manager_h, make_lead, db):
    new_lead(make_lead, db, 1, name="Мария Петрова")
    new_lead(make_lead, db, 2, name="Иван")
    new_lead(make_lead, db, 3, name="Олег")

    def found(text_):
        r = client.get(f"{A}/contacts", params={"q": text_}, headers=manager_h)
        assert r.status_code == 200, r.text
        return sorted(x["phone"] for x in r.json()["items"])

    assert found("мария") == [e164(1)]                  # part of the name, any case
    assert found("ПЕТРОВ") == [e164(1)]
    assert found("8 (902) 555-02-02") == [e164(2)]      # the whole number typed with 8
    assert found("+7 903 555 03 03") == [e164(3)]       # or with +7 and spaces
    assert found("5550303") == [e164(3)]                # or only a part of it
    assert found("%") == []                             # LIKE wildcards are literal
    assert found("555") == []                           # 3 digits: not a phone search
    rows = client.get(f"{A}/contacts", headers=manager_h).json()
    assert rows["total"] == 3
    assert {x["phone_display"] for x in rows["items"]} == {phone(1), phone(2), phone(3)}


def test_contact_list_counts_requests_and_filters_blocked(client, manager_h, make_lead, db):
    first = new_lead(make_lead, db, 4, breed="maltipu")
    child = new_lead(make_lead, db, 4, breed="maltipu")       # a repeat request: attached to the first one
    won = new_lead(make_lead, db, 4, breed="toj-pudel")
    new_lead(make_lead, db, 5)
    assert one(db, "SELECT parent_id FROM leads WHERE id = :i", i=child)["parent_id"] == first
    sql(db, "UPDATE leads SET status = 'won', closed_at = now() WHERE id = :i", i=won)
    c4, c5 = contact_id(db, 4), contact_id(db, 5)
    assert client.patch(f"{A}/contacts/{c5}", json={"is_blocked": True}, headers=manager_h).status_code == 200

    rows = {x["id"]: x for x in client.get(f"{A}/contacts", headers=manager_h).json()["items"]}
    assert (rows[c4]["leads_count"], rows[c4]["open_leads"]) == (3, 1)
    assert (rows[c5]["leads_count"], rows[c5]["open_leads"]) == (1, 1)
    blocked = client.get(f"{A}/contacts", params={"blocked": "true"}, headers=manager_h).json()
    assert [x["id"] for x in blocked["items"]] == [c5] and blocked["total"] == 1
    other = client.get(f"{A}/contacts", params={"blocked": "false"}, headers=manager_h).json()
    assert [x["id"] for x in other["items"]] == [c4]


def test_contact_card_shows_requests_consents_links_and_the_view_is_audited(client, manager_h, manager_user,
                                                                            make_lead, db):
    l1 = new_lead(make_lead, db, 6, breed="maltipu", contact="whatsapp")
    l2 = new_lead(make_lead, db, 6, breed="toj-pudel", contact="whatsapp")
    c = contact_id(db, 6)
    r = client.get(f"{A}/contacts/{c}", headers=manager_h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["phone"] == e164(6) and d["phone_display"] == phone(6) and d["preferred_channel"] == "whatsapp"
    assert [x["id"] for x in d["leads"]] == [l2, l1]                   # newest first, every breed
    assert (d["leads_count"], d["open_leads"]) == (2, 2)
    assert d["aliases"] == []
    assert sorted(x["lead_id"] for x in d["consents"]) == [l1, l2]
    assert all(x["version"] == PROCESSING and x["withdrawn_at"] is None and x["given_at"] for x in d["consents"])
    assert d["links"]["tel"] == "tel:" + e164(6)
    assert d["links"]["whatsapp"] == "https://wa.me/" + e164(6)[1:]
    assert d["links"]["preferred"] == d["links"]["whatsapp"]
    # looking at a person's card is personal-data processing: it is in the audit log, without the data itself
    audit = sql(db, "SELECT actor_id, target, details::text AS d FROM audit_log WHERE action = 'view_contact'")
    assert [(a["actor_id"], a["target"]) for a in audit] == [(manager_user.id, f"contact:{c}")]
    assert e164(6)[2:] not in audit[0]["d"]
    assert client.get(f"{A}/contacts/999999", headers=manager_h).status_code == 404
    assert client.get(f"{A}/contacts/{c}").status_code == 401
    assert client.get(f"{A}/contacts").status_code == 401


def test_contact_patch_updates_the_card(client, manager_h, make_lead, db):
    lid = new_lead(make_lead, db, 7, contact="telegram", name="Аня")
    c = contact_id(db, 7)
    r = client.patch(f"{A}/contacts/{c}", headers=manager_h, json={
        "name": "  Анна Смирнова ", "preferred_channel": "call", "telegram_username": "@anna_smirnova",
        "notes": "Хочет девочку\nкремовую", "is_blocked": False})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == "Анна Смирнова"
    assert d["preferred_channel"] == "call"
    assert d["telegram_username"] == "anna_smirnova"                    # stored without «@»
    assert d["notes"] == "Хочет девочку\nкремовую"
    assert d["links"]["telegram"] == "https://t.me/anna_smirnova"
    assert d["links"]["preferred"] == "tel:" + e164(7)
    # the request card links to the username too, and keeps the name as the person typed it
    lead = client.get(f"{A}/leads/{lid}", headers=manager_h).json()
    assert lead["links"]["telegram"] == "https://t.me/anna_smirnova" and lead["name"] == "Аня"

    r = client.patch(f"{A}/contacts/{c}", json={"telegram_username": None, "notes": None}, headers=manager_h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["telegram_username"] is None and d["notes"] is None and d["name"] == "Анна Смирнова"
    assert d["links"]["telegram"] == "https://t.me/" + e164(7)
    fields = [x["d"]["fields"] for x in sql(db, "SELECT details AS d FROM audit_log WHERE action = 'contact_edit' "
                                                "ORDER BY id")]
    assert fields == [["is_blocked", "name", "notes", "preferred_channel", "telegram_username"],
                      ["notes", "telegram_username"]]


@pytest.mark.parametrize("body", [
    {"phone": "+79990000000"},                 # the number is the person's identity: not editable here
    {"is_admin": True},
    {"telegram_username": "anna smirnova"},
    {"telegram_username": "@ab"},
    {"preferred_channel": "pigeon"},
    {"name": "   "},
    {"name": "Я" * 101},
    {"notes": "x" * 4001},
])
def test_contact_patch_rejects_unknown_fields_and_bad_values(client, manager_h, make_lead, db, body):
    new_lead(make_lead, db, 8, name="Ольга")
    c = contact_id(db, 8)
    r = client.patch(f"{A}/contacts/{c}", json=body, headers=manager_h)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation"
    row = one(db, "SELECT phone, name, telegram_username, preferred_channel, notes FROM contacts WHERE id = :c", c=c)
    assert row == {"phone": e164(8), "name": "Ольга", "telegram_username": None, "preferred_channel": "telegram",
                   "notes": None}


@pytest.mark.parametrize("field", ["name", "is_blocked"])
def test_contact_patch_null_for_a_required_field_is_a_validation_error(client, manager_h, make_lead, db, field):
    new_lead(make_lead, db, 9, name="Ольга")
    c = contact_id(db, 9)
    r = client.patch(f"{A}/contacts/{c}", json={field: None}, headers=manager_h)
    assert r.status_code == 422, r.text
    assert one(db, "SELECT name, is_blocked FROM contacts WHERE id = :c", c=c) == {"name": "Ольга",
                                                                                   "is_blocked": False}


def test_requests_of_a_blocked_contact_are_kept_as_spam_without_notifications(client, manager_h, make_lead, db,
                                                                              webhook):
    first = new_lead(make_lead, db, 10)
    c = contact_id(db, 10)
    assert count(db, "outbox", "lead_id = :i", i=first) == 1
    assert client.patch(f"{A}/contacts/{c}", json={"is_blocked": True}, headers=manager_h).status_code == 200

    r = client.post("/api/v1/leads", json=lead_payload(phone=phone(10), name="Бот", breed="toj-pudel"))
    assert r.status_code == 201, r.text                       # the sender sees an ordinary success
    row = one(db, "SELECT id, contact_id, status, spam_reason, name FROM leads WHERE public_id = :p", p=r.json()["id"])
    assert (row["contact_id"], row["status"], row["spam_reason"], row["name"]) == (c, "spam", "blocked_contact", "Бот")
    assert count(db, "outbox", "lead_id = :i", i=row["id"]) == 0  # nobody is pinged about it
    spam = client.get(f"{A}/leads", params={"status": "spam"}, headers=manager_h).json()
    assert [x["id"] for x in spam["items"]] == [row["id"]]     # but it is not lost: a manager can find it


def test_a_form_never_renames_a_contact(client, manager_h, make_lead, db):
    """Anyone who knows a number could otherwise rename that person in the admin panel."""
    new_lead(make_lead, db, 11, name="Ольга")
    c = contact_id(db, 11)
    client.patch(f"{A}/contacts/{c}", json={"name": "Ольга Викторовна (заводчик)"}, headers=manager_h)
    lid = new_lead(make_lead, db, 11, name="Кто-то другой", breed="toj-pudel")
    assert one(db, "SELECT name FROM contacts WHERE id = :c", c=c)["name"] == "Ольга Викторовна (заводчик)"
    assert one(db, "SELECT contact_id, name FROM leads WHERE id = :i", i=lid) == {"contact_id": c,
                                                                                 "name": "Кто-то другой"}


def test_contact_activity_shows_only_the_persons_browsers_and_obeys_the_switch(client, manager_h, make_lead, db,
                                                                               settings):
    mine, other = uuid.uuid4(), uuid.uuid4()
    beacon(client, mine, n=3)
    beacon(client, other, n=2)
    new_lead(make_lead, db, 26, visitor_id=str(mine))
    new_lead(make_lead, db, 27, visitor_id=str(other))
    c = contact_id(db, 26)
    r = client.get(f"{A}/contacts/{c}/events", headers=manager_h)
    assert r.status_code == 200, r.text
    ev = r.json()
    assert [e["path"] for e in ev] == ["/maltipu/2/", "/maltipu/1/", "/maltipu/0/"]     # newest first
    page2 = client.get(f"{A}/contacts/{c}/events", params={"before_id": ev[0]["id"], "limit": 1},
                       headers=manager_h).json()
    assert [e["id"] for e in page2] == [ev[1]["id"]]
    assert client.get(f"{A}/contacts/999999/events", headers=manager_h).status_code == 404
    # the consent no longer names this purpose → the panel shows nothing
    settings.link_site_activity = False
    assert client.get(f"{A}/contacts/{c}/events", headers=manager_h).json() == []


# ================================================================ merge
def test_merge_moves_requests_and_consents_and_keeps_the_old_phone_as_an_alias(client, manager_h, manager_user,
                                                                               make_lead, db):
    a1 = new_lead(make_lead, db, 12, name="Света", breed="maltipu")
    a2 = new_lead(make_lead, db, 12, name="Света", breed="toj-pudel")
    b1 = new_lead(make_lead, db, 13, name="Светлана", breed="border-kolli")
    src, dst = contact_id(db, 12), contact_id(db, 13)
    client.patch(f"{A}/contacts/{src}", json={"notes": "Звонить после 18", "telegram_username": "sveta_tg"},
                 headers=manager_h)
    client.patch(f"{A}/contacts/{dst}", json={"notes": "Постоянный клиент"}, headers=manager_h)
    sql(db, "UPDATE contacts SET first_seen_at = now() - interval '100 days' WHERE id = :c", c=src)
    src_first_seen = one(db, "SELECT first_seen_at FROM contacts WHERE id = :c", c=src)["first_seen_at"]

    r = merge(client, manager_h, src, dst)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["id"] == dst and d["phone"] == e164(13) and d["name"] == "Светлана"
    assert sorted(x["id"] for x in d["leads"]) == sorted([a1, a2, b1])
    assert (d["leads_count"], d["open_leads"]) == (3, 3)
    assert d["aliases"] == [e164(12)]
    assert sorted(x["lead_id"] for x in d["consents"]) == sorted([a1, a2, b1])
    assert d["telegram_username"] == "sveta_tg"
    assert d["notes"] == f"Постоянный клиент\n\n[из контакта {src}] Звонить после 18"
    assert one(db, "SELECT first_seen_at FROM contacts WHERE id = :c", c=dst)["first_seen_at"] == src_first_seen

    # the old record is gone and nothing points at it
    assert client.get(f"{A}/contacts/{src}", headers=manager_h).status_code == 404
    assert count(db, "leads", "contact_id = :c", c=src) == 0
    assert count(db, "consents", "contact_id = :c", c=src) == 0
    # the moved requests say so in their history
    hist = sql(db, "SELECT lead_id, old_value, new_value, actor_id FROM lead_history WHERE action = 'merged' "
                   "ORDER BY lead_id")
    assert hist == [{"lead_id": lid, "old_value": f"контакт {src}", "new_value": f"контакт {dst}",
                     "actor_id": manager_user.id} for lid in sorted([a1, a2])]
    assert one(db, "SELECT details FROM audit_log WHERE action = 'merge'")["details"] == {"merged": src, "leads": 2}
    # the request card now shows the person's other requests across both numbers
    card = client.get(f"{A}/leads/{b1}", headers=manager_h).json()
    assert sorted(x["id"] for x in card["other_leads"]) == sorted([a1, a2])
    # and the person is found by the old number
    found = client.get(f"{A}/contacts", params={"q": "8 912 555-12-12"}, headers=manager_h).json()
    assert [x["id"] for x in found["items"]] == [dst]


def test_a_later_request_from_the_old_phone_joins_the_surviving_contact(client, admin_h, make_lead, db):
    a1 = new_lead(make_lead, db, 14, breed="maltipu")
    new_lead(make_lead, db, 15, breed="toj-pudel")
    src, dst = contact_id(db, 14), contact_id(db, 15)
    assert merge(client, admin_h, src, dst).status_code == 200
    people = count(db, "contacts")

    a2 = new_lead(make_lead, db, 14, breed="maltipu", name="Другое имя")
    row = one(db, "SELECT contact_id, parent_id, status, is_repeat FROM leads WHERE id = :i", i=a2)
    # same person, same breed, the first request still open: one card for the manager
    assert row == {"contact_id": dst, "parent_id": a1, "status": "duplicate", "is_repeat": True}
    assert count(db, "contacts") == people
    assert one(db, "SELECT count(*) AS n FROM consents WHERE lead_id = :i AND contact_id = :c", i=a2, c=dst)["n"] == 1
    # a request taken by phone from the old number goes there too
    r = client.post(f"{A}/leads", headers=admin_h, json={"origin": "phone", "name": "Света", "phone": "8 914 555 14 14",
                                                         "breed": "border-kolli"})
    assert r.status_code == 201, r.text
    assert r.json()["contact_id"] == dst
    assert count(db, "contacts") == people


def test_merge_chain_keeps_every_old_phone(client, manager_h, make_lead, db):
    for n in (16, 17, 18):
        new_lead(make_lead, db, n)
    c16, c17, c18 = contact_id(db, 16), contact_id(db, 17), contact_id(db, 18)
    assert merge(client, manager_h, c16, c17).status_code == 200
    r = merge(client, manager_h, c17, c18)
    assert r.status_code == 200, r.text
    assert sorted(r.json()["aliases"]) == [e164(16), e164(17)]
    assert r.json()["leads_count"] == 3
    lid = new_lead(make_lead, db, 16, breed="border-kolli")
    assert one(db, "SELECT contact_id FROM leads WHERE id = :i", i=lid)["contact_id"] == c18
    assert count(db, "contacts") == 1


def test_merge_into_itself_or_a_missing_contact_changes_nothing(client, manager_h, make_lead, db):
    lid = new_lead(make_lead, db, 19)
    c = contact_id(db, 19)
    r = merge(client, manager_h, c, c)
    assert r.status_code == 422 and "into_id" in r.json()["error"]["fields"]
    assert merge(client, manager_h, c, 999999).status_code == 404
    assert merge(client, manager_h, 999999, c).status_code == 404
    assert client.post(f"{A}/contacts/{c}/merge", json={}, headers=manager_h).status_code == 422
    assert one(db, "SELECT contact_id FROM leads WHERE id = :i", i=lid)["contact_id"] == c
    assert count(db, "contact_aliases") == 0
    assert count(db, "lead_history", "action = 'merged'") == 0


# ================================================================ erase (152-ФЗ)
def _person_with_everything(client, admin_h, make_lead, db) -> dict:
    """Пётр: three requests from one browser (one of them a repeat), a second number merged in, a manager's comment
    with his number, notifications, a visit with page views. Ольга: someone else who must stay untouched."""
    vid = uuid.uuid4()
    l1 = new_lead(make_lead, db, 20, name="Пётр Иванов", breed="maltipu", visitor_id=str(vid),
                  note="Хочет мальчика", form_title="Узнать цену щенка")
    l2 = new_lead(make_lead, db, 20, name="Пётр Иванов", breed="maltipu", visitor_id=str(vid))
    l3 = new_lead(make_lead, db, 20, name="Пётр Иванов", breed="toj-pudel", visitor_id=str(vid),
                  utm={"utm_source": "yandex", "utm_campaign": "maltipu"})
    l4 = new_lead(make_lead, db, 21, name="Петя", breed="border-kolli")   # his second number, another browser
    beacon(client, vid, n=3)
    p, p2 = contact_id(db, 20), contact_id(db, 21)
    assert merge(client, admin_h, p2, p).status_code == 200
    r = client.post(f"{A}/leads/{l1}/comments", json={"text": "Пётр просил перезвонить на +7 920 555-20-20"},
                    headers=admin_h)
    assert r.status_code == 200, r.text
    ovid = uuid.uuid4()
    other = new_lead(make_lead, db, 22, name="Ольга", breed="francuzskij-buldog", visitor_id=str(ovid))
    beacon(client, ovid, n=2)
    client.post(f"{A}/leads/{other}/comments", json={"text": "Ольга — постоянный клиент"}, headers=admin_h)
    visitors = [str(vid)] + [str(r["visitor_id"]) for r in sql(db, "SELECT visitor_id FROM leads WHERE id = :i", i=l4)]
    return {"p": p, "leads": [l1, l2, l3, l4], "visitors": visitors, "other": other, "ovid": str(ovid)}


def test_erase_destroys_the_persons_data_and_keeps_the_requests_anonymous(client, admin_h, admin_user, make_lead,
                                                                          db, webhook):
    s = _person_with_everything(client, admin_h, make_lead, db)
    mine, vids = s["leads"], s["visitors"]
    assert one(db, "SELECT parent_id FROM leads WHERE id = :i", i=mine[1])["parent_id"] == mine[0]
    comments = count(db, "lead_history", "lead_id = ANY(:ids) AND comment IS NOT NULL", ids=mine)
    outbox = count(db, "outbox", "lead_id = ANY(:ids)", ids=mine)
    assert comments >= 2 and outbox >= 4

    r = erase(client, admin_h, s["p"], reason="withdrawal", subject="Иванов Пётр, заявление от 16.10.2026")
    assert r.status_code == 200, r.text
    counts = r.json()["counts"]
    assert r.json()["erased"] is True
    assert counts == {"leads_anonymised": 4, "comments_cleared": comments, "notifications_deleted": outbox,
                      "consents_deleted": 4, "aliases_deleted": 1, "events_deleted": 3, "visits_deleted": 1,
                      "browsers_deleted": 2, "contacts_deleted": 1}

    # the requests stay (statistics), without anything that identifies the person
    rows = sql(db, "SELECT * FROM leads WHERE id = ANY(:ids) ORDER BY id", ids=mine)
    assert len(rows) == 4
    for row in rows:
        assert row["anonymised_at"] is not None
        for col in ("contact_id", "name", "phone", "ip", "user_agent", "note", "form_title", "page_title",
                    "referrer_host", "visitor_id", "session_id", "idempotency_key", "request_sha256", "utm"):
            assert row[col] is None, (row["id"], col)
        assert row["details"] == {} and row["breed_id"] is not None and row["consent_version"] == PROCESSING
    assert count(db, "lead_history", "lead_id = ANY(:ids) AND comment IS NOT NULL", ids=mine) == 0
    assert count(db, "lead_history", "lead_id = ANY(:ids) AND action = 'merged' "
                                     "AND (old_value IS NOT NULL OR new_value IS NOT NULL)", ids=mine) == 0
    assert count(db, "lead_history", "lead_id = ANY(:ids)", ids=mine) > 0      # the work history stays
    assert count(db, "outbox", "lead_id = ANY(:ids)", ids=mine) == 0
    assert count(db, "consents", "lead_id = ANY(:ids) OR contact_id = :c", ids=mine, c=s["p"]) == 0
    assert count(db, "contact_aliases") == 0
    assert count(db, "contacts", "id = :c", c=s["p"]) == 0
    assert count(db, "visitors", "id::text = ANY(:v)", v=vids) == 0
    assert count(db, "sessions", "visitor_id::text = ANY(:v)", v=vids) == 0
    assert count(db, "site_events", "visitor_id::text = ANY(:v)", v=vids) == 0
    assert sql(db, "SELECT name, phone, contact_id FROM leads_all WHERE lead_id = ANY(:ids)", ids=mine) == \
        [{"name": None, "phone": None, "contact_id": None}] * 4

    # nothing of the person is left anywhere in the database (the erasure record names the subject by design)
    tables = [r["t"] for r in sql(db, "SELECT tablename AS t FROM pg_tables WHERE schemaname = current_schema() "
                                      "AND tablename NOT IN ('erasure_log', 'alembic_version')")]
    for needle in ("Пётр", "Петя", "9205552020", "9215552121", "920 555", vids[0], vids[1]):
        for t in tables:
            assert count(db, f'"{t}" x', "x::text LIKE :n", n=f"%{needle}%") == 0, (t, needle)

    # the other person is untouched
    o = one(db, "SELECT name, phone, contact_id, anonymised_at FROM leads WHERE id = :i", i=s["other"])
    assert (o["name"], o["phone"], o["anonymised_at"]) == ("Ольга", e164(22), None)
    assert count(db, "consents", "contact_id = :c", c=o["contact_id"]) == 1
    assert count(db, "outbox", "lead_id = :i", i=s["other"]) == 1
    assert count(db, "lead_history", "lead_id = :i AND comment = 'Ольга — постоянный клиент'", i=s["other"]) == 1
    assert count(db, "site_events", "visitor_id::text = :v", v=s["ovid"]) == 2
    assert count(db, "sessions", "visitor_id::text = :v", v=s["ovid"]) == 1

    # the erasure record (акт об уничтожении ПД) and the audit trail
    log = sql(db, "SELECT actor_id, actor_label, subject, reason, counts, categories FROM erasure_log")
    assert len(log) == 1
    assert (log[0]["actor_id"], log[0]["actor_label"], log[0]["reason"]) == (admin_user.id, "Анна", "withdrawal")
    assert log[0]["subject"] == "Иванов Пётр, заявление от 16.10.2026"
    assert log[0]["counts"] == counts and "номер телефона" in log[0]["categories"]
    assert one(db, "SELECT target FROM audit_log WHERE action = 'erase'")["target"] == f"contact:{s['p']}"


def test_erased_requests_still_count_in_the_breed_bases_and_stats(client, admin_h, make_lead, db):
    s = _person_with_everything(client, admin_h, make_lead, db)

    def snapshot():
        breeds = client.get(f"{A}/breeds", headers=admin_h).json()
        st = client.get(f"{A}/stats", headers=admin_h).json()
        cnt = client.get(f"{A}/leads/counts", params={"group_by": "breed"}, headers=admin_h).json()
        return (breeds, st["totals"], sorted(st["by_breed"], key=lambda x: x["breed"]),
                sorted(st["by_kind"], key=lambda x: x["kind"]), sorted(st["by_status"], key=lambda x: x["status"]),
                sorted(cnt, key=lambda x: x["breed"]))

    before = snapshot()
    by_key = {b["key"]: b["total"] for b in before[0]}
    assert (by_key["maltipu"], by_key["pudel"], by_key["kolli"], by_key["buldog"]) == (1, 1, 1, 1)
    assert before[1]["leads"] == 4
    assert erase(client, admin_h, s["p"]).status_code == 200
    assert snapshot() == before
    maltipu = client.get(f"{A}/leads", params={"breed": "maltipu"}, headers=admin_h).json()
    assert [x["id"] for x in maltipu["items"]] == [s["leads"][0]] and maltipu["items"][0]["name"] is None


def test_an_anonymised_request_cannot_be_edited_commented_or_taken(client, admin_h, make_lead, db):
    lid = new_lead(make_lead, db, 23)
    assert erase(client, admin_h, contact_id(db, 23)).status_code == 200
    d = client.get(f"{A}/leads/{lid}", headers=admin_h).json()
    assert d["anonymised_at"] and d["name"] is None and d["phone"] is None and d["contact_id"] is None
    assert d["links"] == {} and d["journey"] is None and d["phone_display"] is None
    hist = count(db, "lead_history", "lead_id = :i", i=lid)

    r = client.patch(f"{A}/leads/{lid}", json={"version": d["version"], "status": "in_progress"}, headers=admin_h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "anonymised"
    r = client.patch(f"{A}/leads/{lid}", json={"status": "in_progress"}, headers={**admin_h, "If-Match": str(d["version"])})
    assert r.status_code == 409
    assert client.post(f"{A}/leads/{lid}/comments", json={"text": "Новый номер: +7 999 000-00-00"},
                       headers=admin_h).status_code == 409
    assert client.post(f"{A}/leads/{lid}/take", headers=admin_h).status_code == 409
    row = one(db, "SELECT status, assignee_id, version FROM leads WHERE id = :i", i=lid)
    assert (row["status"], row["assignee_id"], row["version"]) == ("new", None, d["version"])
    assert count(db, "lead_history", "lead_id = :i", i=lid) == hist


def test_a_new_request_after_erasure_starts_a_fresh_contact(client, admin_h, make_lead, db):
    old_lead = new_lead(make_lead, db, 24, breed="maltipu")
    old = contact_id(db, 24)
    assert erase(client, admin_h, old).status_code == 200
    assert contact_id(db, 24) is None

    lid = new_lead(make_lead, db, 24, breed="maltipu", name="Пётр")
    new = contact_id(db, 24)
    assert new is not None and new != old
    row = one(db, "SELECT contact_id, parent_id, status, is_repeat FROM leads WHERE id = :i", i=lid)
    assert row == {"contact_id": new, "parent_id": None, "status": "new", "is_repeat": False}
    d = client.get(f"{A}/contacts/{new}", headers=admin_h).json()
    assert [x["id"] for x in d["leads"]] == [lid] and [x["lead_id"] for x in d["consents"]] == [lid]
    assert one(db, "SELECT contact_id FROM leads WHERE id = :i", i=old_lead)["contact_id"] is None


def test_erase_is_admin_only_and_validated(client, admin_h, manager_h, make_lead, db):
    lid = new_lead(make_lead, db, 25, name="Ольга")
    c = contact_id(db, 25)
    good = {"reason": "request", "subject": "Ольга"}
    assert client.post(f"{A}/contacts/{c}/erase", json=good).status_code == 401
    r = client.post(f"{A}/contacts/{c}/erase", json=good, headers=manager_h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    for bad in ({"reason": "because", "subject": "Ольга"}, {"reason": "request", "subject": "   "},
                {"reason": "request"}, {"subject": "Ольга"}, {"reason": "request", "subject": "О" * 201}):
        assert client.post(f"{A}/contacts/{c}/erase", json=bad, headers=admin_h).status_code == 422, bad
    assert client.post(f"{A}/contacts/999999/erase", json=good, headers=admin_h).status_code == 404
    assert one(db, "SELECT name, contact_id FROM leads WHERE id = :i", i=lid) == {"name": "Ольга", "contact_id": c}
    assert count(db, "consents", "contact_id = :c", c=c) == 1
    assert count(db, "erasure_log") == 0


# ================================================================ retention (python -m app purge)
def test_retention_deletes_old_spam_only(client, make_lead, db):
    from app.services import retention
    old_spam = new_lead(make_lead, db, 30)
    child = new_lead(make_lead, db, 30)                     # attached to it before it was marked spam
    new_spam = new_lead(make_lead, db, 31)
    old_real = new_lead(make_lead, db, 32)
    sql(db, "UPDATE leads SET status = 'spam', spam_reason = 'manual', created_at = now() - interval '31 days' "
            "WHERE id = :i", i=old_spam)
    sql(db, "UPDATE leads SET status = 'spam', spam_reason = 'manual', created_at = now() - interval '5 days' "
            "WHERE id = :i", i=new_spam)
    sql(db, "UPDATE leads SET created_at = now() - interval '400 days' WHERE id = :i", i=old_real)

    out = retention.run(db)
    assert out["spam_deleted"] == 1
    assert {r["id"] for r in sql(db, "SELECT id FROM leads")} == {child, new_spam, old_real}
    assert one(db, "SELECT parent_id FROM leads WHERE id = :i", i=child)["parent_id"] is None
    assert count(db, "lead_history", "lead_id = :i", i=old_spam) == 0
    # the consent proof stays with the person until the person is erased
    assert count(db, "consents", "contact_id = :c", c=contact_id(db, 30)) == 2
    assert retention.run(db)["spam_deleted"] == 0


def test_retention_clears_ip_of_old_requests_but_consents_keep_theirs(client, make_lead, db):
    from app.services import retention
    old = new_lead(make_lead, db, 33)
    recent = new_lead(make_lead, db, 34)
    sql(db, "UPDATE leads SET created_at = now() - interval '31 days' WHERE id = :i", i=old)

    out = retention.run(db)
    assert out["lead_ips_cleared"] == 1
    q_ = "SELECT host(ip) AS ip, user_agent, name, phone FROM leads WHERE id = :i"
    assert one(db, q_, i=old) == {"ip": None, "user_agent": None, "name": "Анна", "phone": e164(33)}
    assert one(db, q_, i=recent) == {"ip": "203.0.113.10", "user_agent": "testclient", "name": "Анна",
                                     "phone": e164(34)}
    proof = sql(db, "SELECT host(ip) AS ip, user_agent FROM consents WHERE lead_id IN (:a, :b)", a=old, b=recent)
    assert proof == [{"ip": "203.0.113.10", "user_agent": "testclient"}] * 2


def test_retention_deletes_old_activity_but_keeps_browsers_linked_to_requests(client, make_lead, db):
    from app.services import retention
    anon, linked, fresh = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    beacon(client, anon, n=2)
    beacon(client, linked, n=2)
    beacon(client, fresh, n=1)
    lid = new_lead(make_lead, db, 35, visitor_id=str(linked))
    old = "now() - interval '200 days'"
    ids = [str(anon), str(linked)]
    sql(db, f"UPDATE site_events SET received_at = {old}, occurred_at = {old} WHERE visitor_id::text = ANY(:v)", v=ids)
    sql(db, f"UPDATE sessions SET started_at = {old}, last_seen_at = {old} WHERE visitor_id::text = ANY(:v)", v=ids)
    sql(db, f"UPDATE visitors SET first_seen_at = {old}, last_seen_at = {old} WHERE id::text = ANY(:v)", v=ids)

    out = retention.run(db)
    assert (out["events_deleted"], out["visits_deleted"], out["browsers_deleted"]) == (4, 2, 1)

    def left(v):
        return (count(db, "visitors", "id = :v", v=v), count(db, "sessions", "visitor_id = :v", v=v),
                count(db, "site_events", "visitor_id = :v", v=v))
    assert left(anon) == (0, 0, 0)
    assert left(linked) == (1, 0, 0)             # the request's «first came from» stays
    assert left(fresh) == (1, 1, 1)
    assert str(one(db, "SELECT visitor_id FROM leads WHERE id = :i", i=lid)["visitor_id"]) == str(linked)


def test_retention_erases_people_not_seen_for_three_years_unless_a_request_is_open(client, make_lead, db):
    from app.services import retention
    gone = new_lead(make_lead, db, 36, name="Давний")
    still_open = new_lead(make_lead, db, 37)
    recent = new_lead(make_lead, db, 38)
    sql(db, "UPDATE leads SET status = 'won', closed_at = now(), sale_amount = 90000 WHERE id IN (:a, :b)",
        a=gone, b=recent)
    sql(db, "UPDATE contacts SET last_seen_at = now() - interval '1100 days' WHERE phone IN (:a, :b)",
        a=e164(36), b=e164(37))

    out = retention.run(db)
    assert out["contacts_erased"] == 1
    assert contact_id(db, 36) is None
    assert contact_id(db, 37) is not None and contact_id(db, 38) is not None
    row = one(db, "SELECT name, phone, contact_id, anonymised_at, status, sale_amount FROM leads WHERE id = :i", i=gone)
    assert (row["name"], row["phone"], row["contact_id"], row["status"], int(row["sale_amount"])) == \
        (None, None, None, "won", 90000)
    assert row["anonymised_at"] is not None
    assert one(db, "SELECT name FROM leads WHERE id = :i", i=still_open)["name"] == "Анна"
    log = sql(db, "SELECT actor_id, actor_label, reason, counts FROM erasure_log")
    assert len(log) == 1
    assert (log[0]["actor_id"], log[0]["actor_label"], log[0]["reason"]) == (None, "Система", "retention")
    assert log[0]["counts"]["leads_anonymised"] == 1 and log[0]["counts"]["consents_deleted"] == 1
    assert retention.run(db)["contacts_erased"] == 0
    assert count(db, "erasure_log") == 1


def test_retention_housekeeping_keeps_pending_notifications_and_recent_records(client, make_lead, db):
    from app.services import retention
    lid = new_lead(make_lead, db, 39)
    for status, days, target in (("sent", 31, "a"), ("failed", 31, "b"), ("pending", 31, "c"), ("sent", 5, "d")):
        sql(db, "INSERT INTO outbox (channel, target, event, lead_id, status, created_at) "
                "VALUES ('webhook', :t, 'lead.updated', :l, :s, now() - make_interval(days => :d))",
            t=target, l=lid, s=status, d=days)
    for days in (1100, 1000):
        sql(db, "INSERT INTO erasure_log (at, actor_label, subject, reason, categories, counts) "
                "VALUES (now() - make_interval(days => :d), 'Система', :s, 'retention', '[]', '{}')",
            d=days, s=f"контакт {days}")
    for days in (400, 10):
        sql(db, "INSERT INTO audit_log (at, actor_label, action) VALUES (now() - make_interval(days => :d), 'x', "
                ":a)", d=days, a=f"login{days}")
    out = retention.run(db)
    assert (out["outbox_deleted"], out["erasure_records_deleted"], out["audit_deleted"]) == (2, 1, 1)
    assert sorted(r["target"] for r in sql(db, "SELECT target FROM outbox")) == ["c", "d"]  # undelivered stays
    assert [r["subject"] for r in sql(db, "SELECT subject FROM erasure_log")] == ["контакт 1000"]
    assert [r["action"] for r in sql(db, "SELECT action FROM audit_log")] == ["login10"]


def test_retention_clears_the_user_agent_even_when_the_ip_is_unknown(db):
    """nginx (a trusted proxy) passed an X-Real-IP the app cannot parse: the request is saved without an IP."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import retention
    from conftest import ORIGIN
    with TestClient(app, client=("127.0.0.1", 50000), headers={"Origin": ORIGIN, "X-Real-IP": "unknown",
                                                               "User-Agent": "Mozilla/5.0 (iPhone)"}) as c:
        r = c.post("/api/v1/leads", json=lead_payload(phone=phone(48)))
    assert r.status_code == 201, r.text
    row = one(db, "SELECT id, ip, user_agent FROM leads WHERE public_id = :p", p=r.json()["id"])
    assert (row["ip"], row["user_agent"]) == (None, "Mozilla/5.0 (iPhone)")
    sql(db, "UPDATE leads SET created_at = now() - interval '31 days' WHERE id = :i", i=row["id"])
    retention.run(db)
    assert one(db, "SELECT user_agent FROM leads WHERE id = :i", i=row["id"])["user_agent"] is None


# ================================================================ catalog sync and the per-breed bases
def test_every_breed_has_its_own_base_plus_general_and_all(client, admin_h, make_lead, db):
    m = new_lead(make_lead, db, 40, breed="maltipu")
    b = new_lead(make_lead, db, 41, breed="francuzskij-buldog")
    p = new_lead(make_lead, db, 42, kind="puppy", puppy=PUP_PUDEL, breed="")      # the puppy names the breed
    g = new_lead(make_lead, db, 43, breed="undecided")
    listed = client.get(f"{A}/breeds", headers=admin_h).json()

    views = leads_views(db)
    assert views == {"leads_all", "leads_general", "leads_maltipu", "leads_buldog", "leads_pudel", "leads_kolli"}
    assert {x["view"] for x in listed} == views - {"leads_all"}         # the panel names only existing views
    assert view_ids(db, "leads_maltipu") == [m]
    assert view_ids(db, "leads_buldog") == [b]
    assert view_ids(db, "leads_pudel") == [p]
    assert view_ids(db, "leads_kolli") == []
    assert view_ids(db, "leads_general") == [g]
    assert view_ids(db, "leads_all") == sorted([m, b, p, g])
    row = q(db, "SELECT breed_key, breed, puppy_slug, puppy_name, name, phone FROM leads_pudel")[0]
    assert row == {"breed_key": "pudel", "breed": "Той-пудель", "puppy_slug": PUP_PUDEL, "puppy_name": "Марго",
                   "name": "Анна", "phone": e164(42)}


def test_sync_adds_a_new_puppy_and_is_idempotent(db):
    from app.services import catalog
    cat = site_catalog()
    cat.puppies.append({"slug": "maltipu-test-zefir-2026-10", "name": "Зефир", "breed": "maltipu", "status": "soon",
                        "sex": "female", "colour": "белый", "generation": "F1", "birth_date": "2026-10-01"})
    cat.puppies.append({"slug": "maltipu-test-strannyj-2026-10", "name": "Странный", "breed": "maltipu",
                        "status": "скоро", "sex": "кобель", "birth_date": "в октябре"})   # never breaks the sync
    st = catalog.sync(db, cat)
    assert (st["puppies_new"], st["puppies"], st["puppies_deactivated"]) == (2, 62, 0)
    rows = {r["slug"]: r for r in q(db, "SELECT p.slug, p.name, p.status, p.is_active, p.sex, p.birth_date::text AS bd, "
                                        "b.key FROM puppies p JOIN breeds b ON b.id = p.breed_id "
                                        "WHERE p.slug LIKE 'maltipu-test-%'")}
    assert rows["maltipu-test-zefir-2026-10"] == {"slug": "maltipu-test-zefir-2026-10", "name": "Зефир",
                                                  "status": "soon", "is_active": True, "sex": "female",
                                                  "bd": "2026-10-01", "key": "maltipu"}
    odd = rows["maltipu-test-strannyj-2026-10"]
    assert (odd["status"], odd["sex"], odd["bd"], odd["is_active"]) == ("available", None, None, True)
    st = catalog.sync(db, cat)
    assert (st["puppies_new"], st["puppies"]) == (0, 62)
    assert q(db, "SELECT count(*) AS n FROM puppies")[0]["n"] == 62


def test_a_puppy_removed_from_the_site_is_sold_and_its_requests_keep_it(client, make_lead, db):
    from app.services import catalog
    lid = new_lead(make_lead, db, 44, kind="puppy", puppy=PUP)
    pid = one(db, "SELECT id FROM puppies WHERE slug = :s", s=PUP)["id"]
    assert one(db, "SELECT puppy_id FROM leads WHERE id = :i", i=lid)["puppy_id"] == pid

    cat = site_catalog()
    cat.puppies = [p for p in cat.puppies if p["slug"] != PUP]
    st = catalog.sync(db, cat)
    assert st["puppies_deactivated"] == 1
    row = q(db, "SELECT is_active, status, deactivated_at FROM puppies WHERE slug = :s", s=PUP)[0]
    assert (row["is_active"], row["status"]) == (False, "sold") and row["deactivated_at"] is not None
    assert q(db, "SELECT puppy_id, puppy_slug FROM leads WHERE id = :i", i=lid) == [{"puppy_id": pid, "puppy_slug": PUP}]
    assert q(db, "SELECT puppy_slug, puppy_name FROM leads_maltipu WHERE lead_id = :i", i=lid) == \
        [{"puppy_slug": PUP, "puppy_name": "Пломбир"}]
    # back on the site: active again with the site's status
    catalog.sync(db, site_catalog())
    row = q(db, "SELECT is_active, status, deactivated_at FROM puppies WHERE slug = :s", s=PUP)[0]
    assert row == {"is_active": True, "status": "available", "deactivated_at": None}


def test_sync_refuses_to_deactivate_more_than_half_of_the_catalog_unless_forced(db):
    from app.services import catalog
    assert active_puppies(db) == 60
    cat = site_catalog()
    cat.puppies = cat.puppies[31:]                          # a truncated puppies.json: 31 of 60 missing
    with pytest.raises(catalog.CatalogError, match="31 of 60"):
        catalog.sync(db, cat)
    assert active_puppies(db) == 60
    assert catalog.sync(db, cat, force=True)["puppies_deactivated"] == 31
    assert active_puppies(db) == 29
    db.rollback()
    cat.puppies = site_catalog().puppies[30:]               # exactly half sold out at once is allowed
    assert catalog.sync(db, cat)["puppies_deactivated"] == 30


def test_sync_refuses_an_empty_puppy_list(db):
    from app.services import catalog
    cat = site_catalog()
    cat.puppies = []
    with pytest.raises(catalog.CatalogError, match="no puppies"):
        catalog.sync(db, cat)
    assert active_puppies(db) == 60
    assert "leads_maltipu" in leads_views(db)


def test_a_renamed_breed_key_keeps_the_breed_and_its_requests_and_renames_the_base(client, make_lead, db):
    from app.services import catalog
    lid = new_lead(make_lead, db, 45, breed="maltipu")
    bid = one(db, "SELECT id FROM breeds WHERE slug = 'maltipu'")["id"]
    cat = site_catalog()
    for b in cat.breeds:
        if b["slug"] == "maltipu":
            b["key"] = "maltipoo"
    st = catalog.sync(db, cat)
    assert st["breeds_deactivated"] == 0 and "leads_maltipoo" in st["views"]
    assert q(db, "SELECT id, key, is_active FROM breeds WHERE slug = 'maltipu'") == \
        [{"id": bid, "key": "maltipoo", "is_active": True}]
    assert q(db, "SELECT count(*) AS n FROM breeds")[0]["n"] == 4
    views = leads_views(db)
    assert "leads_maltipoo" in views and "leads_maltipu" not in views
    assert view_ids(db, "leads_maltipoo") == [lid]
    assert q(db, "SELECT count(*) AS n FROM puppies WHERE breed_id = :b AND is_active", b=bid)[0]["n"] == 15


def test_a_breed_removed_from_the_site_is_deactivated_but_keeps_its_base_and_requests(client, make_lead, db):
    from app.services import catalog
    lid = new_lead(make_lead, db, 46, breed="border-kolli")
    bid = one(db, "SELECT id FROM breeds WHERE key = 'kolli'")["id"]
    cat = site_catalog()
    cat.breeds = [b for b in cat.breeds if b["slug"] != "border-kolli"]
    cat.puppies = [p for p in cat.puppies if p["breed"] != "border-kolli"]
    st = catalog.sync(db, cat)
    assert (st["breeds_deactivated"], st["puppies_deactivated"]) == (1, 15)
    row = q(db, "SELECT is_active, deactivated_at FROM breeds WHERE id = :b", b=bid)[0]
    assert row["is_active"] is False and row["deactivated_at"] is not None
    assert "leads_kolli" in leads_views(db)
    assert view_ids(db, "leads_kolli") == [lid]
    assert q(db, "SELECT breed_id FROM leads WHERE id = :i", i=lid)[0]["breed_id"] == bid


def test_a_new_breed_gets_its_own_base(db):
    from app.services import catalog
    cat = site_catalog()
    cat.breeds.append({"slug": "shpic", "key": "shpic", "name": "Шпиц"})
    cat.puppies.append({"slug": "shpic-belyj-2026-10", "name": "Снежок", "breed": "shpic", "status": "available"})
    st = catalog.sync(db, cat)
    assert st["puppies_new"] == 1 and "leads_shpic" in st["views"]
    assert leads_views(db) == {"leads_all", "leads_general", "leads_maltipu", "leads_buldog", "leads_pudel",
                               "leads_kolli", "leads_shpic"}
    assert q(db, "SELECT b.key FROM puppies p JOIN breeds b ON b.id = p.breed_id WHERE p.slug = 'shpic-belyj-2026-10'"
             ) == [{"key": "shpic"}]
    assert view_ids(db, "leads_shpic") == []


def test_a_puppy_moved_to_another_breed_on_the_site_does_not_break_the_sync(client, make_lead, db):
    from app.services import catalog
    lid = new_lead(make_lead, db, 47, kind="puppy", puppy=PUP)
    pid = one(db, "SELECT id FROM puppies WHERE slug = :s", s=PUP)["id"]
    cat = site_catalog()
    for p in cat.puppies:
        if p["slug"] == PUP:
            p["breed"] = "toj-pudel"                         # a data-entry fix on the site
    catalog.sync(db, cat)
    db.flush()
    row = q(db, "SELECT l.puppy_id, b.key FROM leads l JOIN breeds b ON b.id = l.breed_id WHERE l.id = :i", i=lid)
    assert row == [{"puppy_id": pid, "key": "pudel"}]      # the request follows its puppy into the right base
    assert view_ids(db, "leads_pudel") == [lid]


# ================================================================ consent documents
@pytest.fixture
def consent_doc(tmp_path, settings):
    """(the real consent.json as a dict, write(data) → points the app at a temporary copy)."""
    from app.services import consent
    real = json.loads(Path(settings.consent_file).read_text(encoding="utf-8"))
    path = tmp_path / "consent.json"

    def write(data: dict) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        settings.consent_file = path
        consent.load.cache_clear()

    yield real, write
    consent.load.cache_clear()


def _version(data: dict, ver: str) -> dict:
    return next(v for v in data["versions"] if v["version"] == ver)


def test_consent_sync_with_the_published_texts_changes_nothing(consent_doc, db):
    from app.services import consent
    real, write = consent_doc
    write(copy.deepcopy(real))
    assert consent.sync(db) == {"consent_versions_added": []}


@pytest.mark.parametrize("field", ["body", "checkbox", "title"])
def test_consent_sync_refuses_an_edited_published_text(consent_doc, db, field):
    """People agreed to that exact text: a change must be a new version, never an edit."""
    from app.services import consent
    real, write = consent_doc
    data = copy.deepcopy(real)
    doc = _version(data, PROCESSING)
    doc[field] = doc[field] + ["Новый пункт."] if isinstance(doc[field], list) else doc[field] + " (изм.)"
    write(data)
    with pytest.raises(consent.ConsentError, match="edited"):
        consent.sync(db)
    db.rollback()
    stored = q(db, "SELECT text_sha256 FROM consent_versions WHERE version = :v", v=PROCESSING)[0]["text_sha256"]
    assert stored == consent.digest(_version(real, PROCESSING))


def test_consent_sync_adds_a_new_version_next_to_the_old_one(consent_doc, db):
    from app.services import consent
    real, write = consent_doc
    data = copy.deepcopy(real)
    new = copy.deepcopy(_version(data, PROCESSING))
    new["version"] = "processing-2026-12-01"
    new["body"] = new["body"] + ["Новая цель обработки."]
    data["versions"].append(new)
    data["current"]["processing"] = new["version"]
    write(data)
    assert consent.sync(db) == {"consent_versions_added": ["processing-2026-12-01"]}
    assert consent.current("processing") == "processing-2026-12-01"
    rows = {r["version"]: r for r in q(db, "SELECT version, kind, text_sha256 FROM consent_versions")}
    assert rows["processing-2026-12-01"]["text_sha256"] == consent.digest(new)
    assert rows[PROCESSING]["text_sha256"] == consent.digest(_version(real, PROCESSING))


def test_consent_file_with_a_current_version_that_does_not_exist_is_rejected(consent_doc, tmp_path):
    from app.services import consent
    real, _ = consent_doc
    data = copy.deepcopy(real)
    data["current"]["processing"] = "processing-2099-01-01"
    path = tmp_path / "bad-consent.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(consent.ConsentError, match="not among the versions"):
        consent.load(path)
    del data["current"]["processing"]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    consent.load.cache_clear()
    with pytest.raises(consent.ConsentError, match="no current processing"):
        consent.load(path)
