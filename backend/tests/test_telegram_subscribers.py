"""Requests in the private chat with the bot. notify.telegram_poll: a member of the requests group presses «Старт»
and from then on gets every request there too; a stranger is refused; /stop ends it. notify.telegram_admins_refresh:
the group's admins get them without «Старт» being read (another service may take the bot's messages). No network:
a tiny Bot API."""
from __future__ import annotations

import json

import httpx
import pytest

from app.services import notify
from test_notify import DEFAULT_CHAT, TOKEN, FakeHttp, no_network, outbox, post_lead, tg  # noqa: F401 — fixtures

GROUP = DEFAULT_CHAT
MEMBER, STRANGER = 555, 777


class Bot:
    """getUpdates (what is queued), getChatMember (MEMBER is in GROUP), getMe, sendMessage (recorded)."""

    def __init__(self, updates=(), down=False, admins=(), started=(), webhook=""):
        self.updates = list(updates)
        self.down = down
        self.admins = list(admins)          # [(id, name, is_bot)]
        self.started = set(started)         # ids that pressed «Старт»: the bot may write to them
        self.webhook = webhook              # set → getUpdates answers 409, like with amoCRM chats connected
        self.sent: list[dict] = []
        self.member_checks = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("[Errno 101] Network is unreachable")
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content or b"{}")
        if method == "getUpdates":
            if self.webhook:
                return httpx.Response(409, json={"ok": False, "error_code": 409, "description":
                                                 "Conflict: can't use getUpdates method while webhook is active"})
            return httpx.Response(200, json={"ok": True, "result": self.updates})
        if method == "getWebhookInfo":
            return httpx.Response(200, json={"ok": True, "result": {"url": self.webhook}})
        if method == "getChatAdministrators":
            return httpx.Response(200, json={"ok": True, "result": [
                {"status": "creator" if i == 0 else "administrator", "user": {"id": uid, "first_name": n, "is_bot": b}}
                for i, (uid, n, b) in enumerate(self.admins)]})
        if method == "getChatMember":
            self.member_checks += 1
            status = "member" if (str(body["chat_id"]), body["user_id"]) == (GROUP, MEMBER) else "left"
            return httpx.Response(200, json={"ok": True, "result": {"status": status}})
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"username": "dom_shenkov_bot", "first_name": "Дом"}})
        if method == "sendMessage":
            if not str(body["chat_id"]).startswith("-") and self.started and int(body["chat_id"]) not in self.started:
                return httpx.Response(403, json={"ok": False, "error_code": 403,
                                                 "description": "Forbidden: bot can't initiate conversation with a user"})
            self.sent.append(body)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        return httpx.Response(404, json={"ok": False, "description": "Not Found"})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def msg(update_id: int, user: int, text: str, chat_type: str = "private", chat_id: int | None = None) -> dict:
    return {"update_id": update_id, "message": {"chat": {"id": chat_id or user, "type": chat_type},
                                                "from": {"id": user, "first_name": "Анна"}, "text": text}}


@pytest.fixture
def subs(tg, tmp_path):
    tg.telegram_chat_id = GROUP
    tg.telegram_subscribers_file = str(tmp_path / "telegram_subscribers.json")
    return tg


def test_a_group_member_who_pressed_start_gets_every_request(client, db, subs):
    bot = Bot([msg(10, MEMBER, "/start")])
    assert notify.telegram_poll(subs, bot.client()) == {"added": 1, "removed": 0, "refused": 0}
    assert bot.sent == [{"chat_id": str(MEMBER), "text": notify.SUBSCRIBED}]
    assert list(notify.subscribers(subs)["chats"]) == [str(MEMBER)]

    post_lead(client, breed="maltipu")
    assert sorted(o.target for o in outbox(db)) == sorted([GROUP, str(MEMBER)])  # the group and the private chat
    fake = FakeHttp()
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 2, "failed": 0, "retry": 0}


def test_the_same_updates_are_handled_once(subs):
    bot = Bot([msg(10, MEMBER, "/start")])
    notify.telegram_poll(subs, bot.client())
    notify.telegram_poll(subs, bot.client())       # Telegram keeps returning the update for 24 h
    assert len(bot.sent) == 1 and bot.member_checks == 1


def test_a_stranger_is_refused_and_gets_nothing(client, db, subs):
    bot = Bot([msg(11, STRANGER, "/start")])
    assert notify.telegram_poll(subs, bot.client())["refused"] == 1
    assert bot.sent[0]["text"] == notify.NOT_MEMBER and notify.subscribers(subs)["chats"] == {}
    post_lead(client)
    assert [o.target for o in outbox(db)] == [GROUP]


