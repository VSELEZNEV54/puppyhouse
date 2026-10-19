"""Site events (POST /events), reviews (POST /reviews), client IP behind nginx, rate keys and input hygiene.

What matters here for a kennel: a beacon never breaks a page and never stores personal data it should not; a review
is never lost, carries both 152-ФЗ consents and publishes only «Анна К.»; the IP saved as proof of consent is the
browser's, not something a visitor can type into a header."""
from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from conftest import CONSENT_CURRENT, ORIGIN, lead_payload

UTC = dt.timezone.utc
EVENTS = "/api/v1/events"
REVIEWS = "/api/v1/reviews"
NOTHING = {"accepted": 0, "dropped": 0}


# ---------------------------------------------------------------- helpers

def beacon(visitor_id=None, session_id=None, events=None, **over) -> dict:
    """A batch as main.js flushEvents() builds it: context() + events."""
    b = {
        "visitor_id": str(visitor_id or uuid.uuid4()),
        "session_id": str(session_id or uuid.uuid4()),
        "landing": "/maltipu/",
        "referrer": "https://yandex.ru/search/?text=мальтипу",
        "utm": None,
        "events": events if events is not None else [
            {"type": "page_view", "path": "/maltipu/", "ts": _ms(dt.datetime.now(UTC)), "data": {"title": "Мальтипу"}},
        ],
    }
    b.update(over)
    return b


def _ms(t: dt.datetime) -> int:
    return int(t.timestamp() * 1000)


def send_beacon(client, body, **headers):
    """navigator.sendBeacon: a text/plain Blob, no preflight."""
    raw = body if isinstance(body, (str, bytes)) else json.dumps(body, ensure_ascii=False)
    h = {"Content-Type": "text/plain;charset=UTF-8"}
    h.update(headers)
    return client.post(EVENTS, content=raw.encode() if isinstance(raw, str) else raw, headers=h)


def events_rows(db, visitor_id=None):
    sql = "SELECT type, path, breed_key, puppy_slug, data, session_id, occurred_at, received_at FROM site_events"
    if visitor_id:
        return db.execute(text(sql + " WHERE visitor_id = :v ORDER BY id"), {"v": str(visitor_id)}).mappings().all()
    return db.execute(text(sql + " ORDER BY id")).mappings().all()


def count(db, table: str) -> int:
    return db.execute(text(f"SELECT count(*) FROM {table}")).scalar()


def review_payload(**over) -> dict:
    """What trust.js reviewPayload() sends."""
    p = {
        "name": "Анна Королёва", "phone": "+7 (916) 555-12-34", "city": "Москва", "breed": "maltipu", "rating": 5,
        "text": "Взяли у вас мальтипу, щенок здоровый и весёлый. Спасибо за помощь!",
        "consent": True, "consent_version": CONSENT_CURRENT["review"],
        "consent_publish": True, "consent_publish_version": CONSENT_CURRENT["distribution"],
        "page": {"path": "/otzyvy/?utm_source=vk", "title": "Отзывы"},
        "visitor_id": str(uuid.uuid4()), "session_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()), "hp_note": "", "elapsed_ms": 40_000,
    }
    p.update(over)
    return p


@pytest.fixture
def no_delivery(monkeypatch):
    """Keep notifications in the outbox (no network): the route schedules _deliver_now after the response."""
    from app.api import public
    monkeypatch.setattr(public, "_deliver_now", lambda: None)


def _client(peer: str, **headers) -> TestClient:
    from app.main import app
    return TestClient(app, client=(peer, 1), headers={"Origin": ORIGIN, **headers})


# ================================================================ POST /events

