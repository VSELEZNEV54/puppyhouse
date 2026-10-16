"""Admin authentication and access control: login sessions, brute-force limits, expiry, API keys, roles,
the audit log (152-ФЗ accountability), security headers, CORS per area and the API docs switch."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import uuid
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update

from conftest import ORIGIN

API = "/api/v1"
ADMIN = API + "/admin"
LOGIN = ADMIN + "/auth/login"
ADMIN_PW = "очень-длинный-пароль-1"
MANAGER_PW = "очень-длинный-пароль-2"
PEER_IP = "203.0.113.10"
ADMIN_ORIGIN = "https://admin.xn--b1adduihee9g.xn--p1ai"
PREVIEW_ORIGIN = "https://preview.example.org"
EVIL_ORIGIN = "https://evil.example.com"


# ---------------------------------------------------------------- helpers
def _login(client, login, password, **kw):
    return client.post(LOGIN, json={"login": login, "password": password}, **kw)


def _bearer(token: str) -> dict:
    return {"Authorization": "Bearer " + token}


def _token(headers: dict) -> str:
    return headers["Authorization"][len("Bearer "):]


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _audit(db, action: str) -> list[dict]:
    rows = db.execute(text(
        "SELECT action, actor_id, actor_label, target, host(ip) AS ip, details FROM audit_log "
        "WHERE action = :a ORDER BY id"), {"a": action}).mappings().all()
    return [dict(r) for r in rows]


def _service_key(db, login="svc-panel", name="Админ-панель", role=None):
    from app.enums import Role
    from app.services import auth
    user = auth.create_user(db, login, name, role or Role.admin, None, service=True)
    key = auth.create_api_key(db, user, name)
    db.commit()
    return user, key


def _lead(db, created: dict):
    from app.models import Lead
    db.expire_all()
    return db.scalar(select(Lead).where(Lead.public_id == uuid.UUID(created["id"])))


@pytest.fixture
def sleeps(monkeypatch):
    """Record the login delay instead of sleeping (keeps brute-force tests fast and lets us check it grows)."""
    from app.services import auth
    calls: list[float] = []
    monkeypatch.setattr(auth, "time", SimpleNamespace(sleep=calls.append))
    return calls


# ---------------------------------------------------------------- login
def test_login_ok_case_insensitive_and_token_stored_only_as_digest(client, db, admin_user, settings):
    settings.token_ttl_hours = 3
    before = dt.datetime.now(dt.timezone.utc)
    r = _login(client, "  ANNA ", ADMIN_PW)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"] == {"id": admin_user.id, "login": "anna", "name": "Анна", "role": "admin", "is_service": False}
    token = body["token"]
    expires = dt.datetime.fromisoformat(body["expires_at"])
    assert dt.timedelta(hours=3) - dt.timedelta(minutes=1) <= expires - before <= dt.timedelta(hours=3, minutes=1)

    me = client.get(ADMIN + "/me", headers=_bearer(token))
    assert me.status_code == 200 and me.json()["login"] == "anna"

    rows = db.execute(text("SELECT token_hash, kind, user_id FROM admin_tokens")).all()
    assert rows == [(_digest(token), "session", admin_user.id)]
    # the raw token appears nowhere in the database
    dump = db.execute(text("SELECT row_to_json(t)::text FROM admin_tokens t "
                           "UNION ALL SELECT row_to_json(a)::text FROM audit_log a")).scalars().all()
    assert all(token not in row for row in dump)


def test_login_cyrillic_login_is_case_insensitive(client, db):
    from app.enums import Role
    from app.services import auth
    auth.create_user(db, "Мария", "Мария", Role.manager, "пароль-из-двенадцати")
    db.commit()
    assert _login(client, "мария", "пароль-из-двенадцати").status_code == 200
    assert _login(client, "МАРИЯ", "пароль-из-двенадцати").status_code == 200


def test_wrong_password_and_unknown_login_answer_identically(client, admin_user):
    wrong = _login(client, "anna", "неверный-пароль-123")
    unknown = _login(client, "nobody", "неверный-пароль-123")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"]["code"] == "bad_credentials"
    assert "token" not in wrong.text


def test_deactivated_user_cannot_log_in_and_his_tokens_stop_working(client, db, admin_user, admin_h):
    from app.models import AdminUser
    assert client.get(ADMIN + "/me", headers=admin_h).status_code == 200
    db.execute(update(AdminUser).where(AdminUser.id == admin_user.id).values(is_active=False))
    db.commit()

    r = client.get(ADMIN + "/me", headers=admin_h)
    assert r.status_code == 401
    assert client.get(ADMIN + "/leads", headers=admin_h).status_code == 401
    bad = _login(client, "anna", ADMIN_PW)
    assert bad.status_code == 401
    # same answer as a wrong password: does not reveal that the account exists but is disabled
    assert bad.json() == _login(client, "nobody", "неверный-пароль-123").json()


def test_service_account_cannot_use_password_login(client, db):
    from app.services import auth
    user, key = _service_key(db)
    auth.set_password(db, user, "даже-с-паролем-нельзя")
    db.commit()
    r = _login(client, user.login, "даже-с-паролем-нельзя")
    assert r.status_code == 401 and r.json()["error"]["code"] == "bad_credentials"


# ---------------------------------------------------------------- brute force
def test_repeated_failures_per_login_are_refused_with_429(client, db, admin_user, manager_user, settings, sleeps):
    settings.login_per_login_15min = 3
    settings.login_per_ip_15min = 100
    for variant in ("anna", "ANNA", "Anna"):   # case variants share one bucket
        assert _login(client, variant, "неверный-пароль-123").status_code == 401
    # growing delay: (this client's failures for the login + the client's failures) × 0.25 s
    # + the login's failures from everywhere × 0.05 s
    assert sleeps == [0.0, 0.55, 1.1]

    blocked = _login(client, "anna", ADMIN_PW)  # from this client even the right password is refused for a while
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"

    # other accounts are not locked out by attacks on anna
    assert _login(client, "oleg", MANAGER_PW).status_code == 200
    blocked_rows = _audit(db, "login_blocked")
    assert [(r["target"], r["ip"]) for r in blocked_rows] == [("anna", PEER_IP)]


def test_failures_from_another_client_do_not_lock_the_manager_out(db, admin_user, settings, sleeps):
    """An attacker who knows the login must not be able to keep the real manager out by failing on purpose."""
    from app.main import app
    from fastapi.testclient import TestClient
    settings.login_per_login_15min = 3
    settings.login_per_ip_15min = 100
    with TestClient(app, client=("198.51.100.66", 1)) as attacker:
        for _ in range(5):
            assert attacker.post("/api/v1/admin/auth/login",
                                 json={"login": "anna", "password": "неверный-пароль-123"}).status_code in (401, 429)
        assert attacker.post("/api/v1/admin/auth/login",
                             json={"login": "anna", "password": ADMIN_PW}).status_code == 429
    with TestClient(app, client=("203.0.113.200", 1)) as anna:
        assert anna.post("/api/v1/admin/auth/login", json={"login": "anna", "password": ADMIN_PW}).status_code == 200


def test_per_ip_limit_spans_logins_and_ignores_spoofed_x_real_ip(client, admin_user, settings, sleeps):
    settings.login_per_login_15min = 100
    settings.login_per_ip_15min = 3
    for name in ("u1", "u2", "u3"):
        assert _login(client, name, "неверный-пароль-123").status_code == 401
    assert _login(client, "anna", ADMIN_PW).status_code == 429
    # the peer is not a trusted proxy: X-Real-IP must not reset the counter
    r = _login(client, "anna", ADMIN_PW, headers={"X-Real-IP": "198.51.100.77"})
    assert r.status_code == 429


def test_per_ip_limit_applies_to_an_ipv6_peer(admin_user, db, settings, sleeps):
    from app.main import app
    settings.login_per_login_15min = 100
    settings.login_per_ip_15min = 3
    with TestClient(app, client=("2001:db8:1:2::1", 50000), headers={"Origin": ORIGIN}) as c:
        for i in range(1, 4):
            assert _login(c, f"u{i}", "неверный-пароль-123").status_code == 401
        assert _login(c, "anna", ADMIN_PW).status_code == 429
    assert {r["ip"] for r in _audit(db, "login_failed")} == {"2001:db8:1:2::1"}


def test_per_ip_limit_groups_ipv6_by_64(admin_user, settings, sleeps):
    from app.main import app
    settings.login_per_login_15min = 100
    settings.login_per_ip_15min = 3
    for i in range(1, 4):
        with TestClient(app, client=(f"2001:db8:1:2::{i}", 50000), headers={"Origin": ORIGIN}) as c:
            assert _login(c, f"u{i}", "неверный-пароль-123").status_code == 401
    with TestClient(app, client=("2001:db8:1:2::99", 50000), headers={"Origin": ORIGIN}) as c:
        assert _login(c, "anna", ADMIN_PW).status_code == 429


# ---------------------------------------------------------------- session expiry / logout
def test_idle_session_expires(client, db, admin_h, settings):
    db.execute(text("UPDATE admin_tokens SET last_used_at = now() - interval '3 hours'"))
    db.commit()
    r = client.get(ADMIN + "/me", headers=admin_h)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "session_expired"
    # still expired on the next call (the failed request did not refresh last_used_at)
    assert client.get(ADMIN + "/me", headers=admin_h).json()["error"]["code"] == "session_expired"


def test_idle_limit_follows_settings_and_activity_slides_it(client, db, admin_h, settings):
    settings.token_idle_hours = 4
    db.execute(text("UPDATE admin_tokens SET last_used_at = now() - interval '3 hours'"))
    db.commit()
    assert client.get(ADMIN + "/me", headers=admin_h).status_code == 200
    # the request refreshed last_used_at, so the session keeps living while it is used
    age = db.execute(text("SELECT now() - last_used_at FROM admin_tokens")).scalar()
    assert age < dt.timedelta(minutes=1)
    settings.token_idle_hours = 2
    assert client.get(ADMIN + "/me", headers=admin_h).status_code == 200


def test_absolute_expiry_even_when_active(client, db, admin_h):
    db.execute(text("UPDATE admin_tokens SET expires_at = now() - interval '1 second', last_used_at = now()"))
    db.commit()
    r = client.get(ADMIN + "/me", headers=admin_h)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "session_expired"


def test_logout_revokes_only_this_session(client, db, admin_user):
    first = _bearer(_login(client, "anna", ADMIN_PW).json()["token"])
    second = _bearer(_login(client, "anna", ADMIN_PW).json()["token"])
    r = client.post(ADMIN + "/auth/logout", headers=first)
    assert r.status_code == 204
    gone = client.get(ADMIN + "/me", headers=first)
    assert gone.status_code == 401 and gone.json()["error"]["code"] == "unauthorized"
    assert client.post(ADMIN + "/auth/logout", headers=first).status_code == 401
    assert client.get(ADMIN + "/me", headers=second).status_code == 200
    revoked = db.execute(text("SELECT token_hash FROM admin_tokens WHERE revoked_at IS NOT NULL")).scalars().all()
    assert revoked == [_digest(_token(first))]


def test_password_reset_closes_sessions(client, db, admin_user, admin_h):
    from app.services import auth
    db.expire_all()
    auth.set_password(db, db.merge(admin_user), "новый-длинный-пароль-9")
    db.commit()
    assert client.get(ADMIN + "/me", headers=admin_h).status_code == 401
    assert _login(client, "anna", ADMIN_PW).status_code == 401
    assert _login(client, "anna", "новый-длинный-пароль-9").status_code == 200


@pytest.mark.parametrize("param", ["token", "access_token", "api_key", "authorization", "bearer"])
def test_token_never_accepted_from_query_string(client, admin_h, param):
    token = _token(admin_h)
    value = ("Bearer " + token) if param == "authorization" else token
    r = client.get(ADMIN + "/me", params={param: value})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def _admin_routes() -> list[tuple[str, str]]:
    """Every (method, path) under /api/v1/admin. FastAPI ≥ 0.14x wraps included routers in app.routes, so the
    routers' own APIRoutes and the generated OpenAPI paths are walked too."""
    from app.api import admin, public
    from app.main import app
    found: set[tuple[str, str]] = set()
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path.startswith(ADMIN):
            found |= {(m, r.path) for m in r.methods}
    for router in (admin.router, public.router):
        for r in router.routes:
            if isinstance(r, APIRoute) and (API + r.path).startswith(ADMIN):
                found |= {(m, API + r.path) for m in r.methods}
    for path, ops in app.openapi()["paths"].items():
        if path.startswith(ADMIN):
            found |= {(m.upper(), path) for m in ops}
    return sorted(found)


