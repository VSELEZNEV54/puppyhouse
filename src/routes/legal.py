"""Legal documents (group «legal»): the consent pages /soglasie/ and /soglasie-na-publikaciyu/.
152-ФЗ (ст. 9 and 10.1, as amended on 01.09.2025): the consent is a separate document, not a line in the privacy policy.
Copy: src/data/consent.json — one source for these pages, the form checkboxes (forms.consent_check) and the backend
(a published version is never edited: add a new version and switch `current`). This module renders the CURRENT version
of each kind at its url. Owns: src/routes/legal.py, src/templates/legal/, assets/css/legal.css."""

import datetime as dt
import re

from _lib import crumbs

BRAND = " | домщенков.рф"
TITLE_MAX, DESC_MAX = 60, 160
LAW = {"processing": "№ 152-ФЗ, ст. 9", "review": "№ 152-ФЗ, ст. 9", "distribution": "№ 152-ФЗ, ст. 10.1"}
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]
DESCRIPTION = {
    "processing": "Согласие на обработку персональных данных для заявок на сайте домщенков.рф: цели, какие данные, "
                  "сроки и как отозвать согласие.",
    "review": "Согласие на обработку персональных данных для отзыва на сайте домщенков.рф: цели, какие данные, сроки "
              "и как отозвать согласие.",
    "distribution": "Согласие на публикацию отзыва на сайте домщенков.рф: что публикуется, где и как снять отзыв с сайта.",
}


def version_date(version):
    """«processing-2026-10-16» → «2026-10-16» (the date a version was published), or None. A second edition of the
    same day: «processing-2026-10-20-2» → «2026-10-20»."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})(?:-\d+)?$", version)
    return m.group(1) if m else None


def ru_date(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d.day}\u00a0{MONTHS_GEN[d.month - 1]} {d.year}"


def routes(data):
    consent = data["consent"]
    versions = {v["version"]: v for v in consent["versions"]}
    current = consent["current"]
    out = []
    for kind, ver in current.items():
        doc = versions[ver]
        title = doc.get("short_title", doc["title"]) + BRAND  # <title> ≤ 60 characters
        description = DESCRIPTION.get(kind, doc["title"])
        if len(title) > TITLE_MAX or len(description) > DESC_MAX:
            raise ValueError(f"{doc['url']}: title or description too long")
        date = version_date(ver)
        facts = ([{"label": "Редакция", "value": ru_date(date)}] if date else []) + [
            {"label": "Закон", "value": LAW.get(kind, "№ 152-ФЗ")},
            {"label": "Как дать", "value": "Отметка в форме"},
        ] + ([{"label": "Как отозвать", "value": "Письмо на " + data["site"]["email"]}]
             if "[" not in data["site"].get("email", "[") else [])
        out.append(dict(
            url=doc["url"],
            template="legal/consent.html.j2",
            context=dict(
                title=title,
                description=description,
                breadcrumbs=crumbs((doc["title"], None)),
                doc=doc,
                date=date,
                facts=facts,
                others=[versions[v] for k, v in current.items() if k != kind],
                pups_strip=False,
            ),
        ))
    return out
