"""Manager notifications through the outbox.

Channels (each is optional, configured in .env):
- telegram — chat per breed (or several chats: a group and the private chat with the bot). Telegram is outside Russia, so by default a message carries NO personal data:
  «№123 · Мальтипу · Цена щенка · 14:32» + a link to the admin panel. Plain text, no markup.
- email    — full details (name, phone, «куда написать») over SMTP of a Russian provider to the kennel's mailbox.
- webhook  — {event, id, public_id, at}, HMAC-signed; the receiver (the admin panel) pulls the details with its key.
- amocrm   — requests only (no reviews): a deal in the configured pipeline and stage with the contact (name, phone,
  an existing contact with the same number is reused) and a note with every detail of the request. A repeat request
  is a note in the deal of the person's first request, not a new deal. The deal id is kept in leads.details["amocrm"].

enqueue_*() runs inside the request transaction (the lead and its notifications commit together).
deliver_due() sends what is due: right after the request (background task), and in a loop in the worker
(`python -m app worker`). Safe in several processes at once (FOR UPDATE SKIP LOCKED)."""
from __future__ import annotations

import datetime as dt
import html
import json
import logging
import re
import smtplib
import socket
import ssl
import time
import zoneinfo
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

import httpx
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..enums import CHANNEL_LABELS, LEAD_KIND_LABELS, Channel, LeadKind
from ..models import Lead, Outbox, Review, SiteEvent, Visit, Visitor
from . import catalog, consent
from . import phone as phones
from .security import sign

log = logging.getLogger("dsh.notify")
logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx logs URLs at INFO, and the bot token is in the URL
UTC = dt.timezone.utc


class Permanent(Exception):
    """A failure that a retry will not fix (bad chat id, bot blocked, address rejected)."""


class RetryAfter(Exception):
    def __init__(self, seconds: int):
        super().__init__(f"rate limited, retry after {seconds}s")
        self.seconds = seconds


class Wait(RetryAfter):
    """Not a failure: the row waits for another one (a repeat request for the amoCRM deal of the first request), so
    its attempts are not spent."""

    def __init__(self, seconds: int, reason: str):
        super().__init__(seconds)
        self.args = (reason,)


def chat_list(value: str) -> list[str]:
    """DSH_TELEGRAM_CHAT_ID (and a breed chat) may name several chats separated by commas: a group and the private
    chat with the bot «-100…,123…» — a request goes to each of them."""
    return list(dict.fromkeys(c.strip()[:300] for c in (value or "").split(",") if c.strip()))


def _targets(s: Settings, breed_key: str | None) -> list[tuple[str, str]]:
    out = []
    if s.telegram_bot_token:
        chats = chat_list(s.telegram_breed_chats.get(breed_key or "", "")) or chat_list(s.telegram_chat_id)
        out.extend(("telegram", chat) for chat in chats)  # one row per chat, like e-mail per address
    if s.smtp_host:
        out.extend(("email", addr[:300]) for addr in s.notify_emails)  # one row per address
    if s.webhook_url:
        out.append(("webhook", s.webhook_url))
    if s.amocrm_enabled:
        out.append(("amocrm", s.amocrm_subdomain[:300]))  # one row per request: the deal, its contact and the note
    return out


def enqueue_lead(db: Session, lead: Lead, event: str = "lead.created",
                 channels: tuple[str, ...] = ("telegram", "email", "webhook", "amocrm")) -> list[str]:
    s = get_settings()
    out = []
    for channel, target in _targets(s, lead.breed.key if lead.breed else None):
        if channel not in channels:
            continue
        if channel != "webhook" and event not in ("lead.created", "lead.repeat"):
            continue  # people are pinged about requests; the webhook hears every change
        if channel == "amocrm" and not consent.allows_processor(lead.consent_version, "amocrm"):
            continue  # the person agreed to a text that does not name amoCRM: the request stays with us
        db.add(Outbox(channel=channel, target=target, event=event, lead_id=lead.id))
        out.append(channel)
    return out


def enqueue_review(db: Session, review: Review) -> list[str]:
    s = get_settings()
    out = []
    for channel, target in _targets(s, review.breed.key if review.breed else None):
        if channel == "amocrm":
            continue  # amoCRM gets requests only: a review is not a deal
        db.add(Outbox(channel=channel, target=target, event="review.created", review_id=review.id))
        out.append(channel)
    return out


# ---------------------------------------------------------------- message bodies
def _local(t: dt.datetime, s: Settings) -> dt.datetime:
    return t.astimezone(zoneinfo.ZoneInfo(s.timezone))


def _admin_link(s: Settings, lead_id: int) -> str:
    return s.admin_base_url.format(id=lead_id) if s.admin_base_url else ""


# where the visit came from, in words: source/medium from attribution.classify()
_SOURCE_NAMES = {"yandex": "Яндекс", "google": "Google", "bing": "Bing", "duckduckgo": "DuckDuckGo", "rambler": "Рамблер",
                 "mail.ru": "Mail.ru", "yahoo": "Yahoo", "vk": "ВКонтакте", "ok": "Одноклассники", "telegram": "Telegram",
                 "instagram": "Instagram", "facebook": "Facebook", "youtube": "YouTube", "dzen": "Дзен",
                 "pinterest": "Pinterest", "tiktok": "TikTok", "avito": "Авито", "whatsapp": "WhatsApp", "max": "MAX"}
_DEVICES = {"mobile": "📱 телефон", "tablet": "📱 планшет", "desktop": "💻 компьютер"}


def source_label(source: str | None, medium: str | None) -> str:
    src, med = (source or "").lower(), (medium or "").lower()
    if not src or src == "(direct)":
        return "✍️ прямой заход"
    name = _SOURCE_NAMES.get(src, source)
    if med == "organic":
        return f"🔍 поиск — {name}"
    if med in ("cpc", "ppc", "paid", "cpm"):
        return "💰 реклама — " + {"yandex": "Яндекс Директ", "google": "Google Ads"}.get(src, name)
    if med == "social":
        return f"💬 соцсеть — {name}"
    if med == "referral":
        return f"🔗 переход с сайта {name}"
    return f"🏷 метка — {name} / {medium}"


def visit_facts(db: Session, lead: Lead) -> dict:
    """What the site saw before the request (only while site activity is linked to requests: the consent says so):
    pages viewed, the device, the Yandex Metrika ClientID."""
    out: dict = {}
    if lead.visitor_id:
        out["pages"] = db.scalar(select(func.count()).select_from(SiteEvent).where(
            SiteEvent.visitor_id == lead.visitor_id, SiteEvent.type == "page_view",
            SiteEvent.occurred_at <= lead.created_at)) or 0
        v = db.get(Visitor, lead.visitor_id)
        if v is not None and v.ym_uid:
            out["ym_uid"] = v.ym_uid
    if lead.session_id:
        visit = db.get(Visit, lead.session_id)
        if visit is not None and visit.device in _DEVICES:
            out["device"] = _DEVICES[visit.device]
    return out