def test_send_beacon_text_plain_stores_events_visitor_and_session(client, db):
    vid, sid = uuid.uuid4(), uuid.uuid4()
    now = dt.datetime.now(UTC)
    body = beacon(vid, sid, events=[
        {"type": "page_view", "path": "/maltipu/", "ts": _ms(now), "data": {"title": "Мальтипу"}},
        {"type": "contact_click", "path": "/maltipu/", "ts": _ms(now), "data": {"channel": "telegram", "place": "hdr"}},
    ])
    r = send_beacon(client, body, **{"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                                                   "AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"})
    assert r.status_code == 202
    assert r.json() == {"accepted": 2, "dropped": 0}

    rows = events_rows(db, vid)
    assert [x["type"] for x in rows] == ["page_view", "contact_click"]
    assert all(str(x["session_id"]) == str(sid) for x in rows)

    v = db.execute(text("SELECT first_landing, first_referrer_host, first_source, first_medium FROM visitors "
                        "WHERE id = :v"), {"v": str(vid)}).one()
    assert tuple(v) == ("/maltipu/", "yandex.ru", "yandex", "organic")
    s = db.execute(text("SELECT visitor_id, landing_path, referrer_host, device, events_count FROM sessions "
                        "WHERE id = :s"), {"s": str(sid)}).one()
    assert (str(s.visitor_id), s.landing_path, s.referrer_host, s.device, s.events_count) == \
        (str(vid), "/maltipu/", "yandex.ru", "mobile", 2)

    # the fetch() fallback may come as application/json: same result
    r = client.post(EVENTS, json=beacon(vid, sid))
    assert r.status_code == 202 and r.json() == {"accepted": 1, "dropped": 0}
    assert len(events_rows(db, vid)) == 3


def test_no_ip_or_user_agent_is_kept_for_anonymous_activity(client, db):
    """152-ФЗ minimisation: visitors / sessions / site_events have no column that could hold an IP or a user agent."""
    send_beacon(client, beacon(), **{"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/120"})
    cols = db.execute(text("SELECT table_name, column_name FROM information_schema.columns "
                           "WHERE table_name IN ('visitors', 'sessions', 'site_events')")).all()
    assert cols, "tables not found"
    assert not [c for c in cols if c.column_name in ("ip", "user_agent", "ua", "ip_address")]
    dumped = json.dumps([dict(r) for r in db.execute(text("SELECT * FROM sessions")).mappings()], default=str)
    assert "203.0.113.10" not in dumped and "Chrome/120" not in dumped


def test_first_touch_is_never_overwritten(client, db):
    vid = uuid.uuid4()
    first = beacon(vid, uuid.uuid4(), landing="/maltipu/", referrer="https://www.google.com/",
                   utm={"utm_source": "yandex", "utm_medium": "cpc", "utm_campaign": "malti"}, ym_uid="111")
    assert send_beacon(client, first).json()["accepted"] == 1
    before = db.execute(text("SELECT * FROM visitors WHERE id = :v"), {"v": str(vid)}).mappings().one()

    # a later visit from VK, with explicit first_* that disagree (another tab, a cleared sessionStorage …)
    later = beacon(vid, uuid.uuid4(), landing="/border-kolli/", referrer="https://vk.com/",
                   utm={"utm_source": "vk", "utm_medium": "social"}, ym_uid="222",
                   first_landing="/toj-pudel/", first_referrer="https://mail.ru/", first_utm={"utm_source": "mail"})
    assert send_beacon(client, later).json()["accepted"] == 1
    after = db.execute(text("SELECT * FROM visitors WHERE id = :v"), {"v": str(vid)}).mappings().one()

    for k in ("first_seen_at", "first_landing", "first_referrer_host", "first_utm", "first_source", "first_medium",
              "ym_uid"):
        assert after[k] == before[k], k
    assert before["first_landing"] == "/maltipu/" and before["first_source"] == "yandex"
    assert before["first_utm"] == {"source": "yandex", "medium": "cpc", "campaign": "malti"}
    assert after["last_seen_at"] >= before["last_seen_at"]
    assert count(db, "visitors") == 1 and count(db, "sessions") == 2


def test_session_counts_events_across_beacons_without_rewriting_landing(client, db):
    vid, sid = uuid.uuid4(), uuid.uuid4()
    ev = {"type": "page_view", "path": "/maltipu/"}
    send_beacon(client, beacon(vid, sid, events=[ev] * 3, landing="/maltipu/"))
    send_beacon(client, beacon(vid, sid, events=[ev] * 2, landing="/toj-pudel/", referrer="https://vk.com/"))
    s = db.execute(text("SELECT landing_path, referrer_host, events_count FROM sessions WHERE id = :s"),
                   {"s": str(sid)}).one()
    assert tuple(s) == ("/maltipu/", "yandex.ru", 5)


def test_unknown_event_types_are_dropped(client, db):
    evs = [{"type": "page_view", "path": "/"}, {"type": "purchase", "path": "/"}, {"type": "PAGE_VIEW"},
           {"path": "/"}, {"type": "drop table", "path": "/"}, "not an object", 42]
    r = send_beacon(client, beacon(events=evs))
    assert r.status_code == 202
    assert r.json()["accepted"] == 1 and r.json()["dropped"] == 4
    assert [x["type"] for x in events_rows(db)] == ["page_view"]


def test_batch_is_capped_at_max_events(client, db, settings):
    assert settings.max_events_per_batch == 20
    evs = [{"type": "page_view", "path": f"/maltipu/{i}/"} for i in range(30)]
    r = send_beacon(client, beacon(events=evs))
    assert r.status_code == 202 and r.json() == {"accepted": 20, "dropped": 10}
    assert [x["path"] for x in events_rows(db)] == [f"/maltipu/{i}/" for i in range(20)]


def test_bot_user_agents_are_dropped(client, db):
    for ua in ("Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
               "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36 "
               "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
               "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 HeadlessChrome/120.0.0.0 Safari/537.36",
               "Mozilla/5.0 (Linux; Android 11) Chrome-Lighthouse"):
        r = send_beacon(client, beacon(), **{"User-Agent": ua})
        assert r.status_code == 202 and r.json() == NOTHING, ua
    assert count(db, "visitors") == count(db, "sessions") == count(db, "site_events") == 0


def test_cubot_phone_is_a_person_not_a_bot(client, db):
    ua = ("Mozilla/5.0 (Linux; Android 12; CUBOT KINGKONG 7) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/118.0.0.0 Mobile Safari/537.36")
    assert send_beacon(client, beacon(), **{"User-Agent": ua}).json()["accepted"] == 1


def test_foreign_origin_is_dropped_but_same_site_and_no_origin_pass(client, db):
    r = send_beacon(client, beacon(), Origin="https://evil.example")
    assert r.status_code == 202 and r.json() == NOTHING
    assert count(db, "site_events") == count(db, "visitors") == 0

    assert send_beacon(client, beacon(), Origin="https://www.xn--b1adduihee9g.xn--p1ai").json()["accepted"] == 1
    assert send_beacon(client, beacon(), Origin="null").json()["accepted"] == 1  # privacy-sandboxed frame
    assert count(db, "site_events") == 2


def test_event_data_keys_are_allowlisted_per_type(client, db):
    """A beacon must not smuggle personal data (phone, name) into analytics: only known keys per type survive."""
    pii = {"phone": "+79991234567", "name": "Анна", "email": "a@b.ru", "href": "tel:+79991234567"}
    evs = [
        {"type": "page_view", "path": "/maltipu/", "data": {"title": "Мальтипу", "kind": "price", **pii}},
        {"type": "form_open", "path": "/maltipu/", "data": {
            "kind": "price", "form": "modal", "puppy": "maltipu-f1-krem-2026-08", "colour": "kremovyj",
            "breed": "maltipu", "channel": "telegram", **pii}},
        {"type": "contact_click", "path": "/", "data": {"channel": "whatsapp", "place": "footer", "title": "x", **pii}},
        {"type": "quiz_complete", "path": "/podbor/", "data": {
            "winner": "maltipu", "second": "toj-pudel", "answers": {"home": "flat", "kids": 2, "bad": {"x": 1}},
            **pii}},
    ]
    assert send_beacon(client, beacon(events=evs)).json()["accepted"] == 4
    got = [x["data"] for x in events_rows(db)]
    assert got == [
        {"title": "Мальтипу"},
        {"kind": "price", "form": "modal", "puppy": "maltipu-f1-krem-2026-08", "colour": "kremovyj",
         "breed": "maltipu"},
        {"channel": "whatsapp", "place": "footer"},
        {"winner": "maltipu", "second": "toj-pudel", "answers": {"home": "flat", "kids": "2"}},
    ]
    assert "79991234567" not in json.dumps(got)


def test_event_values_are_cleaned_and_capped(client, db):
    evs = [{"type": "page_view", "path": "/", "data": {"title": "Мальти\u202eпу\x00 \u200b " + "я" * 500}},
           {"type": "page_view", "path": "/", "data": {"title": {"nested": "object"}}},
           {"type": "page_view", "path": "/", "data": ["not", "a", "dict"]}]
    assert send_beacon(client, beacon(events=evs)).json()["accepted"] == 3
    d = [x["data"] for x in events_rows(db)]
    assert d[0]["title"].startswith("Мальтипу ") and len(d[0]["title"]) == 120
    assert "\u202e" not in d[0]["title"] and "\x00" not in d[0]["title"]
    assert d[1] == {} and d[2] == {}


def test_occurred_at_is_clamped_to_a_day_back_and_five_minutes_ahead(client, db):
    now = dt.datetime.now(UTC)
    evs = [
        {"type": "page_view", "path": "/a/", "ts": _ms(now - dt.timedelta(days=3))},       # stale outbox
        {"type": "page_view", "path": "/b/", "ts": _ms(now + dt.timedelta(hours=2))},      # clock ahead
        {"type": "page_view", "path": "/c/", "ts": _ms(now - dt.timedelta(hours=1))},      # honest
        {"type": "page_view", "path": "/d/"},                                              # no ts
        {"type": "page_view", "path": "/e/", "ts": "yesterday"},
        {"type": "page_view", "path": "/f/", "ts": 10 ** 18},                              # year 31 million
        {"type": "page_view", "path": "/g/", "ts": -5},
    ]
    assert send_beacon(client, beacon(events=evs)).json() == {"accepted": 7, "dropped": 0}
    rows = {x["path"]: x for x in events_rows(db)}
    srv = rows["/d/"]["received_at"]

    def near(a, b, sec=10):
        return abs((a - b).total_seconds()) < sec

    assert near(rows["/a/"]["occurred_at"], srv - dt.timedelta(days=1))
    assert near(rows["/b/"]["occurred_at"], srv + dt.timedelta(minutes=5))
    assert near(rows["/c/"]["occurred_at"], now - dt.timedelta(hours=1), 1)
    for p in ("/d/", "/e/", "/f/", "/g/"):
        assert near(rows[p]["occurred_at"], srv), p


def test_breed_and_puppy_are_derived_from_the_path(client, db):
    """This is what puts anonymous activity into the per-breed picture next to the per-breed request bases."""
    cases = [
        ("/maltipu/", "maltipu", None),
        ("/puppyhouse/francuzskij-buldog/palevyj/?utm_source=x#top", "buldog", None),  # GitHub Pages preview
        ("/toj-pudel/", "pudel", None),
        ("/border-kolli/", "kolli", None),
        ("/shchenki/toj-pudel-ryzhij-2026-08-knopka/", "pudel", "toj-pudel-ryzhij-2026-08-knopka"),
        ("/shchenki/maltipu-f1-krem-2026-08/", "maltipu", "maltipu-f1-krem-2026-08"),
        ("/shchenki/no-such-puppy/", None, "no-such-puppy"),
        ("/shchenki/", None, None),
        ("/otzyvy/", None, None),
        ("/", None, None),
    ]
    r = send_beacon(client, beacon(events=[{"type": "page_view", "path": p} for p, _, _ in cases]))
    assert r.json()["accepted"] == len(cases)
    got = [(x["breed_key"], x["puppy_slug"]) for x in events_rows(db)]
    assert got == [(b, s) for _, b, s in cases]


def test_form_open_puppy_from_data_wins_and_breed_still_comes_from_path(client, db):
    evs = [{"type": "form_open", "path": "/border-kolli/",
            "data": {"kind": "puppy", "puppy": "border-kolli-some-puppy"}},
           {"type": "form_open", "path": "/maltipu/", "data": {"kind": "puppy", "puppy": "../../etc/passwd"}}]
    send_beacon(client, beacon(events=evs))
    rows = events_rows(db)
    assert (rows[0]["breed_key"], rows[0]["puppy_slug"]) == ("kolli", "border-kolli-some-puppy")
    assert (rows[1]["breed_key"], rows[1]["puppy_slug"]) == ("maltipu", None)


def test_paths_lose_query_strings_and_referrers_keep_only_the_host(client, db):
    """Query strings and referrer URLs may carry a phone or a search phrase: only path / host are stored."""
    vid, sid = uuid.uuid4(), uuid.uuid4()
    body = beacon(vid, sid, landing="/puppyhouse/maltipu/?phone=79991234567&name=Анна",
                  referrer="https://www.google.com/search?q=анна+79991234567",
                  events=[{"type": "page_view", "path": "/maltipu/index.html?phone=79991234567#form"}])
    send_beacon(client, body)
    (ev,) = events_rows(db, vid)
    assert ev["path"] == "/maltipu/"
    s = db.execute(text("SELECT landing_path, referrer_host FROM sessions WHERE id = :s"), {"s": str(sid)}).one()
    assert tuple(s) == ("/maltipu/", "www.google.com")
    v = db.execute(text("SELECT first_landing, first_referrer_host FROM visitors WHERE id = :v"), {"v": str(vid)}).one()
    assert tuple(v) == ("/maltipu/", "www.google.com")
    everything = json.dumps([dict(r) for t in ("visitors", "sessions", "site_events")
                             for r in db.execute(text(f"SELECT * FROM {t}")).mappings()], default=str)
    assert "79991234567" not in everything

    # navigation inside our own site is not a traffic source
    sid2 = uuid.uuid4()
    send_beacon(client, beacon(session_id=sid2, referrer="https://xn--b1adduihee9g.xn--p1ai/maltipu/"))
    s = db.execute(text("SELECT referrer_host, source, medium FROM sessions WHERE id = :s"), {"s": str(sid2)}).one()
    assert tuple(s) == (None, "(direct)", "(none)")


def test_session_id_of_another_visitor_does_not_capture_events(client, db):
    alice, bob, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    send_beacon(client, beacon(alice, sid))
    r = send_beacon(client, beacon(bob, sid, events=[{"type": "page_view", "path": "/x/"},
                                                     {"type": "page_view", "path": "/y/"}]))
    assert r.json() == {"accepted": 2, "dropped": 0}  # Bob's activity is kept, just not in Alice's visit

    s = db.execute(text("SELECT visitor_id, events_count FROM sessions WHERE id = :s"), {"s": str(sid)}).one()
    assert (str(s.visitor_id), s.events_count) == (str(alice), 1)
    assert [x["session_id"] for x in events_rows(db, bob)] == [None, None]
    assert [str(x["session_id"]) for x in events_rows(db, alice)] == [str(sid)]


def test_malformed_bodies_get_202_and_store_nothing(client, db):
    for raw in ("{not json", "", "[1, 2, 3]", "null", '"string"', "\xff\xfe".encode("latin-1"),
                json.dumps({"visitor_id": "not-a-uuid", "events": [{"type": "page_view"}]}),
                json.dumps({"events": [{"type": "page_view", "path": "/"}]}),  # no visitor id
                json.dumps({"visitor_id": str(uuid.uuid4()), "events": "page_view"})):
        r = send_beacon(client, raw)
        assert r.status_code == 202, raw
        assert r.json()["accepted"] == 0, raw
    assert count(db, "visitors") == count(db, "site_events") == 0


def test_too_large_beacon_gets_202_and_stores_nothing(client, db, settings):
    evs = [{"type": "page_view", "path": "/", "data": {"title": "я" * 250}}] * 50
    raw = json.dumps(beacon(events=evs), ensure_ascii=False)
    assert settings.max_body_bytes < len(raw.encode()) < 4 * settings.max_body_bytes
    r = send_beacon(client, raw)
    assert r.status_code == 202 and r.json() == NOTHING
    assert count(db, "site_events") == 0


def test_infinite_timestamp_still_gets_202(client, db):
    raw = ('{"visitor_id": "%s", "events": [{"type": "page_view", "path": "/", "ts": Infinity}]}' % uuid.uuid4())
    r = send_beacon(client, raw)
    assert r.status_code == 202


def test_one_poisoned_event_does_not_lose_the_rest_of_the_batch(client, db):
    evs = [{"type": "page_view", "path": "/maltipu/"},
           {"type": "quiz_complete", "path": "/podbor/", "data": {"winner": "maltipu", "answers": {"q\u0000": "a"}}}]
    r = send_beacon(client, beacon(events=evs))
    assert r.status_code == 202
    assert count(db, "site_events") >= 1


# ================================================================ POST /reviews

def test_review_is_stored_pending_with_display_name_and_two_consents(client, db):
    p = review_payload(name="  анна   королёва ", city="Новосибирск\u202e")
    r = client.post(REVIEWS, json=p)
    assert r.status_code == 201, r.text
    assert r.json() == {"status": "pending"}

    rv = db.execute(text("SELECT r.*, host(r.ip) AS ip_text, b.key AS breed_key FROM reviews r "
                         "LEFT JOIN breeds b ON b.id = r.breed_id")).mappings().one()
    assert rv["status"] == "pending" and rv["spam_reason"] is None
    assert rv["name"] == "анна королёва" and rv["display_name"] == "Анна К."
    assert rv["city"] == "Новосибирск" and rv["breed_key"] == "maltipu" and rv["rating"] == 5
    assert rv["page_path"] == "/otzyvy/"
    assert rv["ip_text"] == "203.0.113.10" and str(rv["visitor_id"]) == p["visitor_id"]
    assert str(rv["idempotency_key"]) == p["idempotency_key"]

    cons = db.execute(text("SELECT c.version, v.kind, c.review_id, c.contact_id, c.page_path, host(c.ip) AS ip "
                           "FROM consents c JOIN consent_versions v ON v.version = c.version ORDER BY v.kind")).all()
    assert [(c.kind, c.version) for c in cons] == [("distribution", CONSENT_CURRENT["distribution"]),
                                                    ("review", CONSENT_CURRENT["review"])]
    assert all(c.review_id == rv["id"] and c.contact_id is None and c.page_path == "/otzyvy/"
               and c.ip == "203.0.113.10" for c in cons)


def test_review_needs_both_consents(client, db):
    """ст. 10.1 152-ФЗ: publishing a review needs its own consent, on top of the processing one."""
    no_keys = review_payload()
    del no_keys["consent"], no_keys["consent_publish"]
    cases = [
        (review_payload(consent=False), {"consent"}),
        (review_payload(consent_publish=False), {"consent_publish"}),
        (review_payload(consent=False, consent_publish=False), {"consent", "consent_publish"}),
        (review_payload(consent=None, consent_publish=None), {"consent", "consent_publish"}),
        (no_keys, {"consent", "consent_publish"}),
    ]
    for body, fields in cases:
        r = client.post(REVIEWS, json=body)
        assert r.status_code == 422, body
        err = r.json()["error"]
        assert err["code"] == "validation" and set(err["fields"]) == fields
    assert count(db, "reviews") == count(db, "consents") == 0


def test_display_name_never_publishes_the_surname():
    from app.services.reviews import display_name
    for name, shown in [("Анна Королёва", "Анна К."), ("анна", "Анна"), ("  мария   иванова-петрова  ", "Мария И."),
                        ("Ольга 2", "Ольга"), ("И. Петров", "И П."), ("", "Покупатель")]:
        assert display_name(name) == shown, name


def test_review_text_and_rating_are_validated(client, db):
    for bad in (0, 6, None, "пять"):
        r = client.post(REVIEWS, json=review_payload(rating=bad))
        assert r.status_code == 422 and set(r.json()["error"]["fields"]) == {"rating"}, bad

    short = client.post(REVIEWS, json=review_payload(text="Супер щен"))          # 9 characters
    padded = client.post(REVIEWS, json=review_payload(text="     Супер      "))  # 5 after trimming
    too_long = client.post(REVIEWS, json=review_payload(text="я" * 4001))
    for r in (short, padded, too_long):
        assert r.status_code == 422 and set(r.json()["error"]["fields"]) == {"text"}, r.text
    assert count(db, "reviews") == 0

    assert client.post(REVIEWS, json=review_payload(text="Супер щенок")).status_code == 201  # 11 characters
    assert client.post(REVIEWS, json=review_payload(text="я" * 4000)).status_code == 201
    lens = db.execute(text("SELECT char_length(text) FROM reviews ORDER BY id")).scalars().all()
    assert lens == [11, 4000]


def test_review_text_of_invisible_characters_is_rejected(client, db):
    r = client.post(REVIEWS, json=review_payload(text="\u200b" * 12))
    assert r.status_code == 422


def test_review_retry_with_same_key_is_idempotent(client, db):
    p = review_payload()
    first = client.post(REVIEWS, json=p)
    again = client.post(REVIEWS, json=p)
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json() == {"status": "pending"}
    assert count(db, "reviews") == 1 and count(db, "consents") == 2

    other = client.post(REVIEWS, json={**p, "text": "Совсем другой текст отзыва, но тот же ключ"})
    assert other.status_code == 409 and other.json()["error"]["code"] == "idempotency_conflict"
    assert count(db, "reviews") == 1 and count(db, "consents") == 2


def test_reviews_over_the_ip_limit_are_kept_but_flagged_and_not_notified(client, db, settings, no_delivery):
    settings.webhook_url = "https://admin.example/hook"
    for i in range(settings.reviews_per_ip_day + 1):
        r = client.post(REVIEWS, json=review_payload(text=f"Отзыв номер {i}: всё отлично, спасибо!"))
        assert r.status_code == 201
    rows = db.execute(text("SELECT r.spam_reason, r.status, count(o.id) AS notes FROM reviews r "
                           "LEFT JOIN outbox o ON o.review_id = r.id GROUP BY r.id ORDER BY r.id")).all()
    assert [tuple(x) for x in rows] == [(None, "pending", 1)] * 3 + [("rate_limited", "pending", 0)]
    assert count(db, "consents") == 8  # every review keeps its consent proof

    with _client("198.51.100.99") as other:  # another person is not affected
        assert other.post(REVIEWS, json=review_payload()).status_code == 201
    assert db.execute(text("SELECT spam_reason FROM reviews WHERE host(ip) = '198.51.100.99'")).scalar() is None


def test_too_fast_review_is_flagged_not_dropped(client, db):
    assert client.post(REVIEWS, json=review_payload(elapsed_ms=300)).status_code == 201
    assert db.execute(text("SELECT spam_reason FROM reviews")).scalar() == "too_fast"


def test_review_honeypot_pretends_success_and_stores_nothing(client, db):
    r = client.post(REVIEWS, json=review_payload(hp_note="http://spam.example"))
    assert r.status_code == 201 and r.json() == {"status": "pending"}
    assert count(db, "reviews") == count(db, "consents") == 0


def test_review_unknown_or_wrong_kind_consent_version_falls_back_to_current(client, db):
    p = review_payload(consent_version=CONSENT_CURRENT["distribution"],      # a distribution doc sent as processing
                       consent_publish_version="distribution-1999-01-01")  # never published
    assert client.post(REVIEWS, json=p).status_code == 201
    got = db.execute(text("SELECT v.kind, c.version FROM consents c JOIN consent_versions v USING (version) "
                          "ORDER BY v.kind")).all()
    assert [tuple(x) for x in got] == [("distribution", CONSENT_CURRENT["distribution"]),
                                       ("review", CONSENT_CURRENT["review"])]


def test_review_requires_json_and_our_origin(client, db):
    raw = json.dumps(review_payload())
    r = client.post(REVIEWS, content=raw, headers={"Content-Type": "text/plain"})
    assert r.status_code == 415
    r = client.post(REVIEWS, json=review_payload(), headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_origin"
    assert count(db, "reviews") == 0


def test_review_from_a_browser_with_a_long_user_agent_is_not_lost(client, db):
    ua = "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36 " + \
         " ".join(f"InAppToken{i}/1.0" for i in range(30))
    assert len(ua) > 400
    r = client.post(REVIEWS, json=review_payload(), headers={"User-Agent": ua})
    assert r.status_code == 201
    assert count(db, "reviews") == 1 and count(db, "consents") == 2


def test_lead_from_a_browser_with_a_long_user_agent_is_not_lost(client, db):
    ua = "Mozilla/5.0 (Linux; Android 14) Chrome/126 Mobile " + " ".join(f"InAppToken{i}/1.0" for i in range(30))
    r = client.post("/api/v1/leads", json=lead_payload(), headers={"User-Agent": ua})
    assert r.status_code == 201
    assert count(db, "leads") == 1


def test_lead_with_a_nul_in_utm_is_not_lost(client, db):
    r = client.post("/api/v1/leads", json=lead_payload(utm={"utm_source": "ya\u0000ndex", "utm_medium": "cpc"}))
    assert r.status_code == 201
    assert count(db, "leads") == 1


# ================================================================ client IP behind nginx

def test_x_real_ip_is_used_when_the_peer_is_a_trusted_proxy(db, settings):
    settings.trusted_proxies = ["127.0.0.1/32", "172.16.0.0/12"]
    with _client("172.18.0.1", **{"X-Real-IP": "198.51.100.7"}) as c:
        assert c.post("/api/v1/leads", json=lead_payload()).status_code == 201
        assert c.post(REVIEWS, json=review_payload()).status_code == 201
    assert db.execute(text("SELECT host(ip) FROM leads")).scalar() == "198.51.100.7"
    assert db.execute(text("SELECT host(ip) FROM reviews")).scalar() == "198.51.100.7"
    assert set(db.execute(text("SELECT host(ip) FROM consents")).scalars()) == {"198.51.100.7"}


def test_x_real_ip_from_an_untrusted_peer_is_ignored(db, settings):
    settings.trusted_proxies = ["127.0.0.1/32", "172.16.0.0/12"]
    with _client("198.51.100.200", **{"X-Real-IP": "10.9.8.7"}) as c:
        assert c.post("/api/v1/leads", json=lead_payload()).status_code == 201
    assert db.execute(text("SELECT host(ip) FROM leads")).scalar() == "198.51.100.200"


def test_default_settings_do_not_trust_a_docker_peer(client, db, settings):
    """Out of the box only loopback is trusted: a spoofed header cannot dodge the per-IP review limit."""
    for i in range(settings.reviews_per_ip_day + 1):
        r = client.post(REVIEWS, json=review_payload(), headers={"X-Real-IP": f"198.51.100.{i + 1}"})
        assert r.status_code == 201
    ips = db.execute(text("SELECT DISTINCT host(ip) FROM reviews")).scalars().all()
    assert ips == ["203.0.113.10"]
    assert db.execute(text("SELECT spam_reason FROM reviews ORDER BY id DESC LIMIT 1")).scalar() == "rate_limited"


def test_review_limit_groups_ipv6_by_64(db, settings):
    for i in range(settings.reviews_per_ip_day + 1):
        with _client(f"2001:db8:1:2::{i + 1:x}") as c:
            assert c.post(REVIEWS, json=review_payload()).status_code == 201
    assert db.execute(text("SELECT spam_reason FROM reviews ORDER BY id DESC LIMIT 1")).scalar() == "rate_limited"


# ================================================================ services.security.rate_key

def test_rate_key_groups_ipv6_by_64_and_keeps_ipv4():
    from app.services.security import rate_key
    a = rate_key("2001:db8:1:2:aaaa:bbbb:cccc:1")
    assert a == "2001:db8:1:2::/64" == rate_key("2001:db8:1:2::ffff")
    assert rate_key("2001:db8:1:3::1") != a
    assert rate_key("198.51.100.7") == "198.51.100.7" != rate_key("198.51.100.8")
    assert rate_key(None) is None and rate_key("") is None


def test_rate_key_does_not_merge_ipv4_mapped_clients():
    from app.services.security import rate_key
    assert rate_key("::ffff:198.51.100.7") != rate_key("::ffff:203.0.113.10")


# ================================================================ services.sanitize

def test_sanitize_path():
    from app.services.sanitize import path
    for raw, want in [
        ("/puppyhouse/maltipu/?utm_source=x#top", "/maltipu/"),
        ("/puppyhouse", "/"),
        ("/puppyhouse-old/maltipu/", "/puppyhouse-old/maltipu/"),          # only a whole segment is a base path
        ("maltipu/index.html", "/maltipu/"),
        ("https://evil.example/maltipu/?phone=79991234567", "/maltipu/"),
        ("/mal\x00ti\u202epu/", "/maltipu/"),
        ("", None),
        (None, None),
    ]:
        assert path(raw, ["/puppyhouse"]) == want, raw
    assert len(path("/" + "a" * 1000, [])) == 300


def test_sanitize_host_keeps_only_the_host():
    from app.services.sanitize import host
    assert host("https://www.google.com/search?q=анна+79991234567") == "www.google.com"
    assert host("https://User:Pass@Yandex.RU:443/x") == "yandex.ru"
    assert host("not a url") is None and host("") is None and host(None) is None
    assert host("http://[::1") is None  # unparsable, not a crash


def test_sanitize_clean_strips_control_and_bidi_characters():
    from app.services.sanitize import clean
    assert clean("  Анна\u202e\u2066 \x00Королёва\u200b\x7f  ", 100) == "Анна Королёва"
    assert clean("строка\nвторая\r\nтретья", 100) == "строка вторая третья"
    assert clean("абзац 1\r\n\r\n\r\n\r\nабзац\t\t2  ", 100, multiline=True) == "абзац 1\n\nабзац 2"
    assert clean("я" * 50, 10) == "я" * 10
    assert clean("   ", 10) is None and clean("\u200b\u200f", 10) is None and clean(None, 10) is None