def test_stop_ends_it_and_start_again_says_already(subs):
    bot = Bot([msg(10, MEMBER, "/start"), msg(11, MEMBER, "/start"), msg(12, MEMBER, "/stop")])
    assert notify.telegram_poll(subs, bot.client()) == {"added": 1, "removed": 1, "refused": 0}
    assert [m["text"] for m in bot.sent] == [notify.SUBSCRIBED, notify.ALREADY, notify.UNSUBSCRIBED]
    assert notify.subscribers(subs)["chats"] == {}


def test_group_messages_and_other_text_are_ignored(subs):
    bot = Bot([msg(10, MEMBER, "/start", chat_type="supergroup", chat_id=int(GROUP)), msg(11, MEMBER, "привет")])
    assert notify.telegram_poll(subs, bot.client()) == {"added": 0, "removed": 0, "refused": 0}
    assert bot.sent == [] and notify.subscribers(subs)["last_update"] == 11


def test_without_a_group_nobody_can_subscribe(subs):
    subs.telegram_chat_id = "123456"   # only a private chat configured: membership cannot be checked
    bot = Bot([msg(10, MEMBER, "/start")])
    assert notify.telegram_poll(subs, bot.client())["refused"] == 1
    assert bot.sent[0]["text"] == notify.NO_GROUP


def test_telegram_unreachable_changes_nothing(subs, monkeypatch):
    monkeypatch.setattr(notify, "httpx", httpx)  # the real exception classes (no_network stubs the module)
    assert notify.telegram_poll(subs, Bot(down=True).client()) == {"added": 0, "removed": 0, "refused": 0}
    assert notify.subscribers(subs) == {"last_update": 0, "chats": {}, "waiting": {}, "stopped": []}


def test_a_broken_file_reads_as_empty_and_requests_still_go(client, db, subs):
    with open(subs.telegram_subscribers_file, "w") as f:
        f.write("{not json")
    post_lead(client)
    assert [o.target for o in outbox(db)] == [GROUP]


def test_hello_names_the_bot_in_every_configured_chat(subs):
    bot = Bot()
    res = notify.telegram_hello(subs, bot.client())
    assert res == [{"chat": GROUP, "ok": True, "error": ""}]
    assert "@dom_shenkov_bot" in bot.sent[0]["text"] and "«Старт»" in bot.sent[0]["text"]
    assert TOKEN not in json.dumps(bot.sent)


# ---------------------------------------------------------------- the group's admins (no «Старт» needs to be read)
ADMIN, ADMIN2, BOT_ID = 555, 888, 999


def test_admins_who_pressed_start_get_requests_even_when_another_service_takes_the_messages(client, db, subs):
    bot = Bot(webhook="https://amojo.amocrm.ru/hook", admins=[(ADMIN, "Владимир", False), (ADMIN2, "Ольга", False),
                                                               (BOT_ID, "Дом", True)], started={ADMIN})
    assert notify.telegram_admins_refresh(subs, bot.client()) == {"added": 1, "removed": 0, "waiting": 1}
    assert bot.sent == [{"chat_id": str(ADMIN), "text": notify.ADMIN_WELCOME}]   # Ольга has not pressed «Старт»
    data = notify.subscribers(subs)
    assert list(data["chats"]) == [str(ADMIN)] and data["waiting"] == {str(ADMIN2): "Ольга"}

    post_lead(client)
    assert sorted(o.target for o in outbox(db)) == sorted([GROUP, str(ADMIN)])

    bot.started.add(ADMIN2)                                     # Ольга pressed «Старт»: the next refresh adds her
    assert notify.telegram_admins_refresh(subs, bot.client())["added"] == 1
    assert notify.telegram_admins_refresh(subs, bot.client()) == {"added": 0, "removed": 0, "waiting": 0}  # once


def test_former_admins_and_stopped_ones_are_not_written_to(subs):
    bot = Bot(admins=[(ADMIN, "Владимир", False)], updates=[msg(10, ADMIN, "/stop")])
    notify.telegram_poll(subs, bot.client())                     # /stop before the refresh
    assert notify.telegram_admins_refresh(subs, bot.client())["added"] == 0
    bot.updates.append(msg(11, ADMIN, "/start"))                 # changed his mind
    notify.telegram_poll(subs, bot.client())
    assert str(ADMIN) in notify.subscribers(subs)["chats"]
    data = notify.subscribers(subs)
    data["chats"][str(ADMIN)]["via"] = "admin"
    notify._save_subscribers(subs, data)
    bot.admins = []                                              # no longer an admin
    assert notify.telegram_admins_refresh(subs, bot.client())["removed"] == 1
    assert notify.subscribers(subs)["chats"] == {}


def test_a_taken_bot_is_reported_in_the_group_once_a_day(subs):
    bot = Bot(webhook="https://amojo.amocrm.ru/hook")
    notify.telegram_poll(subs, bot.client())
    notify.telegram_poll(subs, bot.client())
    warnings = [m for m in bot.sent if m["chat_id"] == GROUP]
    assert len(warnings) == 1 and "amojo.amocrm.ru" in warnings[0]["text"] and "«Старт»" in warnings[0]["text"]
