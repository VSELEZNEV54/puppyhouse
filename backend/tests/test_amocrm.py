"""Requests from the site → amoCRM (app/services/notify.py, channel «amocrm») and its launch check (notify-check).

What matters for the kennel:
- every request lands in amoCRM as a deal in the configured pipeline and stage, with the contact (name, phone) and a
  note carrying the whole request; a contact with the same number is reused, never a stranger's one;
- a repeat request of the same person is a note in the deal of the first request, not a second deal;
- a failure half-way (no answer, 5xx on the note) never makes a second deal on the retry;
- 401 (the token revoked or expired) fails at once and the token never reaches the database, the logs or the output;
- reviews, spam and erased people never go to amoCRM.
No network: amoCRM is a stub behind httpx.MockTransport.
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select, text

from app.__main__ import main
from app.api import public
from app.config import Settings
from app.models import Lead
from app.services import notify
from conftest import CONSENT_CURRENT
from test_notify import NAME, PHONE_E164, PHONE_FORM, make_due, outbox, post_lead

UTC = dt.timezone.utc
API = "https://amo-stub.example"
# a long-lived token is a JWT; this one is made up
AMO_TOKEN = ("eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsImp0aSI6InRlc3QifQ.eyJhdWQiOiJ0ZXN0LWludGVncmF0aW9uIiwic2NvcGVzIjpb"
             "ImNybSJdfQ.U0VDUkVULXNpZ25hdHVyZS1vZi10aGUtdGVzdC10b2tlbg")
PIPELINE, STAGE = 7001, 61001
OTHER_PIPELINE, OTHER_STAGE = 7002, 62001


class FakeAmo:
    """A tiny amoCRM API v4: contacts search, leads/complex, notes, leads search, account, pipelines.
    `contacts` — what the contact search finds. `fail` — {"POST leads/complex": [answers]}: queued answers served
    before the normal one (an httpx.Response, an exception, a function of the request, or "lost": the deal is made
    but the answer never comes)."""

    def __init__(self, contacts=(), fail=None):
        self.contacts = list(contacts)
        self.fail = {k: list(v) for k, v in (fail or {}).items()}
        self.deals: list[dict] = []
        self.calls: list[SimpleNamespace] = []
        self.next_deal, self.next_contact = 5001, 9001

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(API + "/api/v4/"), request.url
        path = request.url.path.removeprefix("/api/v4/")
        key = "POST notes" if path.endswith("/notes") else f"{request.method} {path}"
        self.calls.append(SimpleNamespace(key=key, path=path, params=dict(request.url.params),
                                          body=json.loads(request.content) if request.content else None,
                                          auth=request.headers.get("authorization")))
        queued = self.fail.get(key)
        if queued:
            r = queued.pop(0)
            if isinstance(r, Exception):
                raise r
            if callable(r):
                return r(request)
            if r == "lost":
                self.answer(request, key, path)
                raise httpx.ReadTimeout("The read operation timed out", request=request)
            return r
        return self.answer(request, key, path)

    def answer(self, request, key, path) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        if key == "GET contacts":
            return httpx.Response(200, json={"_embedded": {"contacts": self.contacts}}) if self.contacts \
                else httpx.Response(204)
        if key == "POST leads/complex":
            contact = body[0]["_embedded"]["contacts"][0]
            contact_id = contact.get("id")
            if contact_id is None:
                contact_id, self.next_contact = self.next_contact, self.next_contact + 1
            deal = {"id": self.next_deal, "name": body[0]["name"], "_embedded": {"contacts": [{"id": contact_id}]}}
            self.next_deal += 1
            self.deals.append(deal)
            return httpx.Response(200, json=[{"id": deal["id"], "contact_id": contact_id, "company_id": None,
                                              "request_id": ["0"], "merged": False}])
        if key == "GET leads":
            found = [d for d in self.deals if request.url.params["query"] in d["name"]]
            return httpx.Response(200, json={"_embedded": {"leads": found}}) if found else httpx.Response(204)
        if key == "POST notes":
            return httpx.Response(200, json={"_embedded": {"notes": [{"id": 1, "entity_id": int(path.split("/")[1])}]}})
        if key == "GET account":
            return httpx.Response(200, json={"id": 31000001, "name": "Питомник Дом щенков", "subdomain": "monnypassy"})
        if key == "GET leads/pipelines":
            return httpx.Response(200, json={"_embedded": {"pipelines": [
                {"id": PIPELINE, "name": "Продажи щенков", "is_main": True, "_embedded": {"statuses": [
                    {"id": 60000, "name": "Неразобранное", "type": 1}, {"id": STAGE, "name": "Новая заявка", "type": 0},
                    {"id": 142, "name": "Успешно реализовано", "type": 0},
                    {"id": 143, "name": "Закрыто и не реализовано", "type": 0}]}},
                {"id": OTHER_PIPELINE, "name": "Стартовые наборы", "is_main": False, "_embedded": {"statuses": [
                    {"id": OTHER_STAGE, "name": "Первичный контакт", "type": 0}]}}]}})
        return httpx.Response(404, json={"title": "Not Found", "status": 404})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def keys(self) -> list[str]:
        return [c.key for c in self.calls]

    def of(self, key: str) -> list[SimpleNamespace]:
        return [c for c in self.calls if c.key == key]

    def note(self, i: int = -1) -> str:
        return self.of("POST notes")[i].body[0]["params"]["text"]


def assert_no_token(*texts: str) -> None:
    for t in texts:
        for part in [AMO_TOKEN, *AMO_TOKEN.split("."), AMO_TOKEN[:30]]:
            assert part not in t, "the amoCRM token leaked"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No real HTTP: the immediate delivery after the response is recorded, a real httpx.Client is forbidden."""
    calls: list[int] = []
    monkeypatch.setattr(public, "_deliver_now", lambda: calls.append(1))

    def _no_real_client(*a, **kw):
        raise AssertionError("a real httpx.Client was created in a test")
    monkeypatch.setattr(notify, "httpx", SimpleNamespace(Client=_no_real_client, HTTPError=httpx.HTTPError))
    return calls


