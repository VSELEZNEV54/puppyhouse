#!/usr/bin/env python3
"""What is still a placeholder on the site, by how much it matters for the launch.

  blocking  — the law needs it before the site takes real requests: the operator in the consent texts (152-ФЗ ст. 9:
              name and address of the operator), the privacy policy, the requisites in the footer, the address on «Контакты».
              NB: a consent version is fixed in the database on the first deploy (migrate refuses an edited
              version), so fill these BEFORE the first production deploy — or add a new version afterwards.
  contacts  — the phone, e-mail, messenger links and the address visitors use to reach you
  content   — puppies' parents and weights, delivery times, blog links… (fine to fill step by step)

  python3 tools/check_launch.py              report; exit 0
  python3 tools/check_launch.py --strict     exit 1 if anything blocking is left
  python3 tools/check_launch.py --md FILE    also write the checklist as Markdown
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "src" / "data"
BRACKET = re.compile(r"\[[^\[\]\n\"]{2,90}\]")
FAKE_PHONE = re.compile(r"74951234567|123-45-67")

# (file, top-level key or None for the whole file) → group, what it is, the page it is on (None: every page).
# A page that is not published yet (src/data/publish.json) does not block the launch: its rule counts as content.
RULES = [
    ("consent.json", "versions", "blocking", "Согласия на обработку ПД: оператор, почта для отзыва согласия", "/soglasie/"),
    ("delivery-service.json", "privacy", "blocking", "Политика конфиденциальности: оператор, почта, сроки, меры защиты",
     "/politika-konfidencialnosti/"),
    ("site.json", "footer", "blocking", "Подвал каждой страницы: ФИО / наименование, ИНН, ОГРН(ИП)", None),
    ("delivery-service.json", "contacts", "blocking", "Страница «Контакты»: адрес и как приехать", "/kontakty/"),
    ("site.json", "email", "contacts", "Почта для связи", None),
    ("site.json", "address", "contacts", "Адрес питомника", None),
    ("site.json", "messengers", "contacts", "Ссылки Telegram, MAX", None),
    ("site.json", "ratings", "contacts", "Ссылки на карточки в Яндексе, Google, Авито", None),
]


def published() -> set[str] | None:
    """Pages of the current stage (src/data/publish.json); None — no staged release, everything is published."""
    p = DATA / "publish.json"
    if not p.is_file():
        return None
    pages = json.loads(p.read_text(encoding="utf-8")).get("pages") or []
    return set(pages)


def is_published(url: str | None, pages: set[str] | None) -> bool:
    if url is None or pages is None:
        return True
    return url in pages or any(p.endswith("*") and url.startswith(p[:-1]) for p in pages)
SKIP_KEYS = {"placeholders"}  # site.json: the list of placeholders itself


def scan(value, found: list[str]):
    if isinstance(value, dict):
        for k, v in value.items():
            if not k.startswith("_") and k not in SKIP_KEYS and not k.endswith("_placeholder"):
                scan(v, found)
    elif isinstance(value, list):
        for v in value:
            scan(v, found)
    elif isinstance(value, str):
        found.extend(BRACKET.findall(value))


def collect() -> dict:
    groups = {"blocking": [], "contacts": [], "content": []}
    claimed = collections.defaultdict(set)
    pages = published()
    for fn, key, group, what, url in RULES:
        if not is_published(url, pages):
            group, what = "content", what + f" (страница {url} ещё не выложена)"
        data = json.loads((DATA / fn).read_text(encoding="utf-8"))
        found: list[str] = []
        value = data.get(key)
        if fn == "consent.json":  # only the versions the site shows now; older ones are history, never edited
            value = [v for v in value if v["version"] in data["current"].values()]
        scan(value, found)
        if fn == "site.json" and key == "messengers":
            found += [v["url_placeholder"] for v in data["messengers"].values() if v.get("url_placeholder")]
        if found:
            groups[group].append({"file": f"src/data/{fn}", "key": key, "what": what, "count": len(found),
                                  "examples": sorted(set(found))[:6]})
        claimed[fn].add(key)
    site = json.loads((DATA / "site.json").read_text(encoding="utf-8"))
    phones = [site["phone"]["display"], site["phone"]["tel"], site["messengers"]["whatsapp"]["url"]]
    if any(FAKE_PHONE.search(p) for p in phones):
        groups["contacts"].insert(0, {"file": "src/data/site.json", "key": "phone", "count": 1,
                                      "what": "Телефон и WhatsApp — сейчас образец +7 (495) 123-45-67",
                                      "examples": [site["phone"]["display"]]})
    for p in sorted(DATA.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        rest = {k: v for k, v in data.items() if k not in claimed.get(p.name, set())} if isinstance(data, dict) else data
        found: list[str] = []
        scan(rest, found)
        if found:
            groups["content"].append({"file": f"src/data/{p.name}", "key": None, "count": len(found),
                                      "what": "Контент", "examples": [m for m, _ in collections.Counter(found).most_common(5)]})
    return groups


TITLES = {"blocking": "Обязательно до приёма реальных заявок (152-ФЗ)", "contacts": "Контакты",
          "content": "Контент (можно заполнять постепенно)"}


def as_text(groups: dict) -> str:
    lines = []
    for g in ("blocking", "contacts", "content"):
        items = groups[g]
        total = sum(i["count"] for i in items)
        lines.append(f"{TITLES[g]}: {total or 'всё заполнено'}")
        for i in items:
            where = i["file"] + (f" → {i['key']}" if i["key"] else "")
            lines.append(f"  - {i['what']} ({i['count']}): {where}; например {', '.join(i['examples'][:4])}")
    return "\n".join(lines)


def as_markdown(groups: dict) -> str:
    out = ["# Что заполнить перед запуском", "",
           "Список собран автоматически (`python3 tools/check_launch.py`). Значения в [квадратных скобках] видны "
           "посетителям как есть.", ""]
    for g in ("blocking", "contacts", "content"):
        out.append(f"## {TITLES[g]}")
        if not groups[g]:
            out += ["", "Всё заполнено.", ""]
            continue
        out.append("")
        for i in groups[g]:
            where = i["file"] + (f" → `{i['key']}`" if i["key"] else "")
            out.append(f"- [ ] {i['what']} — {i['count']} шт., {where}. Например: {', '.join(i['examples'][:4])}")
        out.append("")
    out += ["Согласия (`consent.json`) фиксируются в базе при первом деплое. Если править их после, нужно добавить "
            "новую версию и переключить `current`, иначе миграция откажется запускаться.", ""]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strict", action="store_true", help="exit 1 if anything blocking is left")
    ap.add_argument("--md", help="write the checklist as Markdown to this file")
    ap.add_argument("--quiet", action="store_true", help="print one summary line")
    args = ap.parse_args(argv)
    groups = collect()
    if args.md:
        Path(args.md).write_text(as_markdown(groups), encoding="utf-8")
    counts = {g: sum(i["count"] for i in groups[g]) for g in groups}
    if args.quiet:
        print(f"заглушки: обязательные {counts['blocking']}, контакты {counts['contacts']}, контент {counts['content']}")
    else:
        print(as_text(groups))
    return 1 if args.strict and counts["blocking"] else 0


if __name__ == "__main__":
    sys.exit(main())