def telegram_text(lead: Lead | None, review: Review | None, event: str, s: Settings, facts: dict | None = None) -> str:
    """HTML for parse_mode=HTML, every value escaped. Personal data (name, phone, messenger) only with
    telegram_include_pd AND a consent version that names the transfer abroad (notice to Роскомнадзор first)."""
    def e(v) -> str:
        return html.escape(str(v), quote=False)

    if review is not None:
        lines = [f"⭐ <b>Новый отзыв №{review.id}</b> · {'★' * review.rating}"]
        if review.breed:
            lines.append(f"🐾 Порода: {e(review.breed.name)}")
        lines.append("🕒 Ждёт модерации")
        return "\n".join(lines)
    facts = facts or {}
    num = lead.parent_id or lead.id
    kind = LEAD_KIND_LABELS.get(LeadKind(lead.kind), lead.kind)
    breed = lead.breed.name if lead.breed else "порода не выбрана"
    head = (f"🔁 <b>Повторный запрос по заявке №{num}</b>" if event == "lead.repeat"
            else f"🐶 <b>Новая заявка №{lead.id}</b>")
    lines = [head, "", f"🐾 Порода: {e(breed)}", f"📋 Запрос: {e(kind)}"]
    if lead.puppy_name:
        lines.append(f"🐕 Щенок: {e(lead.puppy_name)}")
    if lead.colour:
        colour = catalog.load().colour_label(lead.breed.slug if lead.breed else None, lead.colour) or lead.colour
        lines.append(f"🎨 Окрас: {e(colour)}")
    if lead.note:
        lines.append(f"🖱 Кнопка: {e(lead.note)}")
    question = (lead.details or {}).get("question")
    if s.telegram_include_pd and consent.allows_cross_border(lead.consent_version):
        lines += ["", f"👤 Имя: {e(lead.name)}", f"📞 Телефон: {e(phones.display(lead.phone))}",
                  f"💬 Куда написать: {e(CHANNEL_LABELS.get(Channel(lead.channel), lead.channel))}"]
        if question:
            lines.append(f"❓ Вопрос: {e(question[:500])}")
    elif question:  # free text may hold personal data: its text goes to Telegram only with the cross-border notice
        lines.append("❓ Есть вопрос — текст в админке")
    lines += ["", f"📍 Источник: {e(source_label(lead.source, lead.medium))}"]
    if lead.landing_path:
        lines.append(f"   • Вошёл на: {e(lead.landing_path)}")
    if lead.page_path and lead.page_path != lead.landing_path:
        lines.append(f"   • Заявка со страницы: {e(lead.page_path)}")
    utm = lead.utm or {}
    if utm.get("campaign"):
        lines.append(f"   • Кампания: {e(utm['campaign'])}")
    if utm.get("term"):
        lines.append(f"   • Ключевая фраза: {e(utm['term'])}")
    if facts.get("pages"):
        lines.append(f"📄 Посмотрел страниц до заявки: {facts['pages']}")
    if facts.get("device"):
        lines.append(f"🖥 Устройство: {e(facts['device'])}")
    if facts.get("ym_uid"):
        lines.append(f"🆔 Метрика ClientID: {e(facts['ym_uid'])}")
    if lead.is_repeat:
        lines.append("🔁 Человек уже обращался раньше")
    if lead.flags:
        lines.append(f"⚠️ Антиспам: {e(', '.join(lead.flags))}")
    lines += ["", f"🕒 {_local(lead.created_at, s):%d.%m.%Y, %H:%M}"]
    link = _admin_link(s, num)
    if link:
        lines.append(f'👉 <a href="{html.escape(link, quote=True)}">Открыть заявку в админке</a>')
    return "\n".join(lines)


def _plain(text: str) -> str:
    """The HTML message without markup: a link becomes «label: url»."""
    text = re.sub(r'<a href="([^"]*)">([^<]*)</a>', lambda m: f"{m.group(2)}: {html.unescape(m.group(1))}", text)
    return html.unescape(re.sub(r"</?[a-z]+>", "", text))


def email_message(lead: Lead | None, review: Review | None, event: str, s: Settings) -> EmailMessage:
    m = EmailMessage()
    if review is not None:
        m["Subject"] = f"Отзыв №{review.id} ждёт модерации ({review.rating}/5)"
        body = [f"Имя: {review.name}", f"Город: {review.city or '—'}",
                f"Порода: {review.breed.name if review.breed else '—'}", f"Оценка: {review.rating} из 5", "",
                review.text]
    else:
        num = lead.parent_id or lead.id
        kind = LEAD_KIND_LABELS.get(LeadKind(lead.kind), lead.kind)
        breed = lead.breed.name if lead.breed else "порода не выбрана"
        title = f"Повторный запрос по заявке №{num}" if event == "lead.repeat" else f"Заявка №{lead.id}"
        m["Subject"] = f"{title}: {breed}, {kind}"
        when = _local(lead.created_at, s)
        body = [f"{title} · {when:%d.%m.%Y %H:%M}", ""]
        if s.email_include_pd:
            body += [f"Имя: {lead.name}", f"Телефон: {phones.display(lead.phone)}",
                     f"Куда написать: {CHANNEL_LABELS.get(Channel(lead.channel), lead.channel)}"]
        body += [f"Порода: {breed}", f"Что нужно: {kind}"]
        if lead.puppy_name:
            body.append(f"Щенок: {lead.puppy_name}")
        if lead.colour:
            body.append(f"Окрас: {lead.colour}")
        if lead.note:
            body.append(f"Пометка формы: {lead.note}")
        question = (lead.details or {}).get("question")
        if question:
            body += ["", "Вопрос:", question, ""] if s.email_include_pd else ["Есть вопрос — текст в админке"]
        if lead.page_path:
            body.append(f"Страница: {lead.page_path}")
        src = " / ".join(x for x in (lead.source, lead.medium) if x)
        if src:
            body.append(f"Источник: {src}")
        if lead.is_repeat:
            body.append("Человек уже обращался раньше.")
        if lead.flags:
            body.append(f"Отметки антиспама: {', '.join(lead.flags)}")
        link = _admin_link(s, num)
        if link:
            body += ["", link]
    m["From"] = formataddr(("дом-щенков.рф", s.smtp_from or s.smtp_user))
    m["Message-ID"] = make_msgid(domain=(s.smtp_from or s.smtp_user or "localhost").split("@")[-1])
    m.set_content("\n".join(body))
    return m


def webhook_body(item: Outbox, lead: Lead | None, review: Review | None) -> bytes:
    """No personal data: the receiver pulls the record by id with its API key."""
    subject = ({"type": "lead", "id": lead.id, "public_id": str(lead.public_id), "parent_id": lead.parent_id}
               if lead is not None else {"type": "review", "id": review.id})
    return json.dumps({"event": item.event, "delivery": item.id, "at": dt.datetime.now(UTC).isoformat(),
                       **subject}, ensure_ascii=False).encode()


def amocrm_deal_name(lead: Lead) -> str:
    """«Заявка с сайта №123: Мальтипу — Узнать цену». The number also finds the deal again after a lost answer."""
    kind = LEAD_KIND_LABELS.get(LeadKind(lead.kind), lead.kind)
    return f"Заявка с сайта №{lead.id}: {lead.breed.name if lead.breed else 'порода не выбрана'} — {kind}"