@pytest.fixture
def amo(settings):
    settings.amocrm_subdomain = "monnypassy"
    settings.amocrm_token = AMO_TOKEN
    settings.amocrm_api_base = API
    settings.amocrm_pipeline_id, settings.amocrm_status_id = PIPELINE, STAGE
    settings.amocrm_responsible_user_id = None
    settings.amocrm_tags = ["сайт"]
    settings.admin_base_url = ""
    return settings


def amo_state(db, lead_id: int) -> dict | None:
    db.expire_all()
    return (db.scalar(select(Lead.details).where(Lead.id == lead_id)) or {}).get("amocrm")


# ---------------------------------------------------------------- a new request
def test_new_request_becomes_a_deal_with_the_contact_and_a_note(client, db, amo, no_network):
    amo.admin_base_url = "https://admin.example/leads/{id}"
    lead_id, _ = post_lead(client, breed="maltipu", kind="price", contact="whatsapp", colour="kremovyj",
                           question="Сколько гуляет мальтипу?", note="Заявка: меню", form_title="Узнать цену",
                           referrer="https://yandex.ru/search/?text=мальтипу", utm={"utm_campaign": "osen"},
                           quiz={"winner": "maltipu", "second": "toj-pudel"})
    assert [(o.channel, o.target, o.event, o.lead_id) for o in outbox(db)] == \
        [("amocrm", "monnypassy", "lead.created", lead_id)]
    assert no_network == [1]

    fake = FakeAmo()
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 1, "failed": 0, "retry": 0}
    assert fake.keys() == ["GET contacts", "POST leads/complex", "POST notes"]
    assert all(c.auth == f"Bearer {AMO_TOKEN}" for c in fake.calls)
    assert fake.calls[0].params == {"query": PHONE_E164.lstrip("+"), "with": "leads"}
    (deal,) = fake.calls[1].body
    assert deal == {
        "name": f"Заявка с сайта №{lead_id}: Мальтипу — Узнать цену", "pipeline_id": PIPELINE, "status_id": STAGE,
        "_embedded": {"tags": [{"name": "сайт"}, {"name": "Мальтипу"}, {"name": "Узнать цену"}],
                      "contacts": [{"first_name": NAME, "custom_fields_values": [
                          {"field_code": "PHONE", "values": [{"value": PHONE_E164, "enum_code": "MOB"}]}]}]}}
    assert fake.calls[2].path == "leads/5001/notes"
    assert fake.calls[2].body[0]["note_type"] == "common"
    lines = fake.note().splitlines()
    assert lines[0].startswith(f"Заявка с сайта №{lead_id} · ")
    for line in (f"Имя: {NAME}", f"Телефон: {PHONE_FORM}", "Что нужно: Узнать цену", "Порода: Мальтипу",
                 "Окрас: Кремовый", "Вопрос: Сколько гуляет мальтипу?", "Куда написать: WhatsApp",
                 "Пометка формы: Заявка: меню", "Заголовок окна: Узнать цену", "Страница: /maltipu/",
                 "Источник: yandex / organic", "UTM: campaign=osen", "Тест «Подбор породы»: Мальтипу, затем Той-пудель",
                 f"Заявка №{lead_id} в админке: https://admin.example/leads/{lead_id}"):
        assert line in lines, line
    assert "Человек уже обращался раньше" not in lines and not any(x.startswith("Щенок") for x in lines)

    assert amo_state(db, lead_id) == {"lead_id": 5001, "contact_id": 9001, "note": True}
    assert db.scalar(select(Lead.details).where(Lead.id == lead_id))["question"] == "Сколько гуляет мальтипу?"
    o = outbox(db)[0]
    assert (o.status, o.attempts, o.last_error) == ("sent", 1, None)
    # sent once: a second run sends nothing
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 0, "failed": 0, "retry": 0}
    assert len(fake.calls) == 3