@pytest.mark.parametrize("auth_header", [None, "Bearer dsh_forged-token", "Bearer ", "Basic YW5uYTpwYXNz", "dsh_x"])
def test_every_admin_route_requires_a_token_except_login(client, auth_header):
    routes = _admin_routes()
    assert len(routes) >= 25
    headers = {"Authorization": auth_header} if auth_header is not None else {}
    open_routes = set()
    for method, path in routes:
        url = re.sub(r"\{(\w+)\}", lambda m: "maltipu-1" if m.group(1) == "slug" else "1", path)
        kw = {"json": {}} if method in ("POST", "PATCH", "PUT") else {}
        r = client.request(method, url, headers=headers, **kw)
        if r.status_code != 401:
            open_routes.add((method, path))
        else:
            assert r.json()["error"]["code"] == "unauthorized", (method, path, r.text)
    assert open_routes == {("POST", LOGIN)}


# ---------------------------------------------------------------- API keys
def test_api_key_authenticates_and_never_idles_out(client, db, settings):
    user, key = _service_key(db)
    r = client.get(ADMIN + "/me", headers=_bearer(key))
    assert r.status_code == 200
    assert r.json()["is_service"] is True and r.json()["id"] == user.id
    row = db.execute(text("SELECT kind, label, token_hash, expires_at FROM admin_tokens")).one()
    assert (row.kind, row.label, row.token_hash, row.expires_at) == ("api_key", "Админ-панель", _digest(key), None)
    db.execute(text("UPDATE admin_tokens SET last_used_at = now() - interval '30 days', "
                    "created_at = now() - interval '400 days'"))
    db.commit()
    assert client.get(ADMIN + "/me", headers=_bearer(key)).status_code == 200