def amocrm_note(lead: Lead, event: str, s: Settings) -> str:
    """The note in the deal: plain text, one line per item the request has (empty ones are left out)."""
    details = lead.details or {}
    cat = catalog.load()
    head = (f"Повторная заявка с сайта №{lead.id} (первая — №{lead.parent_id})" if event == "lead.repeat"
            and lead.parent_id else f"Заявка с сайта №{lead.id}")
    lines = [f"{head} · {_local(lead.created_at, s):%d.%m.%Y %H:%M}", f"Имя: {lead.name}",
             f"Телефон: {phones.display(lead.phone)}"]
    kind = LEAD_KIND_LABELS.get(LeadKind(lead.kind), lead.kind)
    breed = lead.breed.name if lead.breed else (f"не распознана: {lead.breed_input}" if lead.breed_input
                                                else "не выбрана")
    colour = details.get("colour_raw")  # a colour the catalog does not know is kept raw
    if lead.colour:
        colour = cat.colour_label(lead.breed.slug if lead.breed else None, lead.colour) or lead.colour
    quiz = details.get("quiz") or {}
    quiz_names = [(cat.breed_by_any(quiz.get(k)) or {}).get("name") or quiz.get(k) for k in ("winner", "second")
                  if quiz.get(k)]
    utm = lead.utm or {}
    items = [
        ("Что нужно", kind + (f" ({details['kind_raw']})" if details.get("kind_raw") else "")),
        ("Порода", breed),
        ("Щенок", lead.puppy_name or lead.puppy_slug),
        ("Окрас", colour),
        ("Вопрос", details.get("question")),
        ("Куда написать", CHANNEL_LABELS.get(Channel(lead.channel), lead.channel)),
        ("Пометка формы", lead.note),
        ("Заголовок окна", lead.form_title),
        ("Страница", lead.page_path),
        ("Вошёл на сайт", lead.landing_path if lead.landing_path != lead.page_path else None),
        ("Источник", " / ".join(x for x in (lead.source, lead.medium) if x)),
        ("UTM", ", ".join(f"{k}={v}" for k, v in utm.items() if v)),
        ("Тест «Подбор породы»", ", затем ".join(quiz_names)),
    ]
    lines += [f"{label}: {value}" for label, value in items if value]
    if lead.is_repeat:
        lines.append("Человек уже обращался раньше")
    if lead.flags:
        lines.append(f"Отметки антиспама: {', '.join(lead.flags)}")
    num = lead.parent_id or lead.id
    link = _admin_link(s, num)
    if link:
        lines.append(f"Заявка №{num} в админке: {link}")
    return "\n".join(lines)


# ---------------------------------------------------------------- delivery
def _backoff(attempts: int) -> dt.timedelta:
    return dt.timedelta(seconds=min(30 * 2 ** max(attempts - 1, 0), 6 * 3600))  # 30 s, 1 min, 2 min … 6 h


def _tg_url(s: Settings, method: str) -> str:
    return f"{s.telegram_api_base.rstrip('/')}/bot{s.telegram_bot_token}/{method}"


def _send_telegram(item: Outbox, text: str, s: Settings, client: httpx.Client, parse_mode: str | None = None) -> None:
    body = {"chat_id": item.target, "text": text, "disable_web_page_preview": True}
    if parse_mode:
        body["parse_mode"] = parse_mode
    r = client.post(_tg_url(s, "sendMessage"), json=body)
    if r.status_code == 200:
        return
    if r.status_code == 400 and parse_mode and "parse entities" in r.text:
        # a markup mistake must not lose the notification: the same text without markup
        return _send_telegram(item, _plain(text), s, client)
    try:
        info = r.json()
    except ValueError:
        info = {}
    desc = _scrub(str(info.get("description", r.text)), s)[:200]  # mask before cutting: no token fragment left
    if r.status_code == 429:
        raise RetryAfter(int((info.get("parameters") or {}).get("retry_after", 30)))
    if r.status_code in (400, 401, 403, 404):
        raise Permanent(f"Telegram {r.status_code}: {desc}")
    raise RuntimeError(f"Telegram {r.status_code}: {desc}")


def _send_email(item: Outbox, msg: EmailMessage, s: Settings) -> None:
    msg["To"] = item.target
    try:
        if s.smtp_ssl:
            with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15, context=ssl.create_default_context()) as c:
                if s.smtp_user:
                    c.login(s.smtp_user, s.smtp_password)
                c.send_message(msg)
        else:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as c:
                c.starttls(context=ssl.create_default_context())
                if s.smtp_user:
                    c.login(s.smtp_user, s.smtp_password)
                c.send_message(msg)
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as e:
        raise Permanent(f"SMTP: {type(e).__name__}") from e


def _send_webhook(item: Outbox, body: bytes, s: Settings, client: httpx.Client) -> None:
    headers = {"Content-Type": "application/json", "X-Dsh-Event": item.event, "X-Dsh-Delivery": str(item.id)}
    if s.webhook_secret:
        headers["X-Dsh-Signature"] = sign(body, s.webhook_secret)
    r = client.post(item.target, content=body, headers=headers)
    if r.status_code in (400, 401, 403, 404, 410):
        raise Permanent(f"webhook HTTP {r.status_code}")
    if r.status_code >= 300:
        raise RuntimeError(f"webhook HTTP {r.status_code}")


_LONG_DIGITS = re.compile(r"\d{7,}")  # a phone number (the contact search carries it in the URL)


def _amo_url(s: Settings, path: str) -> str:
    return f"{(s.amocrm_api_base or 'https://' + s.amocrm_host).rstrip('/')}/api/v4/{path}"


def _amo_problem(r: httpx.Response) -> str:
    """amoCRM answers errors with problem+json: the detail and, for 400, which field it did not take."""
    try:
        info = r.json()
    except ValueError:
        return r.text
    if not isinstance(info, dict):
        return str(info)
    parts = [str(info.get("detail") or info.get("title") or "")]
    for v in info.get("validation-errors") or []:
        parts += [f"{e.get('path')}: {e.get('code')}" for e in (v.get("errors") or []) if isinstance(e, dict)]
    return "; ".join(p for p in parts if p)


def _amo(s: Settings, client: httpx.Client, method: str, path: str, **kw) -> httpx.Response:
    """One call of amoCRM API v4 with the long-lived token. A retry will not fix 401 (the token was revoked or has
    expired), 400 (e.g. a pipeline or stage id that is not there), 402 (the account is not paid), 403 or 404; 429 waits
    (amoCRM allows 7 calls a second); 5xx and no answer are retried with backoff."""
    try:
        r = client.request(method, _amo_url(s, path), headers={"Authorization": f"Bearer {s.amocrm_token}"}, **kw)
    except httpx.HTTPError as e:
        raise RuntimeError(f"amoCRM {path}: {type(e).__name__}: {_LONG_DIGITS.sub('***', str(e))}") from e
    if r.status_code < 300:
        return r
    desc = _scrub(_LONG_DIGITS.sub("***", _amo_problem(r)), s)[:200]  # mask before cutting
    if r.status_code == 429:
        wait = r.headers.get("Retry-After", "")
        raise RetryAfter(min(int(wait), 3600) if wait.isdigit() and int(wait) > 0 else 60)
    if r.status_code in (400, 401, 402, 403, 404):
        raise Permanent(f"amoCRM {r.status_code} {path}: {desc}")
    raise RuntimeError(f"amoCRM {r.status_code} {path}: {desc}")