def test_without_pipeline_and_stage_amocrm_defaults_are_used_and_the_responsible_user_is_set(client, db, amo):
    amo.amocrm_pipeline_id = amo.amocrm_status_id = None
    amo.amocrm_responsible_user_id = 4242
    amo.amocrm_tags = ["сайт", "дом-щенков.рф"]
    lead_id, _ = post_lead(client, breed="", kind="consult")
    fake = FakeAmo()
    notify.deliver_due(db, client=fake.client())
    (deal,) = fake.of("POST leads/complex")[0].body
    assert "pipeline_id" not in deal and "status_id" not in deal and deal["responsible_user_id"] == 4242
    assert deal["name"] == f"Заявка с сайта №{lead_id}: порода не выбрана — Консультация"
    assert [t["name"] for t in deal["_embedded"]["tags"]] == ["сайт", "дом-щенков.рф", "Консультация"]
    assert "Порода: не выбрана" in fake.note().splitlines()


@pytest.mark.parametrize("numbers, reused", [
    (["8 999 123-45-67"], True),                     # the same number written another way
    (["+7 (495) 000-00-00", "+79991234567"], True),  # the second number of the contact
    (["+7 (999) 123-45-60"], False),                 # the search matched a similar number
    ([], False),                                     # matched by another field, no phone at all
], ids=["same-number", "second-number", "other-number", "no-phone"])
def test_an_existing_contact_is_reused_only_with_the_same_number(client, db, amo, numbers, reused):
    found = {"id": 777, "name": "Евлампия Петровна", "custom_fields_values": [
        {"field_code": "EMAIL", "values": [{"value": "e@example.ru"}]}]}
    if numbers:
        found["custom_fields_values"].append({"field_code": "PHONE", "values": [{"value": n, "enum_code": "WORK"}
                                                                                  for n in numbers]})
    lead_id, _ = post_lead(client)
    fake = FakeAmo(contacts=[found])
    assert notify.deliver_due(db, client=fake.client())["sent"] == 1
    contact = fake.of("POST leads/complex")[0].body[0]["_embedded"]["contacts"]
    if reused:
        assert contact == [{"id": 777}]
        assert amo_state(db, lead_id)["contact_id"] == 777
    else:
        assert contact[0]["first_name"] == NAME and "id" not in contact[0]
        assert amo_state(db, lead_id)["contact_id"] == 9001


