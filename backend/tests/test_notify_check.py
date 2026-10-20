"""`python -m app notify-check`: the launch check of the notification channels (app/services/notify.py → setup checks).

What matters when the owner sends the bot token and the mailbox:
- a wrong token or a chat the bot is not in is reported in plain words, and the exit code is 1;
- the chat ids the bot sees are listed, so the owner can pick the group's id without extra tools;
- --send really sends one test message per chat and one test letter per recipient;
- the token and the SMTP password never appear in the output.
No network: Telegram goes through httpx.MockTransport, SMTP is a fake class (test_notify.py).
"""
from __future__ import annotations

import json
import smtplib
from types import SimpleNamespace

import httpx
import pytest

from app.__main__ import main
from app.services import notify
from test_notify import DEFAULT_CHAT, MALTIPU_CHAT, SMTP_PASSWORD, TOKEN, FakeSMTP

API = "https://tg-stub.example"


class FakeBot:
    """A tiny Bot API: getMe, getUpdates, getChat, sendMessage. Chats in `known` are the ones the bot is in."""

    def __init__(self, token_ok=True, known=(DEFAULT_CHAT,), updates=None):
        self.token_ok = token_ok
        self.known = set(known)
        self.updates = updates if updates is not None else []
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(API + "/bot"), request.url
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content or b"{}")
        self.calls.append((method, body))
        if not self.token_ok:
            return httpx.Response(401, json={"ok": False, "error_code": 401, "description": "Unauthorized"})
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"id": 7012345678, "is_bot": True,
                                                                     "first_name": "Дом щенков", "username": "dsh_leads_bot"}})
        if method == "getUpdates":
            return httpx.Response(200, json={"ok": True, "result": self.updates})
        if method in ("getChat", "sendMessage"):
            if str(body.get("chat_id")) not in self.known:
                return httpx.Response(400, json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})
            if method == "getChat":
                return httpx.Response(200, json={"ok": True, "result": {"id": int(body["chat_id"]), "type": "supergroup",
                                                                         "title": "Заявки домщенков.рф"}})
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        return httpx.Response(404, json={"ok": False, "description": "Not Found"})

    def sent(self) -> list[dict]:
        return [b for m, b in self.calls if m == "sendMessage"]


@pytest.fixture
def channels(settings, monkeypatch):
    """Every channel off; the test turns on what it needs. Telegram goes to the stub."""
    for k, v in dict(telegram_bot_token="", telegram_chat_id="", telegram_breed_chats={}, telegram_include_pd=False,
                     telegram_api_base=API, smtp_host="", smtp_user="", smtp_password="", smtp_from="",
                     notify_emails=[], webhook_url="").items():
        monkeypatch.setattr(settings, k, v)
    return settings


def use_bot(monkeypatch, bot: FakeBot) -> FakeBot:
    monkeypatch.setattr(notify, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(bot)))
    return bot


def use_smtp(monkeypatch, settings):
    settings.smtp_host, settings.smtp_port, settings.smtp_ssl = "smtp.yandex.ru", 465, True
    settings.smtp_user = settings.smtp_from = "kennel@yandex.ru"
    settings.smtp_password = SMTP_PASSWORD
    settings.notify_emails = ["owner@yandex.ru", "manager@yandex.ru"]
    FakeSMTP.sent, FakeSMTP.logins, FakeSMTP.connects = [], [], []
    FakeSMTP.login_error = FakeSMTP.connect_error = None
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)


def run(capsys, *argv) -> tuple[int, str]:
    code = main(["notify-check", *argv])
    out = capsys.readouterr().out
    assert TOKEN not in out and TOKEN.split(":", 1)[1] not in out, "the bot token leaked into the output"
    assert SMTP_PASSWORD not in out
    return code, out


def test_nothing_configured_says_so_and_fails(channels, capsys):
    code, out = run(capsys)
    assert code == 1
    assert "не настроен" in out and "Ни один канал не настроен" in out


def test_good_bot_lists_chats_and_checks_the_configured_one(channels, monkeypatch, capsys):
    channels.telegram_bot_token, channels.telegram_chat_id = TOKEN, DEFAULT_CHAT
    bot = use_bot(monkeypatch, FakeBot(updates=[
        {"update_id": 1, "my_chat_member": {"chat": {"id": int(DEFAULT_CHAT), "type": "supergroup", "title": "Заявки домщенков.рф"}}},
        {"update_id": 2, "message": {"chat": {"id": 555, "type": "private", "first_name": "Анна"}, "text": "/start"}},
        {"update_id": 3, "message": {"chat": {"id": int(DEFAULT_CHAT), "type": "supergroup", "title": "Заявки домщенков.рф"}}},
    ]))
    code, out = run(capsys)
    assert code == 0, out
    assert "@dsh_leads_bot" in out and "7012345678:***" in out
    assert out.count(DEFAULT_CHAT) >= 2 and "555  private  Анна" in out  # listed once per chat + the check line
    assert "✓ общий чат" in out and "Итог: всё в порядке" in out
    assert bot.sent() == []  # without --send nothing is posted
    assert "нет — номер заявки" in out  # personal data stays out of Telegram by default


