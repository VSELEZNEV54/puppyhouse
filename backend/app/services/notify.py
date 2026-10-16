"""Manager notifications through the outbox.

Channels (each is optional, configured in .env):
- telegram — chat per breed. Telegram is outside Russia, so by default a message carries NO personal data:
  «№123 · Мальтипу · Цена щенка · 14:32» + a link to the admin panel. Plain text, no markup.
- email    — full details (name, phone, «куда написать») over SMTP of a Russian provider to the kennel's mailbox.
- webhook  — {event, id, public_id, at}, HMAC-signed; the receiver (the admin panel) pulls the details with its key.

enqueue_*() runs inside the request transaction (the lead and its notifications commit together).
deliver_due() sends what is due: right after the request (background task), and in a loop in the worker
(`python -m app worker`). Safe in several processes at once (FOR UPDATE SKIP LOCKED)."""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import smtplib
import ssl
import zoneinfo
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..enums import CHANNEL_LABELS, LEAD_KIND_LABELS, Channel, LeadKind
from ..models import Lead, Outbox, Review
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


def _targets(s: Settings, breed_key: str | None) -> list[tuple[str, str]]:
    out = []
    if s.telegram_bot_token:
        chat = s.telegram_breed_chats.get(breed_key or "", "") or s.telegram_chat_id
        if chat:
            out.append(("telegram", chat))
    if s.smtp_host:
        out.extend(("email", addr[:300]) for addr in s.notify_emails)  # one row per address
    if s.webhook_url:
        out.append(("webhook", s.webhook_url))
    return out


def enqueue_lead(db: Session, lead: Lead, event: str = "lead.created",
                 channels: tuple[str, ...] = ("telegram", "email", "webhook")) -> list[str]:
    s = get_settings()
    out = []
    for channel, target in _targets(s, lead.breed.key if lead.breed else None):
        if channel not in channels:
            continue
        if channel != "webhook" and event not in ("lead.created", "lead.repeat"):
            continue  # people are pinged about requests; the webhook hears every change
        db.add(Outbox(channel=channel, target=target, event=event, lead_id=lead.id))
        out.append(channel)
    return out


def enqueue_review(db: Session, review: Review) -> list[str]:
    s = get_settings()
    out = []
    for channel, target in _targets(s, review.breed.key if review.breed else None):
        db.add(Outbox(channel=channel, target=target, event="review.created", review_id=review.id))
        out.append(channel)
    return out


# ---------------------------------------------------------------- message bodies
def _local(t: dt.datetime, s: Settings) -> dt.datetime:
    return t.astimezone(zoneinfo.ZoneInfo(s.timezone))


def _admin_link(s: Settings, lead_id: int) -> str:
    return s.admin_base_url.format(id=lead_id) if s.admin_base_url else ""


def telegram_text(lead: Lead | None, review: Review | None, event: str, s: Settings) -> str:
    """Plain text. Personal data only if telegram_include_pd (needs a cross-border transfer notice)."""
    if review is not None:
        lines = [f"Новый отзыв №{review.id} · {'★' * review.rating}", "Ждёт модерации"]
        if review.breed:
            lines.insert(1, review.breed.name)
        return "\n".join(lines)
    num = lead.parent_id or lead.id
    kind = LEAD_KIND_LABELS.get(LeadKind(lead.kind), lead.kind)
    head = f"Повторный запрос по заявке №{num}" if event == "lead.repeat" else f"Новая заявка №{lead.id}"
    breed = lead.breed.name if lead.breed else "порода не выбрана"
    lines = [head, f"{breed} · {kind} · {_local(lead.created_at, s):%H:%M}"]
    if lead.puppy_name:
        lines.append(f"Щенок: {lead.puppy_name}")
    if s.telegram_include_pd:
        lines.append(f"{lead.name}, {phones.display(lead.phone)}, "
                     f"{CHANNEL_LABELS.get(Channel(lead.channel), lead.channel)}")
    link = _admin_link(s, num)
    if link:
        lines.append(link)
    return "\n".join(lines)


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
        body = [
            f"{title} · {when:%d.%m.%Y %H:%M}",
            "",
            f"Имя: {lead.name}",
            f"Телефон: {phones.display(lead.phone)}",
            f"Куда написать: {CHANNEL_LABELS.get(Channel(lead.channel), lead.channel)}",
            f"Порода: {breed}",
            f"Что нужно: {kind}",
        ]
        if lead.puppy_name:
            body.append(f"Щенок: {lead.puppy_name}")
        if lead.colour:
            body.append(f"Окрас: {lead.colour}")
        if lead.note:
            body.append(f"Пометка формы: {lead.note}")
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
    m["From"] = formataddr(("домщенков.рф", s.smtp_from or s.smtp_user))
    m["Message-ID"] = make_msgid(domain=(s.smtp_from or s.smtp_user or "localhost").split("@")[-1])
    m.set_content("\n".join(body))
    return m