# ---------------------------------------------------------------- repeat requests
def test_repeat_request_is_a_note_in_the_deal_of_the_first_request(client, db, amo):
    first, _ = post_lead(client, kind="price")
    fake = FakeAmo()
    notify.deliver_due(db, client=fake.client())
    second, _ = post_lead(client, kind="video_call")
    assert db.scalar(select(Lead.parent_id).where(Lead.id == second)) == first
    assert [(o.lead_id, o.event) for o in outbox(db)] == [(first, "lead.created"), (second, "lead.repeat")]

    assert notify.deliver_due(db, client=fake.client())["sent"] == 1
    assert fake.keys() == ["GET contacts", "POST leads/complex", "POST notes", "POST notes"]
    assert fake.calls[-1].path == "leads/5001/notes"
    lines = fake.note().splitlines()
    assert lines[0].startswith(f"Повторная заявка с сайта №{second} (первая — №{first}) · ")
    assert "Что нужно: Видеозвонок со щенком" in lines and "Человек уже обращался раньше" in lines
    assert amo_state(db, second) == {"lead_id": 5001, "to_request": first, "note": True}
    assert amo_state(db, first) == {"lead_id": 5001, "contact_id": 9001, "note": True}  # the first is not touched


def test_repeat_whose_first_request_has_no_deal_makes_one_and_the_next_repeat_joins_it(client, db, amo, settings):
    settings.amocrm_token = ""          # the first request came before amoCRM was connected
    first, _ = post_lead(client, kind="price")
    assert outbox(db) == []
    settings.amocrm_token = AMO_TOKEN
    second, _ = post_lead(client, kind="video_call")
    fake = FakeAmo()
    assert notify.deliver_due(db, client=fake.client())["sent"] == 1
    assert fake.keys() == ["GET contacts", "POST leads/complex", "POST notes"]
    assert fake.of("POST leads/complex")[0].body[0]["name"] == \
        f"Заявка с сайта №{second}: Мальтипу — Видеозвонок со щенком"
    assert fake.note().startswith(f"Повторная заявка с сайта №{second} (первая — №{first})")
    assert amo_state(db, second) == {"lead_id": 5001, "contact_id": 9001, "note": True}

    third, _ = post_lead(client, kind="litter")
    assert db.scalar(select(Lead.parent_id).where(Lead.id == third)) == first
    notify.deliver_due(db, client=fake.client())
    assert fake.keys()[3:] == ["POST notes"] and fake.calls[-1].path == "leads/5001/notes"
    assert len(fake.deals) == 1


def test_repeat_waits_while_the_deal_of_the_first_request_is_still_being_sent(client, db, amo):
    first, _ = post_lead(client, kind="price")
    down = httpx.Response(503, text="Service Unavailable")
    fake = FakeAmo(fail={"POST leads/complex": [down, down]})
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 0, "failed": 0, "retry": 1}
    second, _ = post_lead(client, kind="video_call")
    make_due(db)
    # the first fails again; the repeat must not make a deal of its own meanwhile
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 0, "failed": 0, "retry": 2}
    rows = {o.lead_id: o for o in outbox(db)}
    assert rows[second].status == "pending" and rows[second].attempts == 0  # waiting is not an attempt
    assert f"request №{first}" in rows[second].last_error
    assert len(fake.of("POST leads/complex")) == 2 and fake.deals == []

    make_due(db)
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 2, "failed": 0, "retry": 0}
    assert len(fake.deals) == 1
    assert [c.path for c in fake.of("POST notes")] == ["leads/5001/notes", "leads/5001/notes"]
    assert amo_state(db, second)["lead_id"] == 5001


# ---------------------------------------------------------------- failures half-way
def test_a_retry_after_the_note_failed_does_not_make_a_second_deal(client, db, amo):
    lead_id, _ = post_lead(client)
    fake = FakeAmo(fail={"POST notes": [httpx.Response(500, json={"title": "Internal Server Error", "status": 500})]})
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 0, "failed": 0, "retry": 1}
    o = outbox(db)[0]
    assert (o.status, o.attempts) == ("pending", 1) and "amoCRM 500" in o.last_error
    assert amo_state(db, lead_id) == {"lead_id": 5001, "contact_id": 9001}  # committed with the outbox row

    make_due(db)
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 1, "failed": 0, "retry": 0}
    assert fake.keys() == ["GET contacts", "POST leads/complex", "POST notes", "POST notes"]
    assert len(fake.deals) == 1
    assert amo_state(db, lead_id) == {"lead_id": 5001, "contact_id": 9001, "note": True}