def _amo_items(r: httpx.Response, key: str) -> list[dict]:
    """_embedded.<key> of a list answer; 204 No Content = nothing found."""
    if r.status_code == 204 or not r.content:
        return []
    return [x for x in ((r.json() or {}).get("_embedded") or {}).get(key) or [] if isinstance(x, dict)]


def _amo_contact(s: Settings, client: httpx.Client, phone: str | None) -> int | None:
    """The person's contact in amoCRM, found by the phone. Reused only when one of its numbers really is this one
    (the same last 10 digits): the search also matches parts of numbers and other fields."""
    want = re.sub(r"\D", "", phone or "")[-10:]
    if len(want) < 10:
        return None
    r = _amo(s, client, "GET", "contacts", params={"query": phone.lstrip("+"), "with": "leads"})
    for c in _amo_items(r, "contacts"):
        for f in c.get("custom_fields_values") or []:
            if f.get("field_code") == "PHONE" and any(
                    re.sub(r"\D", "", str(v.get("value", "")))[-10:] == want for v in f.get("values") or []):
                return int(c["id"])
    return None


def _site_url(s: Settings) -> str:
    """https://дом-щенков.рф (in punycode): the host of the admin links, else the first own host."""
    parts = urlsplit(s.admin_base_url)
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return f"https://{s.own_hosts[0]}" if s.own_hosts else ""


def _amo_deal(s: Settings, name: str, tags: list[str], contact: dict, form: dict) -> dict:
    """A deal of leads/complex: pipeline, stage and responsible user only when they are set (amoCRM's defaults).
    With DSH_AMOCRM_UNSORTED the deal goes to «Неразобранное» of the pipeline: leads/complex makes it a form request
    when it carries form metadata (amoCRM then ignores any other stage), so no stage is sent."""
    deal = {"name": name, "_embedded": {"tags": [{"name": t[:50]} for t in dict.fromkeys(tags) if t],
                                        "contacts": [contact]}}
    keys = ("pipeline_id", "responsible_user_id") if s.amocrm_unsorted else (
        "pipeline_id", "status_id", "responsible_user_id")
    for key in keys:
        value = getattr(s, "amocrm_" + key)
        if value is not None:
            deal[key] = value
    if s.amocrm_unsorted:
        deal["_embedded"]["metadata"] = {"category": "forms", **form}
    return deal


def _amo_form(s: Settings, lead: Lead) -> dict:
    """What «Неразобранное» shows about the form: its name, the page and when it was sent (no IP: amoCRM gets only
    what the consent names)."""
    kind = LEAD_KIND_LABELS.get(LeadKind(lead.kind), lead.kind)
    return {"form_id": f"site-{lead.kind}", "form_name": (lead.form_title or kind)[:100],
            "form_page": _site_url(s) + (lead.page_path or "/"), "form_sent_at": int(lead.created_at.timestamp())}


def _amo_new_deal(s: Settings, client: httpx.Client, lead: Lead, contact_id: int | None) -> tuple[int, int | None]:
    """POST leads/complex: the deal with the existing contact, or with a new one (name and phone) → (deal, contact)."""
    contact = {"id": contact_id} if contact_id else {
        "first_name": lead.name,
        "custom_fields_values": [{"field_code": "PHONE", "values": [{"value": lead.phone, "enum_code": "MOB"}]}]}
    tags = [*s.amocrm_tags, lead.breed.name if lead.breed else "", LEAD_KIND_LABELS.get(LeadKind(lead.kind), lead.kind)]
    r = _amo(s, client, "POST", "leads/complex",
             json=[_amo_deal(s, amocrm_deal_name(lead), tags, contact, _amo_form(s, lead))])
    made = r.json()[0]
    return int(made["id"]), made.get("contact_id") or contact_id


def _amo_get(s: Settings, client: httpx.Client, what: str, entity_id: int) -> dict | None:
    """GET leads/{id} or contacts/{id}; None — there is none (204: deleted, or its «Неразобранное» was declined)."""
    r = _amo(s, client, "GET", f"{what}/{int(entity_id)}")
    return r.json() if r.status_code != 204 and r.content else None


def _amo_known_contact(s: Settings, client: httpx.Client, db: Session, lead: Lead) -> int | None:
    """The amoCRM contact an earlier request of this person (the same contact in our base) already has — while that
    request waits in «Неразобранное», amoCRM's search does not see its contact, and a second one must not appear."""
    for details in db.scalars(select(Lead.details).where(Lead.contact_id == lead.contact_id, Lead.id != lead.id)
                              .order_by(Lead.id.desc())):
        known = ((details or {}).get("amocrm") or {}).get("contact_id")
        if known:
            return int(known) if _amo_get(s, client, "contacts", known) else None
    return None


_REPEATS = re.compile(r" · \+\d+ повторн\w*$")


def _repeats_word(n: int) -> str:
    """The admin's «+2 повторных» badge: повторный / повторных."""
    return "повторный" if n % 10 == 1 and n % 100 != 11 else "повторных"


def _amo_mark_repeats(s: Settings, client: httpx.Client, db: Session, lead: Lead, deal: int) -> None:
    """The deal's name shows how many repeat requests the person's card has, like the admin list: «… · +2
    повторных». Best effort: a deal amoCRM no longer has or will not rename does not fail the delivery."""
    current = _amo_get(s, client, "leads", deal)
    if current is None:
        return
    n = db.scalar(select(func.count()).select_from(Lead).where(Lead.parent_id == lead.parent_id,
                                                                 Lead.id <= lead.id)) or 0
    name = str(current.get("name") or "")
    new = f"{_REPEATS.sub('', name)} · +{n} {_repeats_word(n)}"[:255]
    if n and new != name:
        try:
            _amo(s, client, "PATCH", f"leads/{int(deal)}", json={"name": new})
        except Permanent as e:
            log.warning("amoCRM: the deal %s was not renamed: %s", deal, e)


def _amo_find_deal(s: Settings, client: httpx.Client, lead: Lead) -> tuple[int, int | None] | None:
    """The last attempt asked for the deal and got no answer (a timeout): amoCRM may have made it all the same.
    Found by its name, which starts with the request number."""
    prefix = f"Заявка с сайта №{lead.id}:"
    for d in _amo_items(_amo(s, client, "GET", "leads", params={"query": prefix, "with": "contacts"}), "leads"):
        if str(d.get("name", "")).startswith(prefix):
            contacts = (d.get("_embedded") or {}).get("contacts") or [{}]
            return int(d["id"]), contacts[0].get("id")
    return None


def _amo_first_deal(db: Session, item: Outbox, lead: Lead) -> int | None:
    """The person's deal: the newest one among their requests — the deal of the first request, or one an earlier
    repeat request made (the first came before amoCRM was connected, or its deal was deleted or declined). While the
    deal of one of them is still being sent: wait for it, so a repeat request never makes a second deal."""
    rows = db.execute(select(Lead.id, Lead.details).where(
        or_(Lead.id == lead.parent_id, Lead.parent_id == lead.parent_id), Lead.id != lead.id)
        .order_by(Lead.id.desc())).all()
    for _, details in rows:
        deal = ((details or {}).get("amocrm") or {}).get("lead_id")
        if deal:
            return int(deal)
    waiting = db.scalar(select(Outbox.lead_id).where(
        Outbox.channel == "amocrm", Outbox.status == "pending", Outbox.id < item.id,
        Outbox.lead_id.in_([i for i, _ in rows])).limit(1))
    if waiting:
        raise Wait(60, f"waits for the amoCRM deal of request №{waiting}")
    return None