def webhook_body(item: Outbox, lead: Lead | None, review: Review | None) -> bytes:
    """No personal data: the receiver pulls the record by id with its API key."""
    subject = ({"type": "lead", "id": lead.id, "public_id": str(lead.public_id), "parent_id": lead.parent_id}
               if lead is not None else {"type": "review", "id": review.id})
    return json.dumps({"event": item.event, "delivery": item.id, "at": dt.datetime.now(UTC).isoformat(),
                       **subject}, ensure_ascii=False).encode()


# ---------------------------------------------------------------- delivery
def _backoff(attempts: int) -> dt.timedelta:
    return dt.timedelta(seconds=min(30 * 2 ** max(attempts - 1, 0), 6 * 3600))  # 30 s, 1 min, 2 min … 6 h


def _send_telegram(item: Outbox, text: str, s: Settings, client: httpx.Client) -> None:
    r = client.post(f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
                    json={"chat_id": item.target, "text": text, "disable_web_page_preview": True})
    if r.status_code == 200:
        return
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


def _send(item: Outbox, db: Session, s: Settings, client: httpx.Client) -> None:
    lead = db.get(Lead, item.lead_id) if item.lead_id else None
    review = db.get(Review, item.review_id) if item.review_id else None
    if lead is None and review is None:
        raise Permanent("the request or review is gone")
    if lead is not None and lead.anonymised_at is not None:
        raise Permanent("the person was erased")
    if item.channel == "telegram":
        _send_telegram(item, telegram_text(lead, review, item.event, s), s, client)
    elif item.channel == "email":
        _send_email(item, email_message(lead, review, item.event, s), s)
    else:
        _send_webhook(item, webhook_body(item, lead, review), s, client)


_BOT_TOKEN = re.compile(r"\d{5,}:[A-Za-z0-9_-]{10,}")


def _scrub(err: str, s: Settings) -> str:
    for secret in (s.telegram_bot_token, s.smtp_password, s.webhook_secret):
        if secret:
            err = err.replace(secret, "***")
    return _BOT_TOKEN.sub("***", err)[:500]


def deliver_due(db: Session, limit: int = 20, client: httpx.Client | None = None) -> dict:
    """Send due notifications; each item is locked, sent and committed on its own."""
    s = get_settings()
    stats = {"sent": 0, "failed": 0, "retry": 0}
    own = client is None
    client = client or httpx.Client(timeout=10)
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
                if isinstance(e, Permanent) or item.attempts >= s.notify_max_attempts:
                    item.status = "failed"
                    stats["failed"] += 1
                    log.error("outbox %s (%s) failed for good: %s", item.id, item.channel, item.last_error)
                else:
                    delay = dt.timedelta(seconds=e.seconds) if isinstance(e, RetryAfter) else _backoff(item.attempts)
                    item.next_attempt_at = now + delay
                    stats["retry"] += 1
                    log.warning("outbox %s (%s) attempt %s failed: %s", item.id, item.channel, item.attempts,
                                item.last_error)
            db.commit()
    finally:
        if own:
            client.close()
    return stats