def test_a_deal_made_without_an_answer_is_found_again_not_made_twice(client, db, amo):
    lead_id, _ = post_lead(client)
    fake = FakeAmo(fail={"POST leads/complex": ["lost"]})
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 0, "failed": 0, "retry": 1}
    assert "ReadTimeout" in outbox(db)[0].last_error
    assert amo_state(db, lead_id) == {"creating": True}

    make_due(db)
    assert notify.deliver_due(db, client=fake.client())["sent"] == 1
    assert fake.keys() == ["GET contacts", "POST leads/complex", "GET leads", "POST notes"]
    assert fake.of("GET leads")[0].params["query"] == f"Заявка с сайта №{lead_id}:"
    assert len(fake.deals) == 1
    assert amo_state(db, lead_id) == {"lead_id": 5001, "contact_id": 9001, "note": True}


def test_no_answer_before_the_deal_was_asked_for_just_retries(client, db, amo):
    lead_id, _ = post_lead(client)
    fake = FakeAmo(fail={"GET contacts": [httpx.ConnectError("[Errno 111] Connection refused")]})
    assert notify.deliver_due(db, client=fake.client())["retry"] == 1
    assert amo_state(db, lead_id) is None
    make_due(db)
    assert notify.deliver_due(db, client=fake.client())["sent"] == 1
    assert fake.keys() == ["GET contacts", "GET contacts", "POST leads/complex", "POST notes"]


@pytest.mark.parametrize("echo", ["whole", "cut"])
def test_401_fails_at_once_and_the_token_is_never_stored(client, db, amo, caplog, echo):
    leaked = AMO_TOKEN if echo == "whole" else AMO_TOKEN[:40]
    post_lead(client)
    fake = FakeAmo(fail={"GET contacts": [httpx.Response(401, json={
        "title": "Unauthorized", "status": 401, "detail": f"Token {leaked} is revoked"})]})
    with caplog.at_level("DEBUG"):
        assert notify.deliver_due(db, client=fake.client()) == {"sent": 0, "failed": 1, "retry": 0}
    o = outbox(db)[0]
    assert (o.status, o.attempts) == ("failed", 1)
    assert "amoCRM 401" in o.last_error and "revoked" in o.last_error
    assert_no_token(o.last_error, caplog.text)
    make_due(db)
    notify.deliver_due(db, client=fake.client())
    assert len(fake.calls) == 1  # never retried


def _refuse_with_url(request: httpx.Request):
    raise httpx.ConnectError(f"Connection refused while connecting to {request.url}", request=request)


def _echo_url(request: httpx.Request):
    return httpx.Response(502, text=f"<html>upstream {request.url} unavailable</html>")


@pytest.mark.parametrize("answer", [_refuse_with_url, _echo_url], ids=["transport-error", "error-page"])
def test_the_phone_of_the_search_never_reaches_the_error(client, db, amo, caplog, answer):
    post_lead(client)
    with caplog.at_level("DEBUG"):
        assert notify.deliver_due(db, client=FakeAmo(fail={"GET contacts": [answer]}).client())["retry"] == 1
    err = outbox(db)[0].last_error
    assert err.startswith("RuntimeError: amoCRM ") and "contacts" in err
    assert "9991234567" not in err and "9991234567" not in caplog.text


@pytest.mark.parametrize("headers, wait", [({"Retry-After": "120"}, 120), ({}, 60)], ids=["retry-after", "default"])
def test_429_waits_and_tries_again_later(client, db, amo, headers, wait):
    lead_id, _ = post_lead(client)
    fake = FakeAmo(fail={"POST leads/complex": [httpx.Response(429, headers=headers)]})
    before = dt.datetime.now(UTC)
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 0, "failed": 0, "retry": 1}
    o = outbox(db)[0]
    assert o.status == "pending" and wait - 2 <= (o.next_attempt_at - before).total_seconds() <= wait + 5
    assert notify.deliver_due(db, client=fake.client())["sent"] == 0  # not due yet
    make_due(db)
    assert notify.deliver_due(db, client=fake.client())["sent"] == 1
    assert len(fake.deals) == 1