def test_send_posts_one_test_message_per_chat(channels, monkeypatch, capsys):
    channels.telegram_bot_token, channels.telegram_chat_id = TOKEN, DEFAULT_CHAT
    channels.telegram_breed_chats = {"maltipu": MALTIPU_CHAT}
    bot = use_bot(monkeypatch, FakeBot(known=(DEFAULT_CHAT, MALTIPU_CHAT)))
    code, out = run(capsys, "--send")
    assert code == 0, out
    assert sorted(m["chat_id"] for m in bot.sent()) == sorted([DEFAULT_CHAT, MALTIPU_CHAT])
    assert all(m["text"] == notify.TEST_TEXT for m in bot.sent())
    assert out.count("тестовое сообщение отправлено") == 2


def test_wrong_token_is_reported_without_leaking_it(channels, monkeypatch, capsys):
    channels.telegram_bot_token, channels.telegram_chat_id = TOKEN, DEFAULT_CHAT
    use_bot(monkeypatch, FakeBot(token_ok=False))
    code, out = run(capsys)
    assert code == 1
    assert "не принят" in out and "Unauthorized" in out


def test_no_connection_is_not_reported_as_a_wrong_token(channels, monkeypatch, capsys):
    """A server that cannot reach Telegram must not send the owner off to recreate a good token."""
    channels.telegram_bot_token, channels.telegram_chat_id = TOKEN, DEFAULT_CHAT

    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(notify, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(refuse)))
    code, out = run(capsys)
    assert code == 1
    assert "нет связи с Telegram" in out and "токен не проверен" in out and "не принят" not in out


def test_chat_the_bot_is_not_in_fails(channels, monkeypatch, capsys):
    channels.telegram_bot_token, channels.telegram_chat_id = TOKEN, "-1009999999999"
    use_bot(monkeypatch, FakeBot(known=(DEFAULT_CHAT,)))
    code, out = run(capsys, "--send")
    assert code == 1
    assert "chat not found" in out and "бот добавлен в этот чат?" in out


def test_token_without_chat_lists_chats_and_asks_for_the_id(channels, monkeypatch, capsys):
    channels.telegram_bot_token = TOKEN
    use_bot(monkeypatch, FakeBot(updates=[]))
    code, out = run(capsys)
    assert code == 1
    assert "чатов пока не видно" in out and "/start@dsh_leads_bot" in out and "DSH_TELEGRAM_CHAT_ID" in out


def test_mail_login_and_test_letters(channels, monkeypatch, capsys):
    use_smtp(monkeypatch, channels)
    code, out = run(capsys, "--send")
    assert code == 0, out
    assert FakeSMTP.logins == [("kennel@yandex.ru", SMTP_PASSWORD)]
    assert sorted(m["To"] for m in FakeSMTP.sent) == ["manager@yandex.ru", "owner@yandex.ru"]
    assert all(m["Subject"] == "Проверка уведомлений домщенков.рф" for m in FakeSMTP.sent)
    assert "тестовое письмо отправлено" in out


def test_mail_without_send_only_logs_in(channels, monkeypatch, capsys):
    use_smtp(monkeypatch, channels)
    code, out = run(capsys)
    assert code == 0, out
    assert FakeSMTP.logins and FakeSMTP.sent == []


def test_mail_wrong_password_fails_without_leaking_it(channels, monkeypatch, capsys):
    use_smtp(monkeypatch, channels)
    FakeSMTP.login_error = smtplib.SMTPAuthenticationError(535, b"Invalid user or password " + SMTP_PASSWORD.encode())
    code, out = run(capsys, "--send")
    assert code == 1
    assert "SMTPAuthenticationError" in out and FakeSMTP.sent == []


def test_real_delivery_uses_the_configured_api_base(channels):
    """The lead notifications (not only the check) go to telegram_api_base."""
    channels.telegram_bot_token = TOKEN
    seen = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: (seen.append(str(r.url)), httpx.Response(200, json={"ok": True}))[1]))
    notify._send_telegram(SimpleNamespace(target=DEFAULT_CHAT), "текст", channels, client)
    assert seen == [f"{API}/bot{TOKEN}/sendMessage"]