def test_api_key_x_actor_goes_to_lead_history(client, db, make_lead):
    user, key = _service_key(db)
    lead = _lead(db, make_lead())
    r = client.patch(f"{ADMIN}/leads/{lead.id}", json={"version": lead.version, "status": "in_progress"},
                     headers={**_bearer(key), "X-Actor": "  Maria Petrova  "})
    assert r.status_code == 200, r.text
    rows = db.execute(text("SELECT actor_id, actor_label FROM lead_history WHERE lead_id = :l AND action = 'status'"),
                      {"l": lead.id}).all()
    assert rows == [(user.id, "Maria Petrova (Админ-панель)")]
    hist = client.get(f"{ADMIN}/leads/{lead.id}/history", headers=_bearer(key)).json()
    assert any(h.get("actor_label") == "Maria Petrova (Админ-панель)" for h in hist)

    # a very long X-Actor is cut, the history label still fits its column
    lead = _lead(db, make_lead())
    r = client.post(f"{ADMIN}/leads/{lead.id}/comments", json={"text": "перезвонить"},
                    headers={**_bearer(key), "X-Actor": "x" * 300})
    assert r.status_code == 200, r.text
    label = db.execute(text("SELECT actor_label FROM lead_history WHERE lead_id = :l AND action = 'comment'"),
                       {"l": lead.id}).scalar()
    assert label == "x" * 60 + " (Админ-панель)"