@pytest.mark.parametrize("status, outcome", [(400, "failed"), (402, "failed"), (403, "failed"), (500, "pending"),
                                             (503, "pending")])
def test_amocrm_answer_codes(client, db, amo, status, outcome):
    post_lead(client)
    answer = httpx.Response(status, json={
        "title": "Bad Request", "status": status, "detail": "Request validation failed",
        "validation-errors": [{"request_id": "0", "errors": [{"code": "NotSupportedChoice", "path": "status_id"}]}]})
    fake = FakeAmo(fail={"POST leads/complex": [answer]})
    notify.deliver_due(db, client=fake.client())
    o = outbox(db)[0]
    assert o.status == outcome and f"amoCRM {status} leads/complex" in o.last_error
    if status == 400:
        assert "status_id: NotSupportedChoice" in o.last_error


# ---------------------------------------------------------------- what never goes to amoCRM
@pytest.mark.parametrize("missing", ["amocrm_token", "amocrm_subdomain"])
def test_the_channel_is_off_without_the_token_or_the_subdomain(client, db, amo, missing, no_network):
    setattr(amo, missing, "")
    post_lead(client)
    assert outbox(db) == [] and no_network == []


def test_a_request_with_a_consent_text_that_does_not_name_amocrm_stays_with_us(client, db, amo):
    """152-ФЗ: amoCRM (АО «амоЦРМ») processes requests on our behalf only for people whose consent text names it —
    a page opened before 06.11.2026 sends the older text: telegram/email still, amoCRM never."""
    from app.services import consent
    assert consent.allows_processor(CONSENT_CURRENT["processing"], "amocrm")
    assert not consent.allows_processor("processing-2026-11-02", "amocrm")
    post_lead(client, consent_version="processing-2026-11-02")
    assert "amocrm" not in {o.channel for o in outbox(db)}
    post_lead(client, phone="+7 (999) 765-43-21")
    assert "amocrm" in {o.channel for o in outbox(db)}


def test_reviews_never_go_to_amocrm(client, db, amo):
    amo.telegram_bot_token, amo.telegram_chat_id, amo.telegram_breed_chats = "7012345678:AAH-test", "-1001", {}
    r = client.post("/api/v1/reviews", json={
        "name": NAME, "phone": PHONE_FORM, "city": "Новосибирск", "breed": "maltipu", "rating": 5,
        "text": "Взяли у вас мальтипу, щенок весёлый и здоровый.", "consent": True,
        "consent_version": CONSENT_CURRENT["review"], "consent_publish": True,
        "consent_publish_version": CONSENT_CURRENT["distribution"], "page": {"path": "/otzyvy/", "title": "Отзывы"},
        "idempotency_key": str(uuid.uuid4()), "hp_note": "", "elapsed_ms": 40_000})
    assert r.status_code == 201, r.text
    assert [(o.channel, o.event) for o in outbox(db)] == [("telegram", "review.created")]


def test_spam_and_manual_requests_do_not_go_to_amocrm(client, db, amo, manager_h):
    post_lead(client)
    db.execute(text("UPDATE contacts SET is_blocked = true"))
    db.execute(text("DELETE FROM outbox"))
    db.commit()
    post_lead(client, breed="toj-pudel")                     # a blocked person: spam
    r = client.post("/api/v1/admin/leads", headers=manager_h,  # taken by phone: the manager is already on it
                    json={"origin": "phone", "name": "Пётр", "phone": "+7 999 000-11-22", "breed": "maltipu"})
    assert r.status_code == 201, r.text
    assert outbox(db) == []


