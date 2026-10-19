"""Notifications to the kennel's managers (app/services/notify.py) and the health checks built on the outbox.

What matters for a real kennel:
- a request from the site is never lost and the managers always hear about it (outbox row in the request's
  transaction, retries with backoff, permanent failures recognised);
- Telegram is abroad: by default no name and no phone go there (152-ФЗ, cross-border transfer);
- no secret (bot token, SMTP password) leaks into the database or the logs;
- an erased person is never sent anywhere.
No network: Telegram / webhook go through httpx.MockTransport, SMTP is a fake class.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import smtplib
import uuid
import zoneinfo
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select, text

from app.api import public
from app.models import Lead, Outbox
from app.services import notify
from conftest import CONSENT_CURRENT, lead_payload

UTC = dt.timezone.utc
TOKEN = "7012345678:AAH-test_SECRET-token-0123456789abcd"
DEFAULT_CHAT = "-1001000000001"
MALTIPU_CHAT = "-1002000000002"
WEBHOOK_URL = "https://admin.example/hooks/dsh"
WEBHOOK_SECRET = "w3bh00k-secret-" + "x" * 20
SMTP_PASSWORD = "smtp-PASSWORD-very-secret"
NAME = "Евлампия"
PHONE_FORM = "+7 (999) 123-45-67"
PHONE_E164 = "+79991234567"
ORIGINAL_DELIVER_NOW = public._deliver_now


# ---------------------------------------------------------------- helpers / fixtures
class FakeHttp:
    """Records every request; answers with the queued responses (or 200 ok)."""

    def __init__(self, *responses):
        self.requests: list[httpx.Request] = []
        self.responses = list(responses)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        r = self.responses.pop(0) if self.responses else httpx.Response(200, json={"ok": True, "result": {}})
        if isinstance(r, Exception):
            raise r
        if callable(r):
            return r(request)
        return r

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def json(self, i: int = 0) -> dict:
        return json.loads(self.requests[i].content)


class FakeSMTP:
    """Stands in for smtplib.SMTP_SSL; class-level records so the test can see what was sent."""
    sent: list = []
    logins: list = []
    connects: list = []
    login_error: Exception | None = None
    connect_error: Exception | None = None

    def __init__(self, host, port, timeout=None, context=None):
        if FakeSMTP.connect_error is not None:
            raise FakeSMTP.connect_error
        FakeSMTP.connects.append((host, port))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        if FakeSMTP.login_error is not None:
            raise FakeSMTP.login_error
        FakeSMTP.logins.append((user, password))

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """The route schedules _deliver_now (real HTTP) after the response: record the call instead.
    Any deliver_due() without an explicit client would build a real httpx.Client — forbid that too."""
    calls: list[int] = []
    monkeypatch.setattr(public, "_deliver_now", lambda: calls.append(1))

    def _no_real_client(*a, **kw):
        raise AssertionError("a real httpx.Client was created in a test")
    monkeypatch.setattr(notify, "httpx", SimpleNamespace(Client=_no_real_client))
    return calls


@pytest.fixture
def tg(settings):
    settings.telegram_bot_token = TOKEN
    settings.telegram_chat_id = DEFAULT_CHAT
    settings.telegram_breed_chats = {}
    settings.telegram_include_pd = False
    settings.admin_base_url = ""
    return settings


@pytest.fixture
def webhook(settings):
    settings.webhook_url = WEBHOOK_URL
    settings.webhook_secret = WEBHOOK_SECRET
    return settings


@pytest.fixture
def email(settings, monkeypatch):
    settings.smtp_host = "smtp.yandex.ru"
    settings.smtp_port = 465
    settings.smtp_ssl = True
    settings.smtp_user = "kennel@yandex.ru"
    settings.smtp_password = SMTP_PASSWORD
    settings.smtp_from = "kennel@yandex.ru"
    settings.notify_emails = ["owner@yandex.ru"]
    FakeSMTP.sent, FakeSMTP.logins, FakeSMTP.connects = [], [], []
    FakeSMTP.login_error = FakeSMTP.connect_error = None
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def post_lead(client, **over) -> tuple[int, dict]:
    over.setdefault("name", NAME)
    over.setdefault("phone", PHONE_FORM)
    r = client.post("/api/v1/leads", json=lead_payload(**over))
    assert r.status_code == 201, r.text
    body = r.json()
    lead_id = client_db_lead_id(body["id"])
    return lead_id, body


def client_db_lead_id(public_id: str) -> int:
    from app.db import _factory
    with _factory()() as s:
        return s.scalar(select(Lead.id).where(Lead.public_id == uuid.UUID(public_id)))


def outbox(db) -> list[Outbox]:
    db.expire_all()
    return list(db.scalars(select(Outbox).order_by(Outbox.id)))


def make_due(db) -> None:
    db.execute(text("UPDATE outbox SET next_attempt_at = now() WHERE status = 'pending'"))
    db.commit()


def tg_text(fake: FakeHttp, i: int = 0) -> str:
    return fake.json(i)["text"]


# ---------------------------------------------------------------- enqueue
def test_site_request_enqueues_one_telegram_row_in_the_request_transaction(client, db, tg, no_network):
    lead_id, _ = post_lead(client)
    rows = outbox(db)
    assert len(rows) == 1
    o = rows[0]
    assert (o.channel, o.target, o.event, o.lead_id, o.status, o.attempts) == \
        ("telegram", DEFAULT_CHAT, "lead.created", lead_id, "pending", 0)
    assert o.sent_at is None and o.last_error is None
    # now() is the transaction start in PostgreSQL: equal timestamps prove one transaction
    lead_created = db.scalar(select(Lead.created_at).where(Lead.id == lead_id))
    assert o.created_at == lead_created
    assert no_network == [1], "the immediate delivery must be scheduled after the response"


def test_without_configured_channels_nothing_is_enqueued_and_no_delivery_is_scheduled(client, db, no_network):
    post_lead(client)
    assert outbox(db) == []
    assert no_network == []


def test_idempotent_replay_does_not_notify_twice(client, db, tg, no_network):
    p = lead_payload(name=NAME)
    assert client.post("/api/v1/leads", json=p).status_code == 201
    r2 = client.post("/api/v1/leads", json=p)
    assert r2.status_code == 200
    assert len(outbox(db)) == 1
    assert no_network == [1]


def test_honeypot_bot_request_enqueues_nothing(client, db, tg, no_network):
    r = client.post("/api/v1/leads", json=lead_payload(hp_note="buy cheap"))
    assert r.status_code == 201
    assert outbox(db) == [] and no_network == []


def test_repeat_request_enqueues_lead_repeat_and_text_points_to_the_parent(client, db, tg):
    tg.admin_base_url = "https://admin.example/leads/{id}"
    first, _ = post_lead(client, kind="price")
    second, _ = post_lead(client, kind="video_call")
    parent = db.scalar(select(Lead.parent_id).where(Lead.id == second))
    assert parent == first
    events = [(o.lead_id, o.event) for o in outbox(db)]
    assert events == [(first, "lead.created"), (second, "lead.repeat")]

    fake = FakeHttp()
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 2, "failed": 0, "retry": 0}
    repeat_text = tg_text(fake, 1)
    assert repeat_text.startswith(f"🔁 <b>Повторный запрос по заявке №{first}</b>")
    assert "Видеозвонок со щенком" in repeat_text
    assert f'<a href="https://admin.example/leads/{first}">Открыть заявку в админке</a>' in repeat_text
    assert NAME not in repeat_text and "999" not in repeat_text


def test_rate_phone_flagged_request_is_saved_but_not_notified(client, db, tg, settings, no_network):
    settings.leads_per_phone_hour = 1
    first, _ = post_lead(client, breed="maltipu")
    second, _ = post_lead(client, breed="border-kolli")  # another breed: not a repeat, but the same phone
    flags = db.scalar(select(Lead.flags).where(Lead.id == second))
    assert "rate_phone" in flags
    assert [o.lead_id for o in outbox(db)] == [first]
    assert no_network == [1]


def test_request_of_a_blocked_contact_is_spam_and_not_notified(client, db, tg):
    first, _ = post_lead(client)
    db.execute(text("UPDATE contacts SET is_blocked = true"))
    db.execute(text("DELETE FROM outbox"))
    db.commit()
    second, _ = post_lead(client, breed="toj-pudel")
    assert db.scalar(select(Lead.status).where(Lead.id == second)) == "spam"
    assert outbox(db) == []


# ---------------------------------------------------------------- telegram delivery
def test_delivery_goes_to_the_breed_chat_by_breed_key(client, db, tg):
    tg.telegram_breed_chats = {"maltipu": MALTIPU_CHAT}
    lead_id, _ = post_lead(client, breed="maltipu")
    assert outbox(db)[0].target == MALTIPU_CHAT

    fake = FakeHttp()
    stats = notify.deliver_due(db, client=fake.client())
    assert stats == {"sent": 1, "failed": 0, "retry": 0}
    assert len(fake.requests) == 1
    req = fake.requests[0]
    assert req.method == "POST" and str(req.url) == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert fake.json()["chat_id"] == MALTIPU_CHAT
    o = outbox(db)[0]
    assert (o.status, o.attempts, o.last_error) == ("sent", 1, None) and o.sent_at is not None

    # sent once: a second run sends nothing
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 0, "failed": 0, "retry": 0}
    assert len(fake.requests) == 1


@pytest.mark.parametrize("breed", ["border-kolli", "francuzskij-buldog", None])
def test_breed_without_its_own_chat_goes_to_the_default_chat(client, db, tg, breed):
    tg.telegram_breed_chats = {"maltipu": MALTIPU_CHAT}
    post_lead(client, breed=breed)
    fake = FakeHttp()
    notify.deliver_due(db, client=fake.client())
    assert fake.json()["chat_id"] == DEFAULT_CHAT


def test_telegram_text_has_no_personal_data_by_default(client, db, tg):
    lead_id, _ = post_lead(client, breed="maltipu", kind="price")
    fake = FakeHttp()
    notify.deliver_due(db, client=fake.client())
    payload = fake.json()
    assert payload["parse_mode"] == "HTML"
    msg = payload["text"]
    assert msg.splitlines()[0] == f"🐶 <b>Новая заявка №{lead_id}</b>"
    assert "🐾 Порода: Мальтипу" in msg and "📋 Запрос: Узнать цену" in msg
    assert "📍 Источник: ✍️ прямой заход" in msg
    created = db.scalar(select(Lead.created_at).where(Lead.id == lead_id))
    assert f"🕒 {created.astimezone(zoneinfo.ZoneInfo('Europe/Moscow')):%d.%m.%Y, %H:%M}" in msg
    raw = fake.requests[0].content.decode()  # the whole request, not only the text field
    for pd in (NAME, PHONE_FORM, PHONE_E164, "9991234567", "123-45-67", "Telegram"):
        assert pd not in raw, pd


def test_telegram_text_carries_name_and_phone_only_with_include_pd(client, db, tg):
    from app.services import consent
    cur = consent.current("processing")
    assert not consent.allows_cross_border(cur)        # the site's consent: nothing goes abroad
    abroad = "processing-2026-10-20-3"                 # an edition that names the transfer to Telegram
    assert consent.allows_cross_border(abroad)
    # the switch is off: no personal data, whatever the consent
    post_lead(client, contact="whatsapp", consent_version=abroad)
    fake = FakeHttp()
    notify.deliver_due(db, client=fake.client())
    assert NAME not in fake.json()["text"]
    db.execute(text("DELETE FROM outbox"))
    db.commit()
    tg.telegram_include_pd = True
    # the switch alone is not enough: the consent the person gave must name the transfer abroad
    post_lead(client, contact="whatsapp", consent_version=cur, phone="+7 (999) 111-22-33", breed="francuzskij-buldog")
    fake = FakeHttp()
    notify.deliver_due(db, client=fake.client())
    assert NAME not in fake.json()["text"] and "111-22-33" not in fake.json()["text"]
    db.execute(text("DELETE FROM outbox"))
    db.commit()
    post_lead(client, contact="whatsapp", consent_version=abroad, phone="+7 (999) 765-43-21", breed="toj-pudel")
    fake = FakeHttp()
    notify.deliver_due(db, client=fake.client())
    msg = fake.json()["text"]
    assert f"👤 Имя: {NAME}" in msg and "📞 Телефон: +7 (999) 765-43-21" in msg and "💬 Куда написать: WhatsApp" in msg


def test_telegram_403_fails_at_once_and_is_never_retried(client, db, tg):
    post_lead(client)
    fake = FakeHttp(httpx.Response(403, json={"ok": False, "error_code": 403,
                                              "description": "Forbidden: bot was blocked by the user"}))
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 0, "failed": 1, "retry": 0}
    o = outbox(db)[0]
    assert (o.status, o.attempts) == ("failed", 1)
    assert "403" in o.last_error and "bot was blocked" in o.last_error
    make_due(db)
    notify.deliver_due(db, client=fake.client())
    assert len(fake.requests) == 1


def test_telegram_429_waits_exactly_retry_after(client, db, tg):
    post_lead(client)
    fake = FakeHttp(httpx.Response(429, json={"ok": False, "error_code": 429,
                                              "description": "Too Many Requests: retry after 42",
                                              "parameters": {"retry_after": 42}}))
    before = dt.datetime.now(UTC)
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 0, "failed": 0, "retry": 1}
    o = outbox(db)[0]
    assert (o.status, o.attempts) == ("pending", 1)
    delay = (o.next_attempt_at - before).total_seconds()
    assert 40 <= delay <= 45, delay
    # not due yet: nothing is sent on the next run
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 0, "failed": 0, "retry": 0}
    assert len(fake.requests) == 1


def test_telegram_500_retries_with_growing_backoff_then_fails(client, db, tg, settings):
    settings.notify_max_attempts = 3
    post_lead(client)
    fake = FakeHttp(*[httpx.Response(500, json={"ok": False, "description": "Internal Server Error"})] * 3)
    delays = []
    for attempt in (1, 2):
        before = dt.datetime.now(UTC)
        assert notify.deliver_due(db, client=fake.client()) == {"sent": 0, "failed": 0, "retry": 1}
        o = outbox(db)[0]
        assert (o.status, o.attempts) == ("pending", attempt)
        delays.append((o.next_attempt_at - before).total_seconds())
        make_due(db)
    assert 28 <= delays[0] <= 33 and 58 <= delays[1] <= 63, delays
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 0, "failed": 1, "retry": 0}
    o = outbox(db)[0]
    assert (o.status, o.attempts) == ("failed", 3) and "500" in o.last_error
    assert len(fake.requests) == 3


def test_a_retry_that_succeeds_marks_the_row_sent_and_clears_the_error(client, db, tg):
    post_lead(client)
    fake = FakeHttp(httpx.Response(502, text="Bad Gateway"))
    notify.deliver_due(db, client=fake.client())
    assert outbox(db)[0].last_error
    make_due(db)
    assert notify.deliver_due(db, client=fake.client())["sent"] == 1
    o = outbox(db)[0]
    assert (o.status, o.attempts, o.last_error) == ("sent", 2, None)


def _raise_with_url(request: httpx.Request):
    raise httpx.ConnectError(f"[Errno 111] Connection refused while connecting to {request.url}", request=request)


def _echo_url(request: httpx.Request):
    return httpx.Response(502, text=f"<html>upstream {request.url} unavailable</html>")


@pytest.mark.parametrize("answer", [_raise_with_url, _echo_url], ids=["transport-error", "error-page"])
def test_bot_token_never_reaches_the_outbox_or_the_log(client, db, tg, caplog, answer):
    post_lead(client)
    fake = FakeHttp(answer)
    with caplog.at_level("DEBUG"):
        assert notify.deliver_due(db, client=fake.client())["retry"] == 1
    o = outbox(db)[0]
    assert o.status == "pending" and o.last_error
    assert TOKEN not in o.last_error and TOKEN.split(":")[1] not in o.last_error
    assert "***" in o.last_error
    assert TOKEN not in caplog.text and TOKEN.split(":")[1] not in caplog.text


@pytest.mark.parametrize("cut", [5, 20])
def test_a_token_cut_by_the_error_length_limit_is_not_stored_either(client, db, tg, caplog, cut):
    """An error page (a proxy, a CDN) that echoes the request URL: the 200-char limit can fall inside the token."""
    secret = TOKEN.split(":")[1]

    def page(request: httpx.Request):
        url = str(request.url)
        pad = 200 - url.index(TOKEN) - len(TOKEN) + cut  # the 200th character falls `cut` chars before the end
        return httpx.Response(502, text="x" * pad + url)
    post_lead(client)
    with caplog.at_level("DEBUG"):
        notify.deliver_due(db, client=FakeHttp(page).client())
    err = outbox(db)[0].last_error
    leaked = [secret[:n] for n in range(12, len(secret) + 1) if secret[:n] in err + caplog.text]
    assert not leaked, f"{len(leaked[-1])} of {len(secret)} secret characters of the bot token were stored"


def test_one_broken_chat_does_not_block_other_notifications(client, db, tg):
    tg.telegram_breed_chats = {"maltipu": MALTIPU_CHAT}
    post_lead(client, breed="maltipu")
    post_lead(client, breed="border-kolli", phone="+7 (999) 765-43-21")

    def answer(request):
        if json.loads(request.content)["chat_id"] == MALTIPU_CHAT:
            return httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})
        return httpx.Response(200, json={"ok": True, "result": {}})
    fake = FakeHttp(answer, answer)
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 1, "failed": 1, "retry": 0}
    assert {o.target: o.status for o in outbox(db)} == {MALTIPU_CHAT: "failed", DEFAULT_CHAT: "sent"}


def test_a_row_locked_by_another_worker_is_skipped_not_sent_twice(client, db, tg):
    post_lead(client)
    from app.db import _factory
    other = _factory()()
    try:
        other.execute(text("SELECT id FROM outbox FOR UPDATE")).all()  # another worker is sending it
        fake = FakeHttp()
        assert notify.deliver_due(db, client=fake.client()) == {"sent": 0, "failed": 0, "retry": 0}
        assert fake.requests == []
    finally:
        other.rollback()
        other.close()
    assert notify.deliver_due(db, client=fake.client())["sent"] == 1


def test_request_is_delivered_right_after_the_response(client, db, tg, monkeypatch):
    fake = FakeHttp()
    monkeypatch.setattr(public, "_deliver_now", ORIGINAL_DELIVER_NOW)
    monkeypatch.setattr(notify, "httpx", SimpleNamespace(Client=lambda **kw: fake.client()))
    post_lead(client)
    assert len(fake.requests) == 1
    assert outbox(db)[0].status == "sent"


def test_telegram_outage_does_not_lose_the_request(client, db, tg, monkeypatch):
    fake = FakeHttp(_raise_with_url)
    monkeypatch.setattr(public, "_deliver_now", ORIGINAL_DELIVER_NOW)
    monkeypatch.setattr(notify, "httpx", SimpleNamespace(Client=lambda **kw: fake.client()))
    lead_id, _ = post_lead(client)
    assert lead_id is not None
    o = outbox(db)[0]
    assert (o.status, o.attempts) == ("pending", 1)  # the worker will retry


# ---------------------------------------------------------------- webhook
def test_webhook_is_hmac_signed_over_the_exact_body_and_carries_no_personal_data(client, db, webhook):
    lead_id, body = post_lead(client)
    rows = outbox(db)
    assert [(o.channel, o.target, o.event) for o in rows] == [("webhook", WEBHOOK_URL, "lead.created")]
    fake = FakeHttp(httpx.Response(204))
    assert notify.deliver_due(db, client=fake.client())["sent"] == 1
    req = fake.requests[0]
    assert str(req.url) == WEBHOOK_URL
    expected = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), req.content, hashlib.sha256).hexdigest()
    assert req.headers["X-Dsh-Signature"] == expected
    assert req.headers["X-Dsh-Event"] == "lead.created"
    data = json.loads(req.content)
    assert data["event"] == "lead.created" and data["id"] == lead_id
    assert data["public_id"] == body["id"] and data["parent_id"] is None
    assert set(data) <= {"event", "id", "public_id", "parent_id", "type", "delivery", "at"}
    raw = req.content.decode()
    for pd in (NAME, PHONE_FORM, PHONE_E164, "9991234567"):
        assert pd not in raw


@pytest.mark.parametrize("status, outcome", [(200, "sent"), (410, "failed"), (401, "failed"), (503, "pending")])
def test_webhook_answer_codes(client, db, webhook, status, outcome):
    post_lead(client)
    fake = FakeHttp(httpx.Response(status))
    notify.deliver_due(db, client=fake.client())
    assert outbox(db)[0].status == outcome


def test_admin_patch_enqueues_lead_updated_for_the_webhook_only(client, db, tg, webhook, email, admin_h):
    lead_id, _ = post_lead(client)
    assert sorted(o.channel for o in outbox(db)) == ["email", "telegram", "webhook"]
    db.execute(text("DELETE FROM outbox"))
    db.commit()
    version = db.scalar(select(Lead.version).where(Lead.id == lead_id))
    r = client.patch(f"/api/v1/admin/leads/{lead_id}", json={"version": version, "status": "in_progress"},
                     headers=admin_h)
    assert r.status_code == 200, r.text
    assert [(o.channel, o.event, o.lead_id) for o in outbox(db)] == [("webhook", "lead.updated", lead_id)]

    fake = FakeHttp()
    notify.deliver_due(db, client=fake.client())
    data = json.loads(fake.requests[0].content)
    assert data["event"] == "lead.updated" and data["id"] == lead_id
    assert FakeSMTP.sent == []


def test_manual_request_by_a_manager_pings_only_the_webhook(client, db, tg, webhook, manager_h):
    r = client.post("/api/v1/admin/leads", headers=manager_h,
                    json={"origin": "phone", "name": "Пётр", "phone": "+7 999 000-11-22", "breed": "maltipu"})
    assert r.status_code == 201, r.text
    assert [(o.channel, o.event) for o in outbox(db)] == [("webhook", "lead.created")]


# ---------------------------------------------------------------- e-mail
def test_email_has_full_details_and_a_russian_subject(client, db, email):
    lead_id, _ = post_lead(client, breed="maltipu", kind="price", contact="telegram")
    rows = outbox(db)
    assert [(o.channel, o.target) for o in rows] == [("email", "owner@yandex.ru")]
    fake = FakeHttp()
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 1, "failed": 0, "retry": 0}
    assert fake.requests == []
    assert FakeSMTP.connects == [("smtp.yandex.ru", 465)]
    assert FakeSMTP.logins == [("kennel@yandex.ru", SMTP_PASSWORD)]
    assert len(FakeSMTP.sent) == 1
    msg = FakeSMTP.sent[0]
    assert msg["Subject"] == f"Заявка №{lead_id}: Мальтипу, Узнать цену"
    assert [a.addr_spec for a in msg["To"].addresses] == ["owner@yandex.ru"]
    content = msg.get_content()
    assert f"Имя: {NAME}" in content
    assert f"Телефон: {PHONE_FORM}" in content
    assert "Порода: Мальтипу" in content and "Куда написать: Telegram" in content
    assert SMTP_PASSWORD not in msg.as_string()


def test_smtp_authentication_error_is_permanent(client, db, email):
    email.login_error = smtplib.SMTPAuthenticationError(535, b"5.7.8 Error: authentication failed")
    post_lead(client)
    assert notify.deliver_due(db, client=FakeHttp().client()) == {"sent": 0, "failed": 1, "retry": 0}
    o = outbox(db)[0]
    assert (o.status, o.attempts) == ("failed", 1)
    assert "SMTPAuthenticationError" in o.last_error and SMTP_PASSWORD not in o.last_error
    assert email.sent == []


@pytest.mark.parametrize("error, outcome", [
    (ConnectionRefusedError(111, "Connection refused"), "pending"),
    (smtplib.SMTPServerDisconnected("Connection unexpectedly closed"), "pending"),
    (smtplib.SMTPRecipientsRefused({"owner@yandex.ru": (550, b"No such user")}), "failed"),
], ids=["refused", "disconnected", "recipients-refused"])
def test_smtp_transient_errors_are_retried_permanent_ones_are_not(client, db, email, error, outcome):
    email.connect_error = error
    post_lead(client)
    notify.deliver_due(db, client=FakeHttp().client())
    o = outbox(db)[0]
    assert (o.status, o.attempts) == (outcome, 1)


def test_starttls_runs_before_the_password_is_sent(client, db, email, settings, monkeypatch):
    settings.smtp_ssl = False
    settings.smtp_port = 587
    calls: list[str] = []

    class PlainSMTP(FakeSMTP):
        def starttls(self, context=None):
            calls.append("starttls")

        def login(self, user, password):
            calls.append("login")

        def send_message(self, msg):
            calls.append("send")
    monkeypatch.setattr(smtplib, "SMTP", PlainSMTP)
    post_lead(client)
    assert notify.deliver_due(db, client=FakeHttp().client())["sent"] == 1
    assert calls == ["starttls", "login", "send"]


def test_a_long_list_of_notification_addresses_does_not_break_request_intake(client, db, email, settings):
    settings.notify_emails = [f"manager{i:02d}@pitomnik-domshchenkov.ru" for i in range(12)]  # > 300 characters
    r = client.post("/api/v1/leads", json=lead_payload(name=NAME))
    assert r.status_code == 201, r.text
    assert db.scalar(text("SELECT count(*) FROM leads")) == 1
    # one notification per address: a bad address cannot block the others
    assert sorted(o.target for o in outbox(db)) == sorted(settings.notify_emails)


def test_a_broken_notification_setting_never_costs_the_request(client, db, email, settings):
    settings.notify_emails = ["x" * 400 + "@example.ru"]  # longer than the outbox column
    r = client.post("/api/v1/leads", json=lead_payload(name=NAME))
    assert r.status_code == 201, r.text
    assert db.scalar(text("SELECT count(*) FROM leads")) == 1


def test_review_telegram_text_has_no_personal_data(client, db, tg):
    r = client.post("/api/v1/reviews", json={
        "name": NAME + " Королёва", "phone": "+7 (916) 555-12-34", "city": "Новосибирск", "breed": "maltipu",
        "rating": 4,
        "text": "Взяли у вас мальтипу, звоните мне +7 999 123-45-67, щенок весёлый.",
        "consent": True, "consent_version": CONSENT_CURRENT["review"],
        "consent_publish": True, "consent_publish_version": CONSENT_CURRENT["distribution"],
        "page": {"path": "/otzyvy/", "title": "Отзывы"}, "idempotency_key": str(uuid.uuid4()),
        "hp_note": "", "elapsed_ms": 40_000})
    assert r.status_code == 201, r.text
    rows = outbox(db)
    assert [(o.channel, o.event) for o in rows] == [("telegram", "review.created")]
    fake = FakeHttp()
    assert notify.deliver_due(db, client=fake.client())["sent"] == 1
    payload = fake.json()
    assert payload["parse_mode"] == "HTML"
    assert payload["text"].startswith(f"⭐ <b>Новый отзыв №{rows[0].review_id}</b> · ★★★★")
    raw = fake.requests[0].content.decode()
    for pd in (NAME, "Королёва", "Новосибирск", "999", "916", "звоните"):
        assert pd not in raw, pd


# ---------------------------------------------------------------- erased people
def test_pending_notification_of_an_anonymised_lead_fails_without_sending(client, db, tg, email):
    lead_id, _ = post_lead(client)
    assert len(outbox(db)) == 2
    db.execute(text("UPDATE leads SET anonymised_at = now(), name = NULL, phone = NULL WHERE id = :i"),
               {"i": lead_id})
    db.commit()
    fake = FakeHttp()
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 0, "failed": 2, "retry": 0}
    assert fake.requests == [] and email.sent == []
    assert all(o.status == "failed" and "erased" in o.last_error for o in outbox(db))


def test_erasing_a_contact_deletes_its_pending_notifications(client, db, tg, admin_h):
    lead_id, _ = post_lead(client)
    contact_id = db.scalar(select(Lead.contact_id).where(Lead.id == lead_id))
    r = client.post(f"/api/v1/admin/contacts/{contact_id}/erase", headers=admin_h,
                    json={"reason": "withdrawal", "subject": NAME})
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["notifications_deleted"] == 1
    fake = FakeHttp()
    notify.deliver_due(db, client=fake.client())
    assert fake.requests == [] and outbox(db) == []


# ---------------------------------------------------------------- health
def _outbox_row(db, status: str, age: dt.timedelta) -> None:
    lead_id = db.scalar(select(Lead.id).limit(1))
    db.execute(text("INSERT INTO outbox (channel, target, event, lead_id, status, created_at, next_attempt_at) "
                    "VALUES ('webhook', 'https://x.example/h', 'lead.updated', :l, :s, now() - :a, now())"),
               {"l": lead_id, "s": status, "a": age})
    db.commit()


def test_health_ok(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json() == {"ok": True}


@pytest.mark.parametrize("status, age, healthy", [
    ("pending", dt.timedelta(minutes=5), True),
    ("pending", dt.timedelta(minutes=11), False),
    ("failed", dt.timedelta(hours=2), False),
    ("failed", dt.timedelta(days=2), True),
    ("sent", dt.timedelta(hours=2), True),
])
def test_public_health_reflects_the_outbox(client, db, status, age, healthy):
    post_lead(client)
    _outbox_row(db, status, age)
    r = client.get("/api/v1/health")
    if healthy:
        assert (r.status_code, r.json()) == (200, {"ok": True})
    else:
        assert (r.status_code, r.json()) == (503, {"ok": False})  # no details for the public


def test_admin_health_lists_the_problems(client, db, manager_h):
    post_lead(client)
    assert client.get("/api/v1/admin/health", headers=manager_h).json() == {"problems": []}
    _outbox_row(db, "pending", dt.timedelta(minutes=30))
    _outbox_row(db, "failed", dt.timedelta(hours=1))
    _outbox_row(db, "failed", dt.timedelta(hours=3))
    r = client.get("/api/v1/admin/health", headers=manager_h)
    assert r.status_code == 200
    problems = r.json()["problems"]
    assert len(problems) == 2
    assert any("stuck" in p for p in problems)
    assert any(p.startswith("2 notification(s) failed") for p in problems)
    assert client.get("/api/v1/admin/health").status_code == 401


def test_health_names_the_deployed_release(client, settings):
    settings.release = "20261020-090000-abcdef12"
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json() == {"ok": True, "release": "20261020-090000-abcdef12"}


# ---------------------------------------------------------------- python -m app notify-test
def test_notify_test_sends_one_message_per_chat_and_mailbox_without_personal_data(tg, email):
    tg.telegram_breed_chats = {"maltipu": MALTIPU_CHAT, "pudel": DEFAULT_CHAT}   # a repeated chat is checked once
    fake = FakeHttp()
    res = notify.send_test(tg, client=fake.client())
    assert [(r["channel"], r["target"], r["ok"]) for r in res] == [
        ("telegram", DEFAULT_CHAT, True), ("telegram", MALTIPU_CHAT, True), ("email", "owner@yandex.ru", True)]
    assert [fake.json(i)["chat_id"] for i in range(2)] == [DEFAULT_CHAT, MALTIPU_CHAT]
    assert "Проверка" in fake.json(0)["text"] and NAME not in fake.json(0)["text"]
    assert FakeSMTP.logins == [("kennel@yandex.ru", SMTP_PASSWORD)]
    (msg,) = FakeSMTP.sent
    assert msg["To"] == "owner@yandex.ru" and "Проверка" in msg["Subject"]


def test_notify_test_explains_what_to_fix_and_never_shows_the_token(tg, email):
    fake = FakeHttp(httpx.Response(400, json={"ok": False, "description": f"Bad Request: chat not found {TOKEN}"}))
    FakeSMTP.login_error = smtplib.SMTPAuthenticationError(535, b"auth failed")
    res = notify.send_test(tg, client=fake.client())
    t, e = res
    assert not t["ok"] and "/start" in t["hint"] and TOKEN not in t["error"]
    assert not e["ok"] and "DSH_SMTP_PASSWORD" in e["hint"] and SMTP_PASSWORD not in e["error"]


@pytest.mark.parametrize("answer, words", [
    (httpx.Response(401, json={"ok": False, "description": "Unauthorized"}), "DSH_TELEGRAM_BOT_TOKEN"),
    (httpx.Response(403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"}), "заблокирован"),
    (httpx.ConnectError("no route"), "api.telegram.org"),
])
def test_notify_test_telegram_hints(tg, answer, words):
    (r,) = notify.send_test(tg, client=FakeHttp(answer).client())
    assert not r["ok"] and words in r["hint"]


def test_notify_test_points_to_the_closed_port_of_the_provider(email, settings):
    FakeSMTP.connect_error = TimeoutError("timed out")
    (r,) = notify.send_test(settings, client=FakeHttp().client())
    assert not r["ok"] and "465" in r["hint"] and "Timeweb" in r["hint"]


def test_notify_test_reports_a_half_filled_channel_and_nothing_when_none(settings):
    settings.telegram_bot_token, settings.telegram_chat_id, settings.telegram_breed_chats = TOKEN, "", {}
    settings.smtp_host, settings.notify_emails = "", []
    (r,) = notify.send_test(settings, client=FakeHttp().client())
    assert not r["ok"] and "DSH_TELEGRAM_CHAT_ID" in r["hint"]
    settings.telegram_bot_token = ""
    assert notify.send_test(settings, client=FakeHttp().client()) == []


def test_notify_test_command_exit_codes(monkeypatch, capsys):
    from app.__main__ import main
    monkeypatch.setattr(notify, "send_test", lambda: [])
    assert main(["notify-test"]) == 2
    monkeypatch.setattr(notify, "send_test", lambda: [{"channel": "telegram", "target": "1", "ok": True, "error": "", "hint": ""}])
    assert main(["notify-test"]) == 0 and "dsh restart" in capsys.readouterr().out
    monkeypatch.setattr(notify, "send_test", lambda: [{"channel": "email", "target": "a@b.ru", "ok": False,
                                                        "error": "x", "hint": "почта не приняла"}])
    assert main(["notify-test"]) == 1 and "FAIL  почта → a@b.ru: почта не приняла" in capsys.readouterr().out


# ---------------------------------------------------------------- the look of the Telegram message
def test_telegram_message_tells_where_the_visitor_came_from(client, db, tg):
    tg.admin_base_url = "https://admin.example/#/leads?lead={id}"
    lead_id, _ = post_lead(client, referrer="https://yandex.ru/search/?text=мальтипу", landing="/maltipu/",
                           page={"path": "/toj-pudel/", "title": "Той-пудель"}, note="Заявка: меню",
                           utm={"utm_campaign": "osen"})
    fake = FakeHttp()
    notify.deliver_due(db, client=fake.client())
    msg = fake.json()["text"]
    assert "🖱 Кнопка: Заявка: меню" in msg
    assert "• Вошёл на: /maltipu/" in msg and "• Заявка со страницы: /toj-pudel/" in msg
    assert "• Кампания: osen" in msg
    assert f'<a href="https://admin.example/#/leads?lead={lead_id}">Открыть заявку в админке</a>' in msg


def test_telegram_message_escapes_what_the_page_sent(client, db, tg):
    post_lead(client, note='<b>x</b> & "y"')
    fake = FakeHttp()
    notify.deliver_due(db, client=fake.client())
    msg = fake.json()["text"]
    assert "🖱 Кнопка: &lt;b&gt;x&lt;/b&gt; &amp; \"y\"" in msg and "<b>x</b>" not in msg


def test_a_markup_error_falls_back_to_plain_text_and_keeps_the_link(client, db, tg):
    tg.admin_base_url = "https://admin.example/leads/{id}"
    lead_id, _ = post_lead(client, note="a & b")
    fake = FakeHttp(httpx.Response(400, json={"ok": False, "description": "Bad Request: can't parse entities: x"}))
    assert notify.deliver_due(db, client=fake.client())["sent"] == 1
    first, second = fake.json(0), fake.json(1)
    assert first["parse_mode"] == "HTML" and "parse_mode" not in second
    assert "<b>" not in second["text"] and "Кнопка: a & b" in second["text"]
    assert f"Открыть заявку в админке: https://admin.example/leads/{lead_id}" in second["text"]


@pytest.mark.parametrize("source, medium, words", [
    ("yandex", "organic", "🔍 поиск — Яндекс"), ("google", "cpc", "💰 реклама — Google Ads"),
    ("vk", "social", "💬 соцсеть — ВКонтакте"), ("petbook.ru", "referral", "🔗 переход с сайта petbook.ru"),
    ("(direct)", "(none)", "✍️ прямой заход"), ("partner", "email", "🏷 метка — partner / email"),
])
def test_source_label(source, medium, words):
    assert notify.source_label(source, medium) == words


def test_telegram_message_counts_pages_and_shows_the_device_and_metrika_id(client, db, tg):
    visitor, session = str(uuid.uuid4()), str(uuid.uuid4())
    now_ms = int(dt.datetime.now(UTC).timestamp() * 1000)
    r = client.post("/api/v1/events", json={
        "visitor_id": visitor, "session_id": session, "landing": "/", "ym_uid": "1791982828848951532",
        "events": [{"type": "page_view", "path": p, "ts": now_ms - 60_000 + i} for i, p in enumerate(("/", "/maltipu/", "/toj-pudel/"))]},
        headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) Mobile/15E148"})
    assert r.status_code == 202, r.text
    post_lead(client, visitor_id=visitor, session_id=session)
    fake = FakeHttp()
    notify.deliver_due(db, client=fake.client())
    msg = fake.json()["text"]
    assert "📄 Посмотрел страниц до заявки: 3" in msg
    assert "🖥 Устройство: 📱 телефон" in msg
    assert "🆔 Метрика ClientID: 1791982828848951532" in msg


def test_notify_retry_sends_again_what_failed_and_what_waits(client, db, tg):
    post_lead(client, kind="price")
    post_lead(client, kind="video_call", phone="+7 (999) 222-33-44")
    fake = FakeHttp(httpx.Response(403, json={"ok": False, "description": "Forbidden"}),
                    httpx.Response(500, json={"ok": False, "description": "oops"}))
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 0, "failed": 1, "retry": 1}
    assert sorted(o.status for o in outbox(db)) == ["failed", "pending"]
    fake = FakeHttp()                                   # the cause is fixed: everything goes out at once
    r = notify.retry_now(db, client=fake.client())
    assert r == {"revived": 1, "sent": 2, "failed": 0, "retry": 0}
    assert [o.status for o in outbox(db)] == ["sent", "sent"] and len(fake.requests) == 2