@pytest.mark.parametrize("raw", [
    pytest.param("Мария".encode("utf-8"), id="utf8-bytes"),
    pytest.param(b"%D0%9C%D0%B0%D1%80%D0%B8%D1%8F", id="percent-encoded"),
])
def test_api_key_x_actor_with_cyrillic_name(client, db, make_lead, raw):
    _, key = _service_key(db)
    lead = _lead(db, make_lead())
    r = client.patch(f"{ADMIN}/leads/{lead.id}", json={"version": lead.version, "status": "in_progress"},
                     headers={**_bearer(key), "X-Actor": raw})
    assert r.status_code == 200, r.text
    label = db.execute(text("SELECT actor_label FROM lead_history WHERE lead_id = :l AND action = 'status'"),
                       {"l": lead.id}).scalar()
    assert label == "Мария (Админ-панель)"


def test_session_user_cannot_impersonate_with_x_actor(client, db, admin_h, make_lead):
    lead = _lead(db, make_lead())
    r = client.patch(f"{ADMIN}/leads/{lead.id}", json={"version": lead.version, "status": "in_progress"},
                     headers={**admin_h, "X-Actor": "oleg"})
    assert r.status_code == 200, r.text
    labels = db.execute(text("SELECT actor_label FROM lead_history WHERE lead_id = :l AND action = 'status'"),
                        {"l": lead.id}).scalars().all()
    assert labels == ["Анна"]