def test_an_erased_person_is_never_sent_and_the_erasure_names_the_deal(client, db, amo, admin_h):
    lead_id, _ = post_lead(client)
    db.execute(text("UPDATE leads SET anonymised_at = now(), name = NULL, phone = NULL, contact_id = NULL "
                    "WHERE id = :i"), {"i": lead_id})
    db.commit()
    fake = FakeAmo()
    assert notify.deliver_due(db, client=fake.client()) == {"sent": 0, "failed": 1, "retry": 0}
    assert fake.calls == [] and "erased" in outbox(db)[0].last_error

    other, _ = post_lead(client, phone="+7 (999) 222-33-44", breed="border-kolli")
    notify.deliver_due(db, client=fake.client())
    contact_id = db.scalar(select(Lead.contact_id).where(Lead.id == other))
    r = client.post(f"/api/v1/admin/contacts/{contact_id}/erase", headers=admin_h,
                    json={"reason": "withdrawal", "subject": NAME})
    assert r.status_code == 200, r.text
    assert any("amoCRM" in step and "https://monnypassy.amocrm.ru/leads/detail/5001" in step
               for step in r.json()["manual_steps"])


# ---------------------------------------------------------------- the admin panel
def test_the_lead_card_links_to_the_deal_and_never_shows_the_token(client, db, amo, manager_h):
    lead_id, _ = post_lead(client)
    notify.deliver_due(db, client=FakeAmo().client())
    r = client.get(f"/api/v1/admin/leads/{lead_id}", headers=manager_h)
    assert r.status_code == 200, r.text
    assert r.json()["links"]["amocrm"] == "https://monnypassy.amocrm.ru/leads/detail/5001"
    assert r.json()["details"]["amocrm"]["lead_id"] == 5001
    assert_no_token(r.text)


# ---------------------------------------------------------------- settings
def test_the_subdomain_is_taken_from_the_full_address_and_empty_ids_are_none():
    s = Settings(amocrm_subdomain="https://MonnyPassy.amocrm.ru/leads/pipeline/", amocrm_token=f" Bearer {AMO_TOKEN} ",
                 amocrm_pipeline_id="", amocrm_status_id=" ", amocrm_tags="сайт, дом-щенков.рф")
    assert (s.amocrm_subdomain, s.amocrm_host, s.amocrm_token) == ("monnypassy", "monnypassy.amocrm.ru", AMO_TOKEN)
    assert s.amocrm_pipeline_id is None and s.amocrm_status_id is None and s.amocrm_enabled
    assert s.amocrm_tags == ["сайт", "дом-щенков.рф"]
    assert notify._amo_url(s, "account") == "https://monnypassy.amocrm.ru/api/v4/account"
    assert Settings(amocrm_subdomain="monnypassy").amocrm_host == "monnypassy.amocrm.ru"
    assert Settings(amocrm_subdomain="https://kennel.kommo.com/").amocrm_host == "kennel.kommo.com"
    assert not Settings(amocrm_subdomain="monnypassy", amocrm_token="").amocrm_enabled


# ---------------------------------------------------------------- python -m app notify-check
@pytest.fixture
def check(amo, monkeypatch):
    """Only amoCRM is on; the check talks to the stub."""
    for k, v in dict(telegram_bot_token="", telegram_chat_id="", telegram_breed_chats={}, smtp_host="",
                     notify_emails=[], webhook_url="").items():
        monkeypatch.setattr(amo, k, v)
    fake = FakeAmo()
    monkeypatch.setattr(notify, "http_client", fake.client)
    return fake


def run(capsys, *argv) -> tuple[int, str]:
    code = main(["notify-check", *argv])
    out = capsys.readouterr().out
    assert_no_token(out)
    return code, out


def test_notify_check_lists_pipelines_and_stages_and_marks_the_configured_ones(check, capsys):
    code, out = run(capsys)
    assert code == 0, out
    assert "✓ аккаунт «Питомник Дом щенков» (monnypassy.amocrm.ru)" in out
    assert f"    {PIPELINE}  Продажи щенков (главная)  ← сюда" in out
    assert f"      {STAGE}  Новая заявка  ← сюда" in out
    assert f"    {OTHER_PIPELINE}  Стартовые наборы" in out and f"      {OTHER_STAGE}  Первичный контакт" in out
    assert "60000  Неразобранное (неразобранное)" in out and "142  Успешно реализовано (успешно" in out
    assert "воронка «Продажи щенков», этап «Новая заявка»" in out and "Итог: всё в порядке" in out
    assert check.keys() == ["GET account", "GET leads/pipelines"]  # nothing is made without --send