def _send_amocrm(item: Outbox, lead: Lead, db: Session, s: Settings, client: httpx.Client) -> None:
    """The deal with the contact, then the note with the request; a repeat request is only a note in the deal of the
    person's first request, and the deal's name counts the repeats («+2 повторных»). One contact per person: the one an
    earlier request made, else the one with this number. Each step is written to lead.details["amocrm"] at once and committed with the outbox row
    even when a later step fails: a retry goes on from there and never makes a second deal."""
    # read afresh and locked before anything is sent: an erasure in flight goes first (then this one finds the
    # person erased), and nothing else writes leads.details meanwhile
    lead = db.scalars(select(Lead).where(Lead.id == lead.id).with_for_update(of=Lead)
                      .execution_options(populate_existing=True)).first()
    if lead is None or lead.anonymised_at is not None:
        raise Permanent("the person was erased")
    state = dict((lead.details or {}).get("amocrm") or {})

    def save(**kw) -> None:
        state.update(kw)
        lead.details = {**(lead.details or {}), "amocrm": dict(state)}  # a new object: SQLAlchemy sees the change

    if not state.get("note"):  # else done by an earlier attempt (the row was revived by notify-retry)
        if not state.get("lead_id") and state.pop("creating", None):  # asked for the deal last time, no answer
            found = _amo_find_deal(s, client, lead)
            if found:
                save(lead_id=found[0], contact_id=found[1])
        if not state.get("lead_id") and item.event == "lead.repeat" and lead.parent_id:
            deal = _amo_first_deal(db, item, lead)
            if deal and _amo_get(s, client, "leads", deal):
                save(lead_id=deal, to_request=lead.parent_id)
            elif deal:  # the manager deleted that deal or declined it in «Неразобранное»: this request gets its own
                save(gone=deal)
        if not state.get("lead_id"):
            contact_id = _amo_known_contact(s, client, db, lead) or _amo_contact(s, client, lead.phone)
            save(creating=True)
            deal, contact_id = _amo_new_deal(s, client, lead, contact_id)
            state.pop("creating")
            save(lead_id=deal, contact_id=contact_id)
        _amo(s, client, "POST", f"leads/{int(state['lead_id'])}/notes",
             json=[{"note_type": "common", "params": {"text": amocrm_note(lead, item.event, s)}}])
        save(note=True)
    if item.event == "lead.repeat" and lead.parent_id and not state.get("counted"):
        _amo_mark_repeats(s, client, db, lead, int(state["lead_id"]))
        save(counted=True)


def _send(item: Outbox, db: Session, s: Settings, client: httpx.Client) -> None:
    lead = db.get(Lead, item.lead_id) if item.lead_id else None
    review = db.get(Review, item.review_id) if item.review_id else None
    if lead is None and review is None:
        raise Permanent("the request or review is gone")
    if lead is not None and lead.anonymised_at is not None:
        raise Permanent("the person was erased")
    if item.channel == "telegram":
        facts = visit_facts(db, lead) if lead is not None else None
        _send_telegram(item, telegram_text(lead, review, item.event, s, facts), s, client, parse_mode="HTML")
    elif item.channel == "email":
        _send_email(item, email_message(lead, review, item.event, s), s)
    elif item.channel == "amocrm":
        if lead is None:
            raise Permanent("amoCRM takes requests only")
        _send_amocrm(item, lead, db, s, client)
    else:
        _send_webhook(item, webhook_body(item, lead, review), s, client)


_BOT_TOKEN = re.compile(r"\d{5,}:[A-Za-z0-9_-]{10,}")
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{6,}(?:\.[A-Za-z0-9_-]*){0,2}")  # the amoCRM token, whole or cut


def _proxy_secrets(s: Settings) -> tuple[str, ...]:
    """The proxy address, its «login:password» and the password: none of them may show in an error."""
    if not s.telegram_proxy:
        return ()
    try:
        u = urlsplit(s.telegram_proxy)
        userinfo = u.netloc.rpartition("@")[0]
        return tuple(x for x in (s.telegram_proxy, userinfo, unquote(u.password or ""), u.password or "") if x)
    except ValueError:
        return (s.telegram_proxy,)


def _scrub(err: str, s: Settings) -> str:
    for secret in (s.telegram_bot_token, s.smtp_password, s.webhook_secret, s.amocrm_token, *_proxy_secrets(s)):
        if secret:
            err = err.replace(secret, "***")
    return _JWT.sub("***", _BOT_TOKEN.sub("***", err))[:500]


# ---------------------------------------------------------------- check of the settings (python -m app notify-test)
TEST_TELEGRAM_TEXT = ("Проверка уведомлений дом-щенков.рф: бот подключён. Так будут приходить новые заявки — номер, "
                      "порода и ссылка в админку, без имени и телефона.")


def _test_email_message(s: Settings) -> EmailMessage:
    m = EmailMessage()
    m["Subject"] = "Проверка уведомлений дом-щенков.рф"
    m["From"] = formataddr(("дом-щенков.рф", s.smtp_from or s.smtp_user))
    m["Message-ID"] = make_msgid(domain=(s.smtp_from or s.smtp_user or "localhost").split("@")[-1])
    m.set_content("Почта для заявок настроена: так будут приходить новые заявки с сайта дом-щенков.рф — с именем, "
                  "телефоном и ссылкой в админку.")
    return m


def _hint(channel: str, err: Exception, s: Settings) -> str:
    """What to fix, in the words of api.env, for the person who runs the check."""
    cause = err.__cause__ or err
    msg = str(err).lower()
    if channel == "amocrm":
        return amocrm_hint({"error": str(err), "network": isinstance(err.__cause__, httpx.HTTPError)})
    if channel == "telegram":
        if "telegram 401" in msg:
            return "токен не подходит: проверьте DSH_TELEGRAM_BOT_TOKEN (его выдаёт @BotFather)"
        if "telegram 400" in msg or "telegram 404" in msg:
            return "бот не видит этот чат: напишите боту /start или добавьте его в группу, проверьте DSH_TELEGRAM_CHAT_ID"
        if "telegram 403" in msg:
            return "бот заблокирован в этом чате или удалён из группы: разблокируйте или добавьте его снова"
        if s.telegram_proxy:
            return (f"прокси {proxy_label(s)} не отвечает или не пускает: проверьте DSH_TELEGRAM_PROXY — адрес, порт, "
                    "логин и пароль, и что прокси за пределами России")
        return ("нет ответа от api.telegram.org: если сервер в России, Telegram может быть закрыт — "
                "нужен прокси за рубежом, DSH_TELEGRAM_PROXY (DEPLOY.md)")
    if isinstance(cause, smtplib.SMTPAuthenticationError):
        return "почта не приняла логин или пароль: DSH_SMTP_USER — адрес ящика латиницей, DSH_SMTP_PASSWORD — пароль ящика"
    if isinstance(cause, (smtplib.SMTPSenderRefused, smtplib.SMTPRecipientsRefused)):
        return "почта не приняла адрес: DSH_SMTP_FROM должен совпадать с ящиком, проверьте и DSH_NOTIFY_EMAILS"
    if isinstance(cause, UnicodeEncodeError):
        return "логин и адреса пишутся латиницей: домен .рф — как xn----dtbefzjjef0i.xn--p1ai"
    if isinstance(cause, socket.gaierror):
        return f"сервер почты {s.smtp_host} не найден: проверьте DSH_SMTP_HOST"
    if isinstance(cause, ssl.SSLError):
        return "не удалось зашифровать соединение: для порта 465 нужно DSH_SMTP_SSL=true, для 587 и 2525 — false"
    if isinstance(cause, OSError) and not isinstance(cause, smtplib.SMTPException):
        return (f"нет соединения с {s.smtp_host}:{s.smtp_port}. На Timeweb Cloud порты 25, 465 и 587 закрыты по "
                f"умолчанию — откройте порт {s.smtp_port} в панели сервера («Закрытые порты»)")
    return "почтовый сервер отказал — подробности в скобках"


