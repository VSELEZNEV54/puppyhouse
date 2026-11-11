"""Requests in the private chat with the bot (notify.telegram_poll): a member of the requests group presses «Старт»
and from then on gets every request there too; a stranger is refused; /stop ends it. No network: a tiny Bot API."""
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

    def __init__(self, updates=(), down=False):
        self.updates = list(updates)
        self.down = down
        self.sent: list[dict] = []
        self.member_checks = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("[Errno 101] Network is unreachable")
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content or b"{}")
        if method == "getUpdates":
            return httpx.Response(200, json={"ok": True, "result": self.updates})
        if method == "getChatMember":
            self.member_checks += 1
            status = "member" if (str(body["chat_id"]), body["user_id"]) == (GROUP, MEMBER) else "left"
            return httpx.Response(200, json={"ok": True, "result": {"status": status}})
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"username": "dom_shenkov_bot", "first_name": "Дом"}})
        if method == "sendMessage":
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
    assert notify.subscribers(subs) == {"last_update": 0, "chats": {}}


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
