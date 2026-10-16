"""POST /api/v1/leads — the one public write path every form of the site uses.

What matters for a kennel taking requests: every real request is stored (junk in optional fields never costs one),
it lands in the right per-breed base (leads_<key> views) and in the big one (leads_all), retries and parallel
clicks never double it, repeat requests of one person are grouped, and nothing beyond what 152-ФЗ allows is kept
(no query strings, only the referrer host, nothing at all from a bot that filled the honeypot)."""
from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from conftest import ORIGIN, lead_payload

URL = "/api/v1/leads"
PHONE = "+79991234567"
CURRENT_CONSENT = "processing-2026-10-16"
BULDOG_PUPPY = "francuzskij-buldog-palevyj-2026-07"   # «Бруно», a French bulldog in puppies.json
BREED_VIEWS = ("leads_maltipu", "leads_buldog", "leads_pudel", "leads_kolli", "leads_general")
FIELD_MESSAGES = {
    "name": "Напишите, как к вам обращаться",
    "phone": "Проверьте номер: после +7 нужно 10 цифр",
    "contact": "Выберите, куда вам написать",
    "consent": "Без согласия на обработку данных мы не сможем отправить заявку",
}


# ---------------------------------------------------------------- helpers
def post(client, payload, **headers):
    """Send exactly these bytes (allow_nan: a bot can send Infinity; httpx's json= refuses to)."""
    body = payload if isinstance(payload, (bytes, str)) else json.dumps(payload, ensure_ascii=False)
    return client.post(URL, content=body.encode() if isinstance(body, str) else body,
                       headers={"Content-Type": "application/json", **headers})


def count(db, table, where="TRUE", **kw) -> int:
    return db.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"), kw).scalar()


def leads(db, where="TRUE", **kw) -> list[dict]:
    return [dict(r) for r in db.execute(text(
        f"SELECT l.*, b.key AS breed_key FROM leads l LEFT JOIN breeds b ON b.id = l.breed_id WHERE {where} "
        "ORDER BY l.id"), kw).mappings()]


def lead_of(db, response) -> dict:
    rows = leads(db, "l.public_id = :p", p=response.json()["id"])
    assert len(rows) == 1, response.text
    return rows[0]


def history(db, lead_id) -> list[tuple]:
    return db.execute(text("SELECT action, new_value, comment, actor_label FROM lead_history WHERE lead_id = :i "
                           "ORDER BY id"), {"i": lead_id}).all()


def views_with(db, lead_id) -> set[str]:
    return {v for v in BREED_VIEWS if count(db, v, "lead_id = :i", i=lead_id)}


def nothing_stored(db) -> bool:
    return all(count(db, t) == 0 for t in ("leads", "contacts", "consents", "lead_history", "outbox", "visitors",
                                           "sessions"))


@pytest.fixture
def safe_client():
    """Like `client`, but a server error comes back as a 500 response instead of an exception in the test."""
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, client=("203.0.113.10", 50000), headers={"Origin": ORIGIN},
                    raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def webhook_on(settings, monkeypatch):
    """A notification channel is configured, so the outbox fills; the immediate delivery (network) is stubbed."""
    from app.api import public
    settings.webhook_url = "https://admin.example/hooks/leads"
    settings.webhook_secret = "s" * 32
    calls: list[int] = []
    monkeypatch.setattr(public, "_deliver_now", lambda: calls.append(1))
    return calls


@pytest.fixture
def older_processing_version(db, monkeypatch):
    """A second, older processing consent the site once showed (a cached page may still send it)."""
    from app.models import ConsentVersion
    from app.services import consent
    ver = "processing-2026-01-01"
    db.add(ConsentVersion(version=ver, kind="processing", title="Согласие (старая редакция)",
                          url="/soglasie-2026-01-01/", checkbox_text="Согласен", body="Текст", text_sha256="0" * 64))
    db.commit()
    real = consent.load()
    doc = {"version": ver, "kind": "processing", "title": "Согласие (старая редакция)", "url": "/soglasie-2026-01-01/",
           "checkbox": "Согласен", "body": ["Текст"]}
    patched = {"current": real["current"], "versions": {**real["versions"], ver: doc}}
    monkeypatch.setattr(consent, "load", lambda path=None: patched)
    yield ver
    db.rollback()
    db.execute(text("TRUNCATE leads, consents RESTART IDENTITY CASCADE"))
    db.execute(text("DELETE FROM consent_versions WHERE version = :v"), {"v": ver})
    db.commit()