def send_test(s: Settings | None = None, client: httpx.Client | None = None) -> list[dict]:
    """One test message to every Telegram chat and mailbox of the settings, through the same senders as real
    notifications; amoCRM: the token is checked (no test deal — that is notify-check --send). No personal data,
    nothing in the database. → [{channel, target, ok, error, hint}]; [] when no channel is configured."""
    s = s or get_settings()
    results: list[dict] = []

    def fail(channel: str, target: str, hint: str) -> None:
        results.append({"channel": channel, "target": target, "ok": False, "error": "", "hint": hint})

    def attempt(channel: str, target: str, send) -> None:
        try:
            send()
            results.append({"channel": channel, "target": target, "ok": True, "error": "", "hint": ""})
        except Exception as e:  # noqa: BLE001 — every failure is shown to the person running the check
            results.append({"channel": channel, "target": target, "ok": False,
                            "error": _scrub(f"{type(e).__name__}: {e}", s), "hint": _hint(channel, e, s)})

    own = client is None
    client = client or http_client(s)
    try:
        chats = list(dict.fromkeys(c for v in (s.telegram_chat_id, *s.telegram_breed_chats.values()) for c in chat_list(v)))
        if s.telegram_bot_token or chats:
            if not s.telegram_bot_token:
                fail("telegram", "—", "нет DSH_TELEGRAM_BOT_TOKEN (токен от @BotFather)")
            elif not chats:
                fail("telegram", "—", "нет DSH_TELEGRAM_CHAT_ID (куда присылать заявки)")
            else:
                for chat in chats:
                    attempt("telegram", chat, lambda chat=chat: _send_telegram(
                        SimpleNamespace(target=chat), TEST_TELEGRAM_TEXT, s, client))
        if s.smtp_host or s.notify_emails:
            if not s.smtp_host:
                fail("email", "—", "нет DSH_SMTP_HOST (сервер исходящей почты)")
            elif not s.notify_emails:
                fail("email", "—", "нет DSH_NOTIFY_EMAILS (куда присылать заявки)")
            else:
                for to in s.notify_emails:
                    attempt("email", to, lambda to=to: _send_email(SimpleNamespace(target=to), _test_email_message(s), s))
        if s.amocrm_subdomain or s.amocrm_token:
            if not s.amocrm_enabled:
                fail("amocrm", s.amocrm_host or "—", "нужны оба: DSH_AMOCRM_SUBDOMAIN и DSH_AMOCRM_TOKEN")
            else:
                attempt("amocrm", s.amocrm_host, lambda: _amo(s, client, "GET", "account"))
    finally:
        if own:
            client.close()
    return results


def deliver_due(db: Session, limit: int = 20, client: httpx.Client | None = None) -> dict:
    """Send due notifications; each item is locked, sent and committed on its own."""
    s = get_settings()
    stats = {"sent": 0, "failed": 0, "retry": 0}
    own = client is None
    client = client or http_client(s)
    try:
        for _ in range(limit):
            now = dt.datetime.now(UTC)
            item = db.scalars(select(Outbox).where(Outbox.status == "pending", Outbox.next_attempt_at <= now)
                              .order_by(Outbox.next_attempt_at, Outbox.id).limit(1)
                              .with_for_update(skip_locked=True)).first()
            if item is None:
                break
            item.attempts += 1
            try:
                _send(item, db, s, client)
                item.status, item.sent_at, item.last_error = "sent", now, None
                stats["sent"] += 1
            except Exception as e:  # noqa: BLE001 — every failure is recorded and retried or given up
                item.last_error = _scrub(f"{type(e).__name__}: {e}", s)
                if isinstance(e, Wait):
                    item.attempts -= 1  # it waits its turn: not an attempt
                if isinstance(e, Permanent) or item.attempts >= s.notify_max_attempts:
                    item.status = "failed"
                    stats["failed"] += 1
                    log.error("outbox %s (%s) failed for good: %s", item.id, item.channel, item.last_error)
                else:
                    delay = dt.timedelta(seconds=e.seconds) if isinstance(e, RetryAfter) else _backoff(item.attempts)
                    item.next_attempt_at = now + delay
                    stats["retry"] += 1
                    if isinstance(e, Wait):
                        log.info("outbox %s (%s) %s", item.id, item.channel, e)
                    else:
                        log.warning("outbox %s (%s) attempt %s failed: %s", item.id, item.channel, item.attempts,
                                    item.last_error)
            db.commit()
    finally:
        if own:
            client.close()
    return stats


def retry_now(db: Session, client: httpx.Client | None = None, since: dt.timedelta = dt.timedelta(days=1)) -> dict:
    """After a fix (a port opened, a token corrected): the notifications that failed during the last day and the ones
    waiting for their next attempt go out now (`python -m app notify-retry`)."""
    now = dt.datetime.now(UTC)
    revived = db.execute(update(Outbox).where(Outbox.status == "failed", Outbox.created_at > now - since)
                         .values(status="pending", attempts=0, next_attempt_at=now, last_error=None)).rowcount
    db.execute(update(Outbox).where(Outbox.status == "pending").values(next_attempt_at=now))
    db.commit()
    return {"revived": revived, **deliver_due(db, limit=500, client=client)}


# ---------------------------------------------------------------- why a notification did not arrive (notify-status)
_NETWORK = re.compile(r"Connect|Timeout|timed out|Network|Name or service|Temporary failure|refused|unreachable", re.I)


def error_hint(channel: str, error: str | None, s: Settings | None = None) -> str:
    """What to fix for a recorded last_error (a string: the exception is long gone), in the words of api.env."""
    if not error:
        return ""
    s = s or get_settings()
    if channel == "amocrm":
        return amocrm_hint({"error": error, "network": bool(_NETWORK.search(error)) and "amoCRM 4" not in error})
    if channel == "telegram":
        return _hint("telegram", RuntimeError(error), s)
    if channel == "email":
        if "Authentication" in error or "535" in error:
            return ("почта не приняла логин или пароль: DSH_SMTP_USER — адрес ящика латиницей, "
                    "DSH_SMTP_PASSWORD — пароль ящика")
        if "Refused" in error or "550" in error or "553" in error:
            return "почта не приняла адрес: DSH_SMTP_FROM должен совпадать с ящиком, проверьте и DSH_NOTIFY_EMAILS"
        if _NETWORK.search(error) or "OSError" in error:
            return (f"нет соединения с {s.smtp_host}:{s.smtp_port}. На Timeweb Cloud порты 25, 465 и 587 закрыты по "
                    f"умолчанию — откройте порт {s.smtp_port} в панели сервера («Закрытые порты»)")
        return "почтовый сервер отказал — подробности выше"
    if _NETWORK.search(error):
        return "адрес вебхука не отвечает: проверьте DSH_WEBHOOK_URL"
    return "вебхук ответил ошибкой — подробности выше"


