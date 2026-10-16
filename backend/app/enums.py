"""Closed value sets. Stored as text with named CHECK constraints (easier to extend than PostgreSQL ENUM types).
Labels are what the admin panel shows; GET /api/v1/admin/meta returns them, so the panel never hard-codes them."""
from __future__ import annotations

from enum import StrEnum


class LeadKind(StrEnum):
    lead = "lead"              # final form at the bottom of a page («Подберём щенка за 1 час»)
    price = "price"            # «Узнать цену» without a puppy
    puppy = "puppy"            # «Узнать цену» on a puppy card or puppy page
    consult = "consult"        # «Получить консультацию»
    colour = "colour"          # «Подобрать кремового мальтипу», questions about a colour
    help = "help"              # «Помочь с выбором»
    waitlist = "waitlist"      # «Лист ожидания» (a reserved puppy or a breed without puppies)
    video_call = "video_call"  # «Видеозвонок со щенком»
    litter = "litter"          # «Узнать о следующем помёте»
    shop = "shop"              # «Стартовый набор»
    other = "other"


LEAD_KIND_LABELS = {
    LeadKind.lead: "Заявка с формы внизу страницы",
    LeadKind.price: "Узнать цену",
    LeadKind.puppy: "Цена конкретного щенка",
    LeadKind.consult: "Консультация",
    LeadKind.colour: "Подбор по окрасу",
    LeadKind.help: "Помощь с выбором",
    LeadKind.waitlist: "Лист ожидания",
    LeadKind.video_call: "Видеозвонок со щенком",
    LeadKind.litter: "Следующий помёт",
    LeadKind.shop: "Стартовый набор",
    LeadKind.other: "Другое",
}


class LeadStatus(StrEnum):
    new = "new"
    no_answer = "no_answer"
    in_progress = "in_progress"
    waitlist = "waitlist"
    reserved = "reserved"
    won = "won"
    lost = "lost"
    duplicate = "duplicate"    # a repeat request attached to an open lead of the same person (parent_id)
    spam = "spam"


# label, colour for the panel, closed?
LEAD_STATUS_META = {
    LeadStatus.new: ("Новая", "#FF967C", False),
    LeadStatus.no_answer: ("Не дозвонились", "#FFD66B", False),
    LeadStatus.in_progress: ("В работе", "#8EC1FF", False),
    LeadStatus.waitlist: ("Лист ожидания", "#BEA9FF", False),
    LeadStatus.reserved: ("Бронь", "#7FD8AC", False),
    LeadStatus.won: ("Продан", "#3FA66B", True),
    LeadStatus.lost: ("Отказ", "#9A9A9A", True),
    LeadStatus.duplicate: ("Повторный запрос", "#C9C4BC", True),
    LeadStatus.spam: ("Спам", "#6B6B6B", True),
}
LEAD_STATUS_LABELS = {k: v[0] for k, v in LEAD_STATUS_META.items()}
OPEN_STATUSES = tuple(k for k, v in LEAD_STATUS_META.items() if not v[2])
CLOSED_STATUSES = tuple(k for k, v in LEAD_STATUS_META.items() if v[2])


class LostReason(StrEnum):
    expensive = "expensive"
    bought_elsewhere = "bought_elsewhere"
    no_response = "no_response"
    changed_mind = "changed_mind"
    no_match = "no_match"
    other = "other"


LOST_REASON_LABELS = {
    LostReason.expensive: "Дорого",
    LostReason.bought_elsewhere: "Купили в другом месте",
    LostReason.no_response: "Не отвечает",
    LostReason.changed_mind: "Передумали",
    LostReason.no_match: "Нет нужного окраса или пола",
    LostReason.other: "Другое",
}


class Origin(StrEnum):
    """Where the request came in. Public forms are always site_form; managers pick one for manual leads."""
    site_form = "site_form"
    phone = "phone"
    telegram = "telegram"
    whatsapp = "whatsapp"
    max = "max"
    avito = "avito"
    instagram = "instagram"
    referral = "referral"
    other = "other"


ORIGIN_LABELS = {
    Origin.site_form: "Форма на сайте", Origin.phone: "Звонок", Origin.telegram: "Telegram",
    Origin.whatsapp: "WhatsApp", Origin.max: "MAX", Origin.avito: "Авито", Origin.instagram: "Instagram",
    Origin.referral: "По рекомендации", Origin.other: "Другое",
}


class Channel(StrEnum):
    """Where the person asked us to reply («Куда написать» in the form)."""
    telegram = "telegram"
    whatsapp = "whatsapp"
    max = "max"
    call = "call"


CHANNEL_LABELS = {Channel.telegram: "Telegram", Channel.whatsapp: "WhatsApp", Channel.max: "MAX", Channel.call: "Звонок"}


class SpamReason(StrEnum):
    honeypot = "honeypot"
    too_fast = "too_fast"
    rate_limited = "rate_limited"
    blocked_contact = "blocked_contact"
    manual = "manual"


class EventType(StrEnum):
    page_view = "page_view"            # data: {title}
    form_open = "form_open"            # data: {kind, form, puppy, colour}
    contact_click = "contact_click"    # data: {channel: telegram|whatsapp|max|phone|email, place}
    quiz_complete = "quiz_complete"    # data: {winner, second, answers{key: option}}


EVENT_LABELS = {
    EventType.page_view: "Просмотр страницы",
    EventType.form_open: "Открыл форму",
    EventType.contact_click: "Нажал на контакт",
    EventType.quiz_complete: "Прошёл тест подбора породы",
}


class ReviewStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    withdrawn = "withdrawn"    # the author asked to stop publication (ст. 10.1 152-ФЗ: within 3 working days)


REVIEW_STATUS_LABELS = {ReviewStatus.pending: "На модерации", ReviewStatus.approved: "Опубликован",
                        ReviewStatus.rejected: "Отклонён", ReviewStatus.withdrawn: "Снят по просьбе автора"}


class ErasureReason(StrEnum):
    withdrawal = "withdrawal"  # отзыв согласия
    request = "request"        # требование субъекта
    retention = "retention"    # истёк срок хранения
    not_me = "not_me"          # номер указал другой человек


ERASURE_REASON_LABELS = {ErasureReason.withdrawal: "Отзыв согласия", ErasureReason.request: "Требование субъекта",
                         ErasureReason.retention: "Истёк срок хранения", ErasureReason.not_me: "Чужой номер"}


class Role(StrEnum):
    admin = "admin"      # everything: users, API keys, export, erasure
    manager = "manager"  # leads, contacts, reviews


class HistoryAction(StrEnum):
    created = "created"
    repeat = "repeat"          # the same person sent another request; it was attached to this lead
    status = "status"
    assignee = "assignee"
    breed = "breed"
    puppy = "puppy"
    next_contact = "next_contact"
    comment = "comment"
    edit = "edit"
    merged = "merged"


class PuppyStatus(StrEnum):
    available = "available"
    reserved = "reserved"
    soon = "soon"
    sold = "sold"        # set by the catalog sync when a puppy disappears from puppies.json


def check(column: str, enum: type[StrEnum], nullable: bool = False) -> str:
    """SQL for a CHECK constraint: column IN (...)."""
    sql = f"{column} IN ({', '.join(repr(e.value) for e in enum)})"
    return f"{column} IS NULL OR {sql}" if nullable else sql