# ---------------------------------------------------------------- happy path: one request, every table, its base
def test_request_is_stored_with_contact_consent_history_and_breed_view(client, db):
    p = lead_payload(kind="puppy", puppy="maltipu-f1-krem-2026-08", note="Цена: Пломбир",
                     form_title="Узнать цену щенка", page={"path": "/shchenki/maltipu-f1-krem-2026-08/",
                                                           "title": "Пломбир"})
    r = post(client, p, **{"User-Agent": "Mozilla/5.0 (iPhone)"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {"id", "status"} and body["status"] == "accepted"

    lead = lead_of(db, r)
    assert str(lead["public_id"]) == body["id"] != str(lead["id"])      # the admin number is not shown
    assert lead["status"] == "new" and lead["origin"] == "site_form" and lead["kind"] == "puppy"
    assert lead["breed_key"] == "maltipu" and lead["puppy_slug"] == "maltipu-f1-krem-2026-08"
    assert lead["puppy_id"] is not None and lead["puppy_name"] == "Пломбир"
    assert (lead["name"], lead["phone"], lead["channel"]) == ("Анна", PHONE, "telegram")
    assert lead["consent_version"] == CURRENT_CONSENT and lead["consent_at"] is not None
    assert str(lead["ip"]) == "203.0.113.10" and lead["user_agent"] == "Mozilla/5.0 (iPhone)"
    assert lead["flags"] == [] and lead["parent_id"] is None and lead["is_repeat"] is False
    assert str(lead["idempotency_key"]) == p["idempotency_key"]
    assert str(lead["visitor_id"]) == p["visitor_id"] and str(lead["session_id"]) == p["session_id"]
    assert (lead["note"], lead["form_title"]) == ("Цена: Пломбир", "Узнать цену щенка")

    contact = db.execute(text("SELECT id, phone, name, preferred_channel FROM contacts")).one()
    assert contact[1:] == (PHONE, "Анна", "telegram") and lead["contact_id"] == contact[0]

    consent = db.execute(text("SELECT version, contact_id, lead_id, page_path, host(ip) FROM consents")).one()
    assert consent == (CURRENT_CONSENT, contact[0], lead["id"], "/shchenki/maltipu-f1-krem-2026-08/",
                       "203.0.113.10")

    assert history(db, lead["id"]) == [("created", "new", None, "Сайт")]
    assert views_with(db, lead["id"]) == {"leads_maltipu"}
    assert count(db, "leads_all", "lead_id = :i", i=lead["id"]) == 1
    assert count(db, "visitors", "id = :v", v=p["visitor_id"]) == 1


def test_every_breed_has_its_own_base_and_all_meet_in_leads_all(client, db):
    cases = {"maltipu": "leads_maltipu", "francuzskij-buldog": "leads_buldog", "toj-pudel": "leads_pudel",
             "border-kolli": "leads_kolli", "undecided": "leads_general"}
    ids = {}
    for i, (breed, view) in enumerate(cases.items()):
        r = post(client, lead_payload(breed=breed, phone=f"+7999000000{i}"))
        assert r.status_code == 201, r.text
        ids[view] = lead_of(db, r)["id"]
    for view, lead_id in ids.items():
        assert db.execute(text(f"SELECT lead_id FROM {view}")).scalars().all() == [lead_id]
    assert count(db, "leads_all") == 5
    assert count(db, "contacts") == 5


def test_site_activity_is_not_linked_when_the_purpose_is_switched_off(client, db, settings):
    settings.link_site_activity = False   # consent text no longer names the purpose → no visitor link (152-ФЗ)
    r = post(client, lead_payload())
    assert r.status_code == 201
    lead = lead_of(db, r)
    assert lead["visitor_id"] is None and lead["session_id"] is None
    assert count(db, "visitors") == 0


# ---------------------------------------------------------------- idempotency
def test_same_key_and_payload_replays_200_without_second_row_history_or_notification(client, db, webhook_on):
    p = lead_payload()
    first = post(client, p)
    assert first.status_code == 201
    again = post(client, p)
    same_number_other_mask = post(client, {**p, "phone": "8 999 123-45-67", "elapsed_ms": 99_000})
    for r in (again, same_number_other_mask):
        assert r.status_code == 200, r.text
        assert r.json() == first.json()
    assert count(db, "leads") == 1 and count(db, "contacts") == 1 and count(db, "consents") == 1
    assert count(db, "lead_history") == 1
    assert count(db, "outbox") == 1 and len(webhook_on) == 1


def test_same_key_with_other_payload_is_409_and_keeps_the_first(client, db, webhook_on):
    p = lead_payload()
    assert post(client, p).status_code == 201
    r = post(client, {**p, "name": "Мария", "phone": "+7 (912) 000-00-00"})
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "idempotency_conflict" and any("а" <= ch <= "я" for ch in err["message"].lower())
    assert [(x["name"], x["phone"]) for x in leads(db)] == [("Анна", PHONE)]
    assert count(db, "contacts") == 1 and count(db, "outbox") == 1


def test_missing_or_garbage_key_gets_a_generated_one(client, db):
    p = lead_payload()
    del p["idempotency_key"]
    r1 = post(client, p)
    r2 = post(client, lead_payload(idempotency_key="not-a-uuid", breed="toj-pudel"))
    assert (r1.status_code, r2.status_code) == (201, 201)
    keys = [x["idempotency_key"] for x in leads(db)]
    assert len(keys) == 2 and all(isinstance(k, uuid.UUID) for k in keys) and keys[0] != keys[1]


# ---------------------------------------------------------------- never lose a request
def test_unknown_kind_becomes_other_with_raw_text(safe_client, db):
    r = post(safe_client, lead_payload(kind="Хочу щенка на день рождения"))
    assert r.status_code == 201, r.text
    lead = lead_of(db, r)
    assert lead["kind"] == "other" and lead["details"]["kind_raw"] == "Хочу щенка на день рождения"
    assert lead["status"] == "new"


@pytest.mark.parametrize("colour, slug, raw", [
    ("kremovyj", "kremovyj", None),
    ("кремовый", None, "кремовый"),
    ("Kremovyj", None, "Kremovyj"),
    ("a" * 41, None, "a" * 41),
])
def test_colour_slug_kept_text_kept_raw(safe_client, db, colour, slug, raw):
    r = post(safe_client, lead_payload(kind="colour", colour=colour))
    assert r.status_code == 201, r.text
    lead = lead_of(db, r)
    assert lead["colour"] == slug and lead["details"].get("colour_raw") == raw


@pytest.mark.parametrize("puppy", ["maltipu-f1-krem-2099-01", "Пломбир (кремовый)"])
def test_unknown_puppy_is_kept_as_text_and_breed_still_applies(safe_client, db, puppy):
    r = post(safe_client, lead_payload(kind="puppy", puppy=puppy, breed="maltipu"))
    assert r.status_code == 201, r.text
    lead = lead_of(db, r)
    assert lead["puppy_id"] is None and lead["puppy_slug"] == puppy and lead["breed_key"] == "maltipu"
    assert db.execute(text("SELECT puppy_slug FROM leads_maltipu")).scalar() == puppy


@pytest.mark.parametrize("breed, key", [
    ("Пока не решил(а)", None),
    ("Пока не решил(а)", None),          # the <select> sends a non-breaking space
    ("undecided", None),
    ("", None),
    ("   ", None),
    (["maltipu"], None),
    (12345, None),
    ("сенбернар", None),
    ("Французский бульдог", "buldog"),
    ("ФРАНЦУЗСКИЙ  БУЛЬДОГ", "buldog"),
    ("французский бульдог", "buldog"),
    ("  той-пудель ", "pudel"),
    ("Той-пудёль", "pudel"),                  # ё / е
    ("Мальтипу", "maltipu"),
    ("border-kolli", "kolli"),
    ("kolli", "kolli"),
])
def test_breed_input_resolves_to_breed_or_general(safe_client, db, breed, key):
    r = post(safe_client, lead_payload(breed=breed))
    assert r.status_code == 201, r.text
    lead = lead_of(db, r)
    assert lead["breed_key"] == key
    assert views_with(db, lead["id"]) == {f"leads_{key}" if key else "leads_general"}


def test_puppy_slug_wins_over_a_conflicting_breed(client, db):
    r = post(client, lead_payload(kind="puppy", breed="maltipu", puppy=BULDOG_PUPPY))
    assert r.status_code == 201, r.text
    lead = lead_of(db, r)
    assert lead["breed_key"] == "buldog" and lead["breed_input"] == "maltipu"
    assert lead["puppy_id"] is not None and lead["puppy_name"] == "Бруно"
    assert views_with(db, lead["id"]) == {"leads_buldog"}


def test_overlong_strings_are_trimmed_not_rejected(safe_client, db):
    r = post(safe_client, lead_payload(
        name="Анна" * 60, kind="k" * 200, colour="кремовый" * 20, breed="б" * 300, puppy="p" * 300,
        puppy_name="Пломбир" * 40, note="н" * 1000, form_title="ф" * 500,
        page={"path": "/maltipu/" + "x" * 600, "title": "т" * 500}))
    assert r.status_code == 201, r.text
    lead = lead_of(db, r)
    assert lead["name"] == ("Анна" * 60)[:100]
    assert db.execute(text("SELECT name FROM contacts")).scalar() == ("Анна" * 60)[:100]
    assert len(lead["details"]["kind_raw"]) == 40 and len(lead["details"]["colour_raw"]) == 60
    assert len(lead["breed_input"]) == 100 and len(lead["puppy_slug"]) == 120 and len(lead["puppy_name"]) == 100
    assert len(lead["note"]) == 300 and len(lead["form_title"]) == 200
    assert len(lead["page_title"]) == 200 and len(lead["page_path"]) == 300


def test_long_user_agent_does_not_lose_the_request(safe_client, db):
    ua = "Mozilla/5.0 (Linux; Android 14; in-app browser) " + "FBAV/450.0.0.38;" * 40   # ~700 chars
    r = post(safe_client, lead_payload(), **{"User-Agent": ua})
    assert r.status_code == 201, r.text
    assert len(lead_of(db, r)["user_agent"]) == 400


def test_garbage_tracking_fields_never_cost_a_request(safe_client, db):
    p = lead_payload(visitor_id="not-a-uuid", session_id=12345, idempotency_key={"a": 1}, utm="utm_source=x",
                     first_utm=[1, 2], page="/maltipu/", landing={"x": 1}, referrer=42, first_referrer=["x"],
                     first_landing=True, ym_uid={"id": 1}, quiz="maltipu", elapsed_ms="soon",
                     consent_version="x" * 500, puppy={"slug": "x"}, puppy_name=["Бруно"], note=None,
                     form_title=3.14, colour=False, extra_field_from_new_frontend={"any": "thing"})
    r = post(safe_client, p)
    assert r.status_code == 201, r.text
    lead = lead_of(db, r)
    assert lead["status"] == "new" and lead["visitor_id"] is None and lead["session_id"] is None
    assert lead["utm"] is None and (lead["source"], lead["medium"]) == ("(direct)", "(none)")
    assert lead["consent_version"] == CURRENT_CONSENT and "consent_version_fallback" in lead["flags"]


def test_broken_urls_in_tracking_fields_never_cost_a_request(safe_client, db):
    r = post(safe_client, lead_payload(page={"path": "http://[broken/maltipu/"}, landing="http://[::1",
                                       referrer="https://[not-ipv6/", first_referrer="http://[x",
                                       first_landing="::::"))
    assert r.status_code == 201, r.text
    lead = lead_of(db, r)
    assert lead["referrer_host"] is None and lead["page_path"] is None


def test_nul_in_utm_does_not_lose_the_request(safe_client, db):
    r = post(safe_client, lead_payload(utm={"utm_source": "ya\u0000ndex", "utm_campaign": "spring\u0000"}))
    assert r.status_code == 201, r.text
    assert "\x00" not in json.dumps(lead_of(db, r)["utm"])


def test_nul_in_referrer_does_not_lose_the_request(safe_client, db):
    r = post(safe_client, lead_payload(referrer="https://exa\u0000mple.com/page"))
    assert r.status_code == 201, r.text


def test_non_finite_elapsed_ms_does_not_crash(safe_client, db):
    body = json.dumps(lead_payload(), ensure_ascii=False).replace('"elapsed_ms": 20000', '"elapsed_ms": Infinity')
    assert "Infinity" in body
    r = post(safe_client, body)
    assert r.status_code == 201, r.text
    assert lead_of(db, r)["status"] == "new"


# ---------------------------------------------------------------- validation: only the four typed fields
def test_empty_body_lists_exactly_the_required_fields_in_russian(client, db):
    for body in ({}, [], "null"):
        r = post(client, body if isinstance(body, str) else json.dumps(body))
        assert r.status_code == 422, r.text
        err = r.json()["error"]
        assert err["code"] == "validation"
        assert err["fields"] == FIELD_MESSAGES
    assert nothing_stored(db)


def test_junk_optional_fields_never_show_up_as_validation_errors(client, db):
    r = post(client, lead_payload(phone="12345", kind=[1], breed={"x": 1}, utm=7, page=[], elapsed_ms=-5,
                                  visitor_id="zzz", colour="§§§", quiz=[1, 2]))
    assert r.status_code == 422
    assert r.json()["error"]["fields"] == {"phone": FIELD_MESSAGES["phone"]}
    assert nothing_stored(db)


@pytest.mark.parametrize("over, field", [
    ({"name": "   "}, "name"),
    ({"name": None}, "name"),
    ({"phone": "+7 (999) 123-45-6"}, "phone"),
    ({"phone": "+1 202 555 0100"}, "phone"),
    ({"phone": ""}, "phone"),
    ({"contact": "email"}, "contact"),
    ({"contact": None}, "contact"),
    ({"consent": False}, "consent"),
    ({"consent": None}, "consent"),
])
def test_each_required_field_fails_under_its_input_name(client, db, over, field):
    r = post(client, lead_payload(**over))
    assert r.status_code == 422, r.text
    assert r.json()["error"]["fields"] == {field: FIELD_MESSAGES[field]}
    assert nothing_stored(db)


def test_phone_masks_normalise_to_one_contact(client, db):
    for i, phone in enumerate(["+7 (999) 123-45-67", "8 999 123 45 67", "9991234567", "7(999)1234567"]):
        breed = ["maltipu", "francuzskij-buldog", "toj-pudel", "border-kolli"][i]
        assert post(client, lead_payload(phone=phone, breed=breed)).status_code == 201
    assert {x["phone"] for x in leads(db)} == {PHONE}
    assert count(db, "contacts") == 1


# ---------------------------------------------------------------- request gating
def test_non_json_content_type_is_415_and_nothing_stored(client, db):
    body = json.dumps(lead_payload(), ensure_ascii=False).encode()
    for ctype in ("text/plain", "application/x-www-form-urlencoded", ""):
        r = client.post(URL, content=body, headers={"Content-Type": ctype})
        assert r.status_code == 415, (ctype, r.text)
        assert r.json()["error"]["code"] == "unsupported_media_type"
    assert post(client, "{not json").status_code == 400
    assert nothing_stored(db)
    r = client.post(URL, content=body, headers={"Content-Type": "application/json; charset=utf-8"})
    assert r.status_code == 201


@pytest.mark.parametrize("origin", ["https://evil.example", "https://xn--b1adduihee9g.xn--p1ai.evil.example",
                                    "http://xn--b1adduihee9g.xn--p1ai"])
def test_foreign_origin_is_403_and_nothing_stored(client, db, origin):
    r = post(client, lead_payload(), Origin=origin)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden_origin"
    assert nothing_stored(db)


def test_missing_or_null_origin_is_accepted_and_flagged(client, db):
    r1 = post(client, lead_payload(breed="maltipu"), Origin="null")
    del client.headers["Origin"]
    r2 = post(client, lead_payload(breed="toj-pudel"))
    for r in (r1, r2):
        assert r.status_code == 201, r.text
        lead = lead_of(db, r)
        assert lead["flags"] == ["no_origin"] and lead["status"] == "new"


def test_honeypot_pretends_success_and_stores_nothing(client, db, webhook_on):
    r = post(client, lead_payload(hp_note="https://cheap-seo.example"))
    assert r.status_code == 201
    assert set(r.json()) == {"id", "status"} and uuid.UUID(r.json()["id"])
    assert nothing_stored(db) and webhook_on == []


def test_whitespace_in_honeypot_is_not_a_bot(client, db):
    r = post(client, lead_payload(hp_note="  "))
    assert r.status_code == 201
    assert count(db, "leads") == 1


def test_too_fast_is_flagged_but_still_a_new_notified_request(client, db, webhook_on):
    r = post(client, lead_payload(elapsed_ms=400))
    lead = lead_of(db, r)
    assert lead["flags"] == ["too_fast"] and lead["status"] == "new" and lead["spam_reason"] is None
    assert count(db, "outbox", "lead_id = :i", i=lead["id"]) == 1


# ---------------------------------------------------------------- repeat requests of one person
def test_repeat_with_same_phone_and_breed_joins_the_open_lead(client, db, webhook_on):
    first = lead_of(db, post(client, lead_payload(kind="price")))
    second = lead_of(db, post(client, lead_payload(kind="puppy", puppy="maltipu-f1-krem-2026-08",
                                                   phone="8 (999) 123-45-67")))
    third = lead_of(db, post(client, lead_payload(kind="video_call")))
    assert first["status"] == "new" and first["parent_id"] is None
    for child in (second, third):
        assert child["status"] == "duplicate" and child["parent_id"] == first["id"] and child["is_repeat"]
    repeats = [h for h in history(db, first["id"]) if h[0] == "repeat"]
    assert [h[1] for h in repeats] == [f"№{second['id']}", f"№{third['id']}"]
    assert "Пломбир" in repeats[0][2]
    events = db.execute(text("SELECT lead_id, event FROM outbox ORDER BY id")).all()
    assert events == [(first["id"], "lead.created"), (second["id"], "lead.repeat"), (third["id"], "lead.repeat")]
    assert count(db, "contacts") == 1


def test_repeat_without_breed_joins_the_open_general_lead(client, db):
    first = lead_of(db, post(client, lead_payload(breed="undecided")))
    second = lead_of(db, post(client, lead_payload(breed="Пока не решил(а)")))
    assert second["status"] == "duplicate" and second["parent_id"] == first["id"]


def test_same_person_other_breed_is_a_separate_new_lead(client, db):
    first = lead_of(db, post(client, lead_payload(breed="maltipu")))
    second = lead_of(db, post(client, lead_payload(breed="border-kolli")))
    third = lead_of(db, post(client, lead_payload(breed="undecided")))
    for lead in (second, third):
        assert lead["status"] == "new" and lead["parent_id"] is None and lead["is_repeat"] is True
    assert first["contact_id"] == second["contact_id"] == third["contact_id"]


@pytest.mark.parametrize("close_sql", [
    "UPDATE leads SET status = 'won', closed_at = now()",
    "UPDATE leads SET status = 'lost', lost_reason = 'expensive', closed_at = now()",
    "UPDATE leads SET created_at = now() - interval '31 days'",            # outside repeat_window_days
])
def test_after_the_parent_is_closed_or_old_a_repeat_is_a_new_lead(client, db, close_sql):
    first = lead_of(db, post(client, lead_payload()))
    db.execute(text(close_sql + " WHERE id = :i"), {"i": first["id"]})
    db.commit()
    second = lead_of(db, post(client, lead_payload()))
    assert second["status"] == "new" and second["parent_id"] is None and second["is_repeat"] is True


def test_a_form_never_renames_an_existing_contact(client, db):
    first = lead_of(db, post(client, lead_payload(name="Анна", contact="telegram")))
    second = lead_of(db, post(client, lead_payload(name="Злоумышленник", contact="call", breed="toj-pudel")))
    assert db.execute(text("SELECT name FROM contacts")).scalar() == "Анна"
    assert (first["name"], second["name"]) == ("Анна", "Злоумышленник")   # each request keeps what was typed


def test_blocked_contact_request_is_saved_as_spam_without_notification(client, db, webhook_on):
    first = lead_of(db, post(client, lead_payload()))
    db.execute(text("UPDATE contacts SET is_blocked = true"))
    db.commit()
    r = post(client, lead_payload(kind="consult"))
    assert r.status_code == 201 and set(r.json()) == {"id", "status"}      # the sender learns nothing
    lead = lead_of(db, r)
    assert (lead["status"], lead["spam_reason"], lead["parent_id"]) == ("spam", "blocked_contact", None)
    assert count(db, "outbox", "lead_id = :i", i=lead["id"]) == 0
    assert [h[0] for h in history(db, first["id"])] == ["created"]       # not attached to the real lead


def test_more_than_three_requests_an_hour_are_saved_but_not_notified(client, db, webhook_on):
    rows = [lead_of(db, post(client, lead_payload(kind=k))) for k in ("price", "puppy", "consult", "help", "shop")]
    assert [("rate_phone" in x["flags"]) for x in rows] == [False, False, False, True, True]
    notified = {lead_id for (lead_id,) in db.execute(text("SELECT lead_id FROM outbox"))}
    assert notified == {x["id"] for x in rows[:3]}
    assert len(webhook_on) == 3
    assert count(db, "leads") == 5                                       # nothing dropped


# ---------------------------------------------------------------- consent proof (152-ФЗ)
def test_older_known_consent_version_is_kept(client, db, older_processing_version):
    r = post(client, lead_payload(consent_version=older_processing_version))
    lead = lead_of(db, r)
    assert lead["consent_version"] == older_processing_version and lead["flags"] == []
    assert db.execute(text("SELECT version FROM consents WHERE lead_id = :i"), {"i": lead["id"]}).scalar() \
        == older_processing_version


@pytest.mark.parametrize("sent, flagged", [("processing-1999-01-01", True), (None, False), ("", False)])
def test_unknown_or_missing_consent_version_records_the_current_one(client, db, sent, flagged):
    p = lead_payload(consent_version=sent)
    r = post(client, p)
    lead = lead_of(db, r)
    assert lead["consent_version"] == CURRENT_CONSENT
    assert ("consent_version_fallback" in lead["flags"]) is flagged
    assert db.execute(text("SELECT version FROM consents")).scalar() == CURRENT_CONSENT


def test_consent_of_another_kind_is_not_proof_of_processing_consent(client, db):
    r = post(client, lead_payload(consent_version="distribution-2026-10-16"))
    lead = lead_of(db, r)
    kind = db.execute(text("SELECT kind FROM consent_versions WHERE version = :v"),
                      {"v": lead["consent_version"]}).scalar()
    assert kind == "processing"
    assert "consent_version_fallback" in lead["flags"]


# ---------------------------------------------------------------- paths, referrer, source
@pytest.mark.parametrize("raw, path", [
    ("/puppyhouse/maltipu/?utm_source=x&phone=%2B79991234567#form", "/maltipu/"),
    ("/puppyhouse", "/"),
    ("/puppyhouse/", "/"),
    ("/puppyhouse/index.html", "/"),
    ("/maltipu/index.html?x=1", "/maltipu/"),
    ("https://xn--b1adduihee9g.xn--p1ai/toj-pudel/cena/?q=Анна", "/toj-pudel/cena/"),
    ("maltipu/", "/maltipu/"),
    ("/puppyhouse-old/maltipu/", "/puppyhouse-old/maltipu/"),
])
def test_page_paths_are_normalised_and_lose_the_query(client, db, raw, path):
    r = post(client, lead_payload(page={"path": raw, "title": "t"}, landing=raw))
    lead = lead_of(db, r)
    assert lead["page_path"] == path and lead["landing_path"] == path
    assert db.execute(text("SELECT page_path FROM consents")).scalar() == path
    assert "79991234567" not in json.dumps({k: str(v) for k, v in lead.items() if k != "phone"})


@pytest.mark.parametrize("referrer", [
    "https://xn--b1adduihee9g.xn--p1ai/maltipu/",
    "https://www.xn--b1adduihee9g.xn--p1ai/",
    "https://домщенков.рф/toj-pudel/",
    "https://vseleznev54.github.io/puppyhouse/maltipu/",
])
def test_own_site_referrer_is_not_a_source(client, db, referrer):
    lead = lead_of(db, post(client, lead_payload(referrer=referrer)))
    assert lead["referrer_host"] is None
    assert (lead["source"], lead["medium"]) == ("(direct)", "(none)")


def test_referrer_keeps_only_the_host(client, db):
    lead = lead_of(db, post(client, lead_payload(
        referrer="https://yandex.ru/search/?text=мальтипу+купить+89991234567&lr=213")))
    assert lead["referrer_host"] == "yandex.ru"
    assert (lead["source"], lead["medium"]) == ("yandex", "organic")
    stored = json.dumps({k: str(v) for k, v in lead.items() if k != "phone"}, ensure_ascii=False)
    assert "89991234567" not in stored and "купить" not in stored


@pytest.mark.parametrize("utm, referrer, expected", [
    ({"utm_source": "Yandex", "utm_medium": "CPC", "utm_campaign": "maltipu-spring"}, "https://www.google.com/",
     ("yandex", "cpc")),
    ({"source": "vk", "campaign": "x"}, None, ("vk", "(not set)")),
    ({"yclid": "8273645"}, None, ("yandex", "cpc")),
    ({"gclid": "Cj0KCQ"}, None, ("google", "cpc")),
    ({"utm_source": "   "}, None, ("(direct)", "(none)")),
    (None, "https://yandex.ru/search/?text=x", ("yandex", "organic")),
    (None, "https://yabs.yandex.ru/count/abc", ("yandex", "cpc")),
    (None, "https://www.google.com/", ("google", "organic")),
    (None, "https://vk.com/wall-1_2", ("vk", "social")),
    (None, "https://t.me/s/kennel", ("telegram", "social")),
    (None, "https://dog-forum.ru/thread/1", ("dog-forum.ru", "referral")),
    (None, "https://xn--b1adduihee9g.xn--p1ai.evil.example/", ("xn--b1adduihee9g.xn--p1ai.evil.example",
                                                               "referral")),
    (None, None, ("(direct)", "(none)")),
])
def test_source_and_medium_classification(client, db, utm, referrer, expected):
    lead = lead_of(db, post(client, lead_payload(utm=utm, referrer=referrer)))
    assert (lead["source"], lead["medium"]) == expected
    if utm and utm.get("utm_campaign"):
        assert lead["utm"] == {"source": "Yandex", "medium": "CPC", "campaign": "maltipu-spring"}
        assert db.execute(text("SELECT utm_campaign FROM leads_maltipu")).scalar() == "maltipu-spring"


def test_referrer_host_is_not_matched_by_substring(client, db):
    lead = lead_of(db, post(client, lead_payload(referrer="https://petbook.ru/forum/maltipu")))
    assert (lead["source"], lead["medium"]) == ("petbook.ru", "referral")


# ---------------------------------------------------------------- concurrency
def _parallel(payloads: list[dict]):
    """Each thread has its own TestClient (own event loop); a barrier releases all requests at once."""
    from fastapi.testclient import TestClient
    from app.main import app
    barrier = threading.Barrier(len(payloads))

    def send(p):
        with TestClient(app, client=("203.0.113.10", 50000), headers={"Origin": ORIGIN},
                        raise_server_exceptions=False) as c:
            barrier.wait(timeout=20)
            return c.post(URL, json=p)

    with ThreadPoolExecutor(len(payloads)) as ex:
        return list(ex.map(send, payloads))


def test_parallel_requests_of_one_person_make_one_contact_and_one_parent(db):
    responses = _parallel([lead_payload(kind=k) for k in
                           ("price", "puppy", "consult", "help", "colour", "litter", "shop", "waitlist")])
    assert [r.status_code for r in responses] == [201] * 8, [r.text for r in responses]
    assert count(db, "contacts") == 1 and count(db, "leads") == 8 and count(db, "consents") == 8
    parents = leads(db, "l.parent_id IS NULL")
    assert len(parents) == 1 and parents[0]["status"] == "new"
    children = leads(db, "l.parent_id IS NOT NULL")
    assert len(children) == 7
    assert {(c["status"], c["parent_id"]) for c in children} == {("duplicate", parents[0]["id"])}
    assert count(db, "lead_history", "lead_id = :i AND action = 'repeat'", i=parents[0]["id"]) == 7


def test_parallel_retries_with_one_key_make_exactly_one_lead(db, webhook_on):
    p = lead_payload()
    responses = _parallel([dict(p) for _ in range(8)])
    codes = sorted(r.status_code for r in responses)
    assert codes == [200] * 7 + [201], [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1
    assert count(db, "leads") == 1 and count(db, "contacts") == 1 and count(db, "consents") == 1
    assert count(db, "lead_history") == 1 and count(db, "outbox") == 1