@pytest.mark.parametrize("pipeline, status, words", [
    (PIPELINE, OTHER_STAGE, f"этапа {OTHER_STAGE} нет в воронке «Продажи щенков»"),
    (PIPELINE, 99999, "этапа 99999 нет в воронке «Продажи щенков»: проверьте DSH_AMOCRM_STATUS_ID"),
    (12345, None, "воронки 12345 нет в аккаунте: проверьте DSH_AMOCRM_PIPELINE_ID"),
    (None, 142, "закрывает сделку"),
], ids=["stage-of-another-pipeline", "no-such-stage", "no-such-pipeline", "closing-stage"])
def test_notify_check_flags_a_wrong_pipeline_or_stage(amo, check, capsys, pipeline, status, words):
    amo.amocrm_pipeline_id, amo.amocrm_status_id = pipeline, status
    code, out = run(capsys, "--send")
    assert code == 1, out
    assert words in out and "Итог: проблем: 1" in out
    assert f"    {OTHER_PIPELINE}  Стартовые наборы" in out  # the list is shown, to pick the right ids
    if status == OTHER_STAGE:
        assert f"из воронки «Стартовые наборы», её id {OTHER_PIPELINE}" in out
    assert check.of("POST leads/complex") == []  # no test deal into a wrong place


def test_notify_check_send_makes_a_clearly_marked_test_deal_without_personal_data(check, capsys):
    code, out = run(capsys, "--send")
    assert code == 0, out
    (deal,) = check.of("POST leads/complex")[0].body
    assert deal["name"] == "Проверка интеграции с сайтом дом-щенков.рф — можно удалить"
    assert deal["_embedded"]["contacts"] == [{"first_name": "Тест"}]
    assert (deal["pipeline_id"], deal["status_id"]) == (PIPELINE, STAGE)
    assert [t["name"] for t in deal["_embedded"]["tags"]] == ["сайт", "проверка"]
    assert check.of("POST notes")[0].path == "leads/5001/notes"
    assert "✓ тестовая сделка создана: https://monnypassy.amocrm.ru/leads/detail/5001" in out


def test_notify_check_explains_a_rejected_token(check, capsys):
    check.fail["GET account"] = [httpx.Response(401, json={"title": "Unauthorized", "status": 401,
                                                            "detail": f"bad token {AMO_TOKEN}"})]
    code, out = run(capsys)
    assert code == 1
    assert "токен не принят" in out and "DSH_AMOCRM_TOKEN" in out and "amoCRM 401" in out


def test_notify_check_no_connection_is_not_a_rejected_token(check, capsys):
    check.fail["GET account"] = [httpx.ConnectError("[Errno -2] Name or service not known")]
    code, out = run(capsys)
    assert code == 1
    assert "не достаёт до amoCRM" in out and "токен не принят" not in out


@pytest.mark.parametrize("missing, words", [("amocrm_token", "DSH_AMOCRM_TOKEN"),
                                            ("amocrm_subdomain", "DSH_AMOCRM_SUBDOMAIN")])
def test_notify_check_half_filled_settings(amo, check, capsys, missing, words):
    setattr(amo, missing, "")
    code, out = run(capsys)
    assert code == 1
    assert "нужны оба" in out and words in out and check.calls == []


# ---------------------------------------------------------------- python -m app notify-test
def test_notify_test_checks_the_amocrm_token_without_making_a_deal(amo, capsys):
    fake = FakeAmo()
    (r,) = notify.send_test(amo, client=fake.client())
    assert (r["channel"], r["target"], r["ok"]) == ("amocrm", "monnypassy.amocrm.ru", True)
    assert fake.keys() == ["GET account"]

    fake = FakeAmo(fail={"GET account": [httpx.Response(401, json={"title": "Unauthorized",
                                                                    "detail": f"token {AMO_TOKEN}"})]})
    (r,) = notify.send_test(amo, client=fake.client())
    assert not r["ok"] and "DSH_AMOCRM_TOKEN" in r["hint"] and "amoCRM 401" in r["error"]
    assert_no_token(r["error"])

    amo.amocrm_token = ""
    (r,) = notify.send_test(amo, client=FakeAmo().client())
    assert not r["ok"] and "DSH_AMOCRM_SUBDOMAIN и DSH_AMOCRM_TOKEN" in r["hint"]