def recent(db: Session, limit: int = 15, days: int = 7) -> dict:
    """The last notifications, the newest first, and what happened to each channel over `days` — to see why a
    request did not reach Telegram or the mail (`python -m app notify-status`)."""
    since = dt.datetime.now(UTC) - dt.timedelta(days=days)
    rows = db.scalars(select(Outbox).order_by(Outbox.id.desc()).limit(limit)).all()
    totals: dict[str, dict[str, int]] = {}
    for channel, status, count in db.execute(select(Outbox.channel, Outbox.status, func.count())
                                             .where(Outbox.created_at > since).group_by(Outbox.channel, Outbox.status)):
        totals.setdefault(channel, {})[status] = count
    return {"rows": rows, "totals": totals}


# ---------------------------------------------------------------- setup checks (python -m app notify-check)
TEST_TEXT = ("Проверка уведомлений дом-щенков.рф: бот подключён. Сюда будут приходить новые заявки с сайта — "
             "номер, порода, что нужно и ссылка в админ-панель.")


def http_client(s: Settings | None = None) -> httpx.Client:
    """The client of every channel. With DSH_TELEGRAM_PROXY only the Telegram calls go through that proxy (a server
    where api.telegram.org is closed); the mail, amoCRM and the webhook go out directly."""
    s = s or get_settings()
    mounts = None
    if s.telegram_proxy:
        u = urlsplit(s.telegram_api_base)
        mounts = {f"{u.scheme}://{u.hostname}": httpx.HTTPTransport(proxy=s.telegram_proxy)}
    return httpx.Client(timeout=10, mounts=mounts)


def proxy_label(s: Settings) -> str:
    """«socks5://proxy.example:1080» — the proxy without its login and password, for messages."""
    if not s.telegram_proxy:
        return ""
    try:
        u = urlsplit(s.telegram_proxy)
        return f"{u.scheme}://{u.hostname}:{u.port}" if u.port else f"{u.scheme}://{u.hostname}"
    except ValueError:  # a malformed value is reported by the call itself
        return "(адрес не разобран)"


def mask_token(token: str) -> str:
    """«7012345678:AAH…» → «7012345678:***» — the bot id is public, the secret part is not."""
    return token.split(":", 1)[0] + ":***" if ":" in token else "***"


def telegram_targets(s: Settings) -> dict[str, str]:
    """{label: chat id} — the default chats and the per-breed chats (a list → «общий чат», «общий чат 2», …)."""
    out = {}
    for label, value in [("общий чат", s.telegram_chat_id),
                         *((f"порода {key}", v) for key, v in sorted(s.telegram_breed_chats.items()))]:
        for i, chat in enumerate(chat_list(value)):
            out[label + (f" {i + 1}" if i else "")] = chat
    return out


def _tg_call(s: Settings, client: httpx.Client, method: str, **params) -> dict:
    try:
        r = client.post(_tg_url(s, method), json=params)
        info = r.json() if r.content else {}
    except httpx.HTTPError as e:  # Telegram not reached at all: the token was not checked
        return {"ok": False, "network": True, "error": _scrub(f"{type(e).__name__}: {e}", s)}
    except ValueError as e:
        return {"ok": False, "error": _scrub(f"{type(e).__name__}: {e}", s)}
    if r.status_code == 200 and info.get("ok"):
        return {"ok": True, "result": info.get("result")}
    return {"ok": False, "error": _scrub(f"Telegram {r.status_code}: {info.get('description', r.text)}", s)[:200]}


def telegram_bot(s: Settings, client: httpx.Client) -> dict:
    """getMe: is the token valid, what is the bot's @username."""
    r = _tg_call(s, client, "getMe")
    if r["ok"]:
        me = r["result"] or {}
        return {"ok": True, "username": me.get("username", ""), "name": me.get("first_name", "")}
    return r


def telegram_chats_seen(s: Settings, client: httpx.Client) -> dict:
    """getUpdates: the chats where the bot was added or got a message — to find the chat id after adding the bot
    to a group. Telegram keeps updates for 24 hours; nothing is consumed (no offset)."""
    r = _tg_call(s, client, "getUpdates", timeout=0,
                 allowed_updates=["message", "channel_post", "my_chat_member", "chat_member"])
    if not r["ok"]:
        return r
    chats: dict[str, dict] = {}
    for upd in r["result"] or []:
        for key in ("message", "channel_post", "my_chat_member", "chat_member", "edited_message"):
            chat = (upd.get(key) or {}).get("chat")
            if chat and "id" in chat:
                title = chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) \
                    or ("@" + chat["username"] if chat.get("username") else "")
                chats[str(chat["id"])] = {"id": str(chat["id"]), "type": chat.get("type", ""), "title": title}
    return {"ok": True, "chats": list(chats.values())}


def telegram_chat(s: Settings, client: httpx.Client, chat_id: str) -> dict:
    """getChat: the id is right and the bot is in the chat."""
    r = _tg_call(s, client, "getChat", chat_id=chat_id)
    if r["ok"]:
        c = r["result"] or {}
        return {"ok": True, "type": c.get("type", ""), "title": c.get("title") or c.get("first_name") or ""}
    return r


def telegram_send_test(s: Settings, client: httpx.Client, chat_id: str) -> dict:
    r = _tg_call(s, client, "sendMessage", chat_id=chat_id, text=TEST_TEXT, disable_web_page_preview=True)
    return {"ok": True} if r["ok"] else r


TEST_AMOCRM_DEAL = "Проверка интеграции с сайтом дом-щенков.рф — можно удалить"
TEST_AMOCRM_NOTE = ("Тестовая сделка из проверки настроек сайта дом-щенков.рф (notify-check --send). Так будут "
                    "приходить заявки с сайта: сделка с контактом и примечание со всеми подробностями. Удалите её.")


def amocrm_deal_url(s: Settings, deal_id: int) -> str:
    return f"https://{s.amocrm_host}/leads/detail/{int(deal_id)}"


def _amo_call(s: Settings, client: httpx.Client, method: str, path: str, **kw) -> dict:
    try:
        r = _amo(s, client, method, path, **kw)
        return {"ok": True, "result": r.json() if r.content else {}}
    except Exception as e:  # noqa: BLE001 — reported to the person running the check, never raised
        return {"ok": False, "network": isinstance(e.__cause__, httpx.HTTPError), "error": _scrub(str(e), s)}