def test_revoke_all_disables_api_keys(client, db):
    from app.services import auth
    user, key = _service_key(db)
    key2 = auth.create_api_key(db, user, "Второй ключ")
    db.commit()
    assert client.get(ADMIN + "/me", headers=_bearer(key2)).status_code == 200
    assert auth.revoke_all(db, user.id, ("api_key",)) == 2
    db.commit()
    for k in (key, key2):
        r = client.get(ADMIN + "/me", headers=_bearer(k))
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert auth.revoke_all(db, user.id) == 0  # already revoked ones are not counted again


def test_deactivated_service_user_key_stops_working(client, db):
    from app.models import AdminUser
    user, key = _service_key(db)
    db.execute(update(AdminUser).where(AdminUser.id == user.id).values(is_active=False))
    db.commit()
    assert client.get(ADMIN + "/me", headers=_bearer(key)).status_code == 401


# ---------------------------------------------------------------- roles
def test_manager_cannot_export_admin_can(client, db, admin_h, manager_h, make_lead):
    make_lead()
    r = client.get(ADMIN + "/export/leads.csv", headers=manager_h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert _audit(db, "export") == []

    r = client.get(ADMIN + "/export/leads.csv", headers=admin_h)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"].startswith("attachment;")
    assert r.headers["cache-control"] == "no-store"
    csv = r.content.decode("utf-8-sig")
    assert csv.startswith("№;") and "Анна" in csv


def test_manager_cannot_erase_contact_admin_can(client, db, admin_h, manager_h, make_lead):
    from app.models import Contact
    cid = _lead(db, make_lead()).contact_id
    body = {"reason": "request", "subject": "Анна, +7 999 123-45-67"}
    r = client.post(f"{ADMIN}/contacts/{cid}/erase", json=body, headers=manager_h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    db.expire_all()
    assert db.get(Contact, cid) is not None   # nothing was destroyed by the refused call

    r = client.post(f"{ADMIN}/contacts/{cid}/erase", json=body, headers=admin_h)
    assert r.status_code == 200, r.text
    assert r.json()["erased"] is True
    db.expire_all()
    assert db.get(Contact, cid) is None


# ---------------------------------------------------------------- audit log
def test_audit_login_and_login_failed(client, db, admin_user):
    assert _login(client, "anna", ADMIN_PW).status_code == 200
    assert _login(client, "Anna", "секретная-попытка-42").status_code == 401
    assert _login(client, "ghost", "секретная-попытка-43").status_code == 401

    ok = _audit(db, "login")
    assert [(r["actor_id"], r["actor_label"], r["ip"]) for r in ok] == [(admin_user.id, "Анна", PEER_IP)]
    failed = _audit(db, "login_failed")
    assert [(r["actor_id"], r["target"], r["ip"]) for r in failed] == [(admin_user.id, "anna", PEER_IP),
                                                                        (None, "ghost", PEER_IP)]
    # the typed passwords are never stored
    everything = json.dumps([dict(r) for r in db.execute(text("SELECT * FROM audit_log")).mappings()], default=str)
    assert "секретная-попытка" not in everything and ADMIN_PW not in everything


def test_audit_view_contact_and_export(client, db, admin_user, admin_h, make_lead):
    cid = _lead(db, make_lead()).contact_id
    assert client.get(f"{ADMIN}/contacts/{cid}", headers=admin_h).status_code == 200
    views = _audit(db, "view_contact")
    assert [(r["actor_id"], r["target"], r["ip"]) for r in views] == [(admin_user.id, f"contact:{cid}", PEER_IP)]

    assert client.get(ADMIN + "/export/leads.csv?breed=maltipu", headers=admin_h).status_code == 200
    exports = _audit(db, "export")
    assert len(exports) == 1
    assert (exports[0]["actor_id"], exports[0]["ip"], exports[0]["details"]["rows"]) == (admin_user.id, PEER_IP, 1)
    assert "maltipu" in json.dumps(exports[0]["details"]["filters"])


def test_audit_through_api_key_names_the_person(client, db, make_lead):
    user, key = _service_key(db)
    cid = _lead(db, make_lead()).contact_id
    h = {**_bearer(key), "X-Actor": "Maria"}
    assert client.get(f"{ADMIN}/contacts/{cid}", headers=h).status_code == 200
    assert client.get(ADMIN + "/export/leads.csv", headers=h).status_code == 200
    labels = [r["actor_label"] for r in _audit(db, "view_contact") + _audit(db, "export")]
    assert labels and all("Maria" in label for label in labels), labels


# ---------------------------------------------------------------- password policy
def test_password_policy(db, settings):
    from app.enums import Role
    from app.services import auth
    with pytest.raises(ValueError):
        auth.create_user(db, "short", "Коротко", Role.manager, "a" * 11)
    with pytest.raises(ValueError):
        auth.create_user(db, "nopass", "Без пароля", Role.manager, None)
    u = auth.create_user(db, "exact", "Ровно", Role.manager, "b" * 12)
    with pytest.raises(ValueError):
        auth.set_password(db, u, "c" * 11)
    with pytest.raises(ValueError):          # logins are unique case-insensitively
        auth.create_user(db, "EXACT", "Дубль", Role.manager, "d" * 12)
    settings.min_password_len = 16
    with pytest.raises(ValueError):
        auth.create_user(db, "longer", "Длиннее", Role.manager, "e" * 15)
    assert auth.create_user(db, "svc-x", "Сервис", Role.admin, None, service=True).password_hash is None
    db.rollback()


# ---------------------------------------------------------------- headers, CORS, logs
def test_security_headers_on_admin_and_public_responses(client, admin_user):
    login = _login(client, "anna", ADMIN_PW)
    responses = [login, client.get(ADMIN + "/me", headers=_bearer(login.json()["token"])),
                 client.get(ADMIN + "/me"), _login(client, "anna", "неверный-пароль-123"), client.get(API + "/health")]
    for r in responses:
        assert r.headers.get("x-content-type-options") == "nosniff", r.url
        assert r.headers.get("cache-control") == "no-store", r.url
        assert r.headers.get("referrer-policy") == "no-referrer", r.url
        assert "frame-ancestors 'none'" in r.headers.get("content-security-policy", ""), r.url


def _preflight(client, path, origin):
    return client.options(path, headers={"Origin": origin, "Access-Control-Request-Method": "GET",
                                         "Access-Control-Request-Headers": "authorization, x-actor"})


def test_cors_is_separate_for_admin_and_public(client, settings):
    settings.admin_cors_origins = [ADMIN_ORIGIN]
    settings.cors_origins = [PREVIEW_ORIGIN]

    ok = _preflight(client, ADMIN + "/leads", ADMIN_ORIGIN)
    assert ok.status_code == 204
    assert ok.headers["access-control-allow-origin"] == ADMIN_ORIGIN
    assert "Authorization" in ok.headers["access-control-allow-headers"]
    assert "X-Actor" in ok.headers["access-control-allow-headers"]

    pub = _preflight(client, API + "/leads", PREVIEW_ORIGIN)
    assert pub.status_code == 204 and pub.headers["access-control-allow-origin"] == PREVIEW_ORIGIN

    for path, origin in [(API + "/leads", ADMIN_ORIGIN), (ADMIN + "/leads", PREVIEW_ORIGIN),
                         (ADMIN + "/leads", EVIL_ORIGIN), (API + "/leads", EVIL_ORIGIN), (ADMIN + "/leads", ORIGIN)]:
        r = _preflight(client, path, origin)
        assert r.status_code == 403, (path, origin)
        assert "access-control-allow-origin" not in r.headers, (path, origin)


def test_cors_headers_on_actual_admin_requests(client, settings, admin_h):
    settings.admin_cors_origins = [ADMIN_ORIGIN]
    settings.cors_origins = [PREVIEW_ORIGIN]
    r = client.get(ADMIN + "/me", headers={**admin_h, "Origin": ADMIN_ORIGIN})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == ADMIN_ORIGIN
    # the panel can read a 401 too (to show «войдите заново»)
    r = client.get(ADMIN + "/me", headers={"Origin": ADMIN_ORIGIN})
    assert r.status_code == 401 and r.headers["access-control-allow-origin"] == ADMIN_ORIGIN
    # a public-area origin never gets admin data readable by its scripts
    r = client.get(ADMIN + "/me", headers={**admin_h, "Origin": PREVIEW_ORIGIN})
    assert "access-control-allow-origin" not in r.headers
    r = client.get(API + "/health", headers={"Origin": ADMIN_ORIGIN})
    assert "access-control-allow-origin" not in r.headers


def test_access_log_has_no_query_string_token_or_ip(client, admin_h, caplog):
    caplog.set_level(logging.INFO, logger="dsh.http")
    r = client.get(ADMIN + "/leads", params={"q": "79991234567"}, headers=admin_h)
    assert r.status_code == 200
    lines = [rec.getMessage() for rec in caplog.records if rec.name == "dsh.http"]
    assert any("/api/v1/admin/leads" in line for line in lines)
    for line in lines:
        assert "79991234567" not in line and PEER_IP not in line and _token(admin_h) not in line


# ---------------------------------------------------------------- docs
@pytest.mark.parametrize("env, expose, visible", [
    ("test", None, True),
    ("test", False, False),
    ("prod", None, False),
    ("prod", True, True),
])
def test_docs_switch(settings, env, expose, visible):
    from app.main import create_app
    settings.env = env
    settings.expose_docs = expose
    with TestClient(create_app()) as c:
        docs = c.get(API + "/docs")
        spec = c.get(API + "/openapi.json")
    if visible:
        assert docs.status_code == 200 and spec.status_code == 200
        assert LOGIN in spec.json()["paths"]
    else:
        assert docs.status_code == 404 and spec.status_code == 404