def amocrm_hint(r: dict) -> str:
    """What to fix, in the words of api.env, for a failed amoCRM call."""
    err = r.get("error", "")
    if r.get("network"):
        return "сервер не достаёт до amoCRM: проверьте DSH_AMOCRM_SUBDOMAIN и интернет на сервере"
    if "amoCRM 401" in err:
        return ("токен не принят (отозван или истёк срок): выпустите новый долгосрочный токен — amoCRM → amoМаркет → "
                "ваша интеграция → «Ключи и доступы» — и впишите его в DSH_AMOCRM_TOKEN")
    if "amoCRM 402" in err:
        return "аккаунт amoCRM не оплачен: после оплаты заявки пойдут снова (dsh app notify-retry)"
    if "amoCRM 403" in err:
        return "amoCRM не пускает: у пользователя токена нет прав или аккаунт заблокирован"
    if "amoCRM 404" in err:
        return "такого аккаунта нет: проверьте DSH_AMOCRM_SUBDOMAIN (из адреса https://<поддомен>.amocrm.ru)"
    if "amoCRM 400" in err:
        return "amoCRM не принял сделку: проверьте id воронки, этапа и ответственного (список выше)"
    return "amoCRM ответил ошибкой — подробности в скобках, попробуйте ещё раз"


def amocrm_account(s: Settings, client: httpx.Client) -> dict:
    """GET account: the token works, the account's name."""
    r = _amo_call(s, client, "GET", "account")
    if r["ok"]:
        a = r["result"] or {}
        return {"ok": True, "name": a.get("name", ""), "id": a.get("id")}
    return r


def _stage_kind(status: dict) -> str:
    if status.get("id") == 142:
        return "успешно реализовано — закрывает сделку"
    if status.get("id") == 143:
        return "закрыто и не реализовано — закрывает сделку"
    return "неразобранное" if status.get("type") == 1 else ""


def amocrm_pipelines(s: Settings, client: httpx.Client) -> dict:
    """GET leads/pipelines: every pipeline with its stages and their ids (for DSH_AMOCRM_PIPELINE_ID / _STATUS_ID)."""
    r = _amo_call(s, client, "GET", "leads/pipelines")
    if not r["ok"]:
        return r
    out = []
    for p in ((r["result"] or {}).get("_embedded") or {}).get("pipelines") or []:
        stages = [{"id": st.get("id"), "name": st.get("name", ""), "kind": _stage_kind(st)}
                  for st in (p.get("_embedded") or {}).get("statuses") or []]
        out.append({"id": p.get("id"), "name": p.get("name", ""), "is_main": bool(p.get("is_main")),
                    "statuses": stages})
    return {"ok": True, "pipelines": out}


def amocrm_target(s: Settings, pipelines: list[dict]) -> dict:
    """Where new deals go, checked against the account → {"pipeline", "status", "problems"}. Without a pipeline id
    amoCRM takes the main pipeline; without a stage id, the first stage of the pipeline; with DSH_AMOCRM_UNSORTED,
    its «Неразобранное»."""
    problems = []
    if s.amocrm_pipeline_id is None:
        pipe = next((p for p in pipelines if p["is_main"]), pipelines[0] if pipelines else None)
    else:
        pipe = next((p for p in pipelines if p["id"] == s.amocrm_pipeline_id), None)
        if pipe is None:
            problems.append(f"воронки {s.amocrm_pipeline_id} нет в аккаунте: проверьте DSH_AMOCRM_PIPELINE_ID")
    status = None
    if s.amocrm_unsorted and pipe is not None:
        status = next((st for st in pipe["statuses"] if st["kind"] == "неразобранное"), None)
        if status is None:
            problems.append(f"в воронке «{pipe['name']}» выключено «Неразобранное»: включите его в настройках воронки "
                            "в amoCRM или уберите DSH_AMOCRM_UNSORTED")
    elif s.amocrm_status_id is not None and pipe is not None:
        status = next((st for st in pipe["statuses"] if st["id"] == s.amocrm_status_id), None)
        if status is None:
            other = next((p for p in pipelines if any(st["id"] == s.amocrm_status_id for st in p["statuses"])), None)
            where = (f" (этот этап — из воронки «{other['name']}», её id {other['id']} впишите в "
                     "DSH_AMOCRM_PIPELINE_ID)" if other else "")
            problems.append(f"этапа {s.amocrm_status_id} нет в воронке «{pipe['name']}»: проверьте "
                            f"DSH_AMOCRM_STATUS_ID{where}")
        elif status["id"] in (142, 143):
            problems.append(f"этап «{status['name']}» закрывает сделку: для новых заявок выберите рабочий этап "
                            "(DSH_AMOCRM_STATUS_ID)")
        elif status["kind"] == "неразобранное":
            problems.append(f"в «{status['name']}» сделки попадают только как заявки: впишите DSH_AMOCRM_UNSORTED=1 "
                            "вместо DSH_AMOCRM_STATUS_ID")
    return {"pipeline": pipe, "status": status, "problems": problems}


def amocrm_send_test(s: Settings, client: httpx.Client) -> dict:
    """A clearly marked test deal with the contact «Тест» (no phone, no personal data) and a note, in the configured
    pipeline and stage → {"ok", "lead_id", "url"}."""
    form = {"form_id": "site-check", "form_name": "Проверка интеграции", "form_page": _site_url(s) + "/",
            "form_sent_at": int(time.time())}
    r = _amo_call(s, client, "POST", "leads/complex",
                  json=[_amo_deal(s, TEST_AMOCRM_DEAL, [*s.amocrm_tags, "проверка"], {"first_name": "Тест"}, form)])
    if not r["ok"]:
        return r
    try:
        deal = int(r["result"][0]["id"])
    except (KeyError, IndexError, TypeError, ValueError):
        return {"ok": False, "error": f"amoCRM не вернул номер сделки: {str(r['result'])[:200]}"}
    n = _amo_call(s, client, "POST", f"leads/{deal}/notes",
                  json=[{"note_type": "common", "params": {"text": TEST_AMOCRM_NOTE}}])
    return {**n, "lead_id": deal, "url": amocrm_deal_url(s, deal)}


def _smtp_connect(s: Settings):
    if s.smtp_ssl:
        return smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15, context=ssl.create_default_context())
    c = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
    c.starttls(context=ssl.create_default_context())
    return c


def smtp_check(s: Settings, send_to: list[str] | None = None) -> dict:
    """Connect and log in; with send_to, also send a test letter to those addresses."""
    try:
        with _smtp_connect(s) as c:
            if s.smtp_user:
                c.login(s.smtp_user, s.smtp_password)
            for addr in send_to or []:
                m = EmailMessage()
                m["Subject"] = "Проверка уведомлений дом-щенков.рф"
                m["From"] = formataddr(("дом-щенков.рф", s.smtp_from or s.smtp_user))
                m["To"] = addr
                m["Message-ID"] = make_msgid(domain=(s.smtp_from or s.smtp_user or "localhost").split("@")[-1])
                m.set_content("Почта для заявок подключена. На этот адрес будут приходить новые заявки с сайта "
                              "дом-щенков.рф: имя, телефон, куда написать, порода и ссылка в админ-панель.")
                c.send_message(m)
        return {"ok": True}
    except Exception as e:  # noqa: BLE001 — any failure is reported, never raised
        return {"ok": False, "error": _scrub(f"{type(e).__name__}: {e}", s)}
