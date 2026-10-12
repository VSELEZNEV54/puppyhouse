"""Puppy pages /shchenki/<slug>/ — one conversion page per puppy in puppies.json.
Owns: src/routes/puppy.py, src/templates/puppy/, assets/css/puppy.css, assets/js/puppy.js."""

import datetime as dt

from _lib import crumbs

NBSP = " "
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]
TITLE_MAX, DESC_MAX = 60, 160
BRAND = " | Puppy House"
TAKE_HOME_WEEKS = 10  # content/home.md, FAQ «Во сколько щенка можно забрать домой?» — не раньше 10 недель

# крупный план лайфстайл-фото в большом кадре галереи (как object-position у карточек в main.css)
LIFE_POS = {
    "pup__img--mokka": "40% 70%",
    "pup__img--luiza": "40% 74%",
    "pup__img--charli": "48% 60%",
    "pup__img--tessa": "50% 50%",
}
# взрослые фото по породе родителя (плейсхолдеры, пока питомник не пришлёт фото настоящих родителей)
PARENT_PHOTO = (("пудел", "toj-pudel"), ("мальтипу", "maltipu"), ("бульдог", "francuzskij-buldog"), ("колли", "border-kolli"))
# короткие факты о родителях — образцы в скобках, заменить реальными
PARENT_FACTS = {
    "мальтийская болонка": ("[4 года]", "[3 кг]"),
    "мальтипу": ("[3 года]", "[4 кг]"),
    "той-пудель": ("[3 года]", "[3 кг]"),
    "французский бульдог": (("[4 года]", "[10 кг]"), ("[3 года]", "[12 кг]")),
    "бордер-колли": (("[4 года]", "[17 кг]"), ("[3 года]", "[20 кг]")),
}
VARIETY_LINE = {
    "maltipu": "F1, F1b, F2, мини и окрасы",
    "francuzskij-buldog": "Окрасы по стандарту и вне его",
    "toj-pudel": "Той и мини, все окрасы",
    "border-kolli": "Типы шерсти и окрасы",
}
STEPS = [
    {"title": "Заявка", "text": "Оставьте номер — пришлём цену и видео"},
    {"title": "Видеозвонок", "text": "Покажем щенка, маму и документы онлайн"},
    {"title": "Бронь", "text": "Договор и предоплата — щенок закреплён за вами"},
    {"title": "Встреча или доставка", "text": "Заберёте в питомнике или привезём домой"},
]


def cap(s):
    """Capitalise the first letter, also inside a leading «[»: «[кличка мамы]» → «[Кличка мамы]»."""
    i = 1 if s.startswith("[") else 0
    return s[:i] + s[i:i + 1].upper() + s[i + 1:]


def ru_date(d, year=True):
    return f"{d.day}{NBSP}{MONTHS_GEN[d.month - 1]}" + (f" {d.year}" if year else "")


def plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def weeks(n):
    return f"{n}{NBSP}{plural(n, 'неделя', 'недели', 'недель')}"


def fit(candidates, limit):
    """First candidate within the limit (the last one otherwise)."""
    for c in candidates:
        if len(c) <= limit:
            return c
    return candidates[-1]


def parent_photo(breed_text, bmap):
    """(photo, tone) of the adult studio photo that matches the parent's breed; (None, None) for the maltese."""
    t = breed_text.strip("[]").lower()
    for key, slug in PARENT_PHOTO:
        if key in t:
            return dict(bmap[slug]["adult"]), bmap[slug]["tone"]
    return None, None


def parent_facts(breed_text, role):
    t = breed_text.strip("[]").lower()
    for key, facts in PARENT_FACTS.items():
        if key in t:
            if isinstance(facts[0], tuple):
                facts = facts[0] if role == "mother" else facts[1]
            out = list(facts)
            if "мальтипу" not in t:
                out.append("Родословная РКФ")  # чистопородные родители: у щенков метрика РКФ / копии родословных
            return out
    return ["[возраст]", "[вес]"]


def doc_list(docs, n):
    """«Метрика РКФ, ветпаспорт, договор» — the first n documents as one phrase."""
    return ", ".join([docs[0]] + [d[0].lower() + d[1:] for d in docs[1:n]])


def documents(p, b):
    """Documents badges: RKF metric only for FCI breeds; maltipu — vet passport, contract, pedigree copies."""
    if b["rkf"]:
        docs = ["Метрика РКФ", "Ветпаспорт", "Договор"]
    else:
        gen = (p.get("generation") or "").split()[0] if p.get("generation") else ""
        # F1: оба родителя чистопородные. F1b / F2: мама (и папа у F2) — мальтипу F1, у них родословной нет
        docs = ["Ветпаспорт", "Договор", "Копии родословных родителей" if gen in ("", "F1") else "Копии родословных предков"]
    if "Чип" in p.get("badges", []):
        docs.append("Чип")
    return docs


def colour_note(p, b):
    for c in b.get("colours", {}).get("items", []):
        if c["name"] == p["colour"] and c.get("standard") is False:
            return f"{cap(p['colour'])} окрас не входит в стандарт FCI — щенок для дома, не для выставок."
    return None


def specs(p, b, as_of):
    facts = {f["key"]: f["value"] for f in b["facts"]}
    height = facts["height"].replace(" в холке", "")
    if p.get("variety") and "до 28" in p["variety"]:
        height = "до 28 см"
    rows = [
        {"label": "Взрослый вес", "value": p["weight_forecast"]},
        {"label": "Рост в холке", "value": height},
        {"label": "Шерсть", "value": facts["coat"]},
        {"label": "Прививки", "value": "по возрасту, в ветпаспорте"},
    ]
    if p["status"] != "reserved":
        born = dt.date.fromisoformat(p["birth_date"])
        home = born + dt.timedelta(weeks=TAKE_HOME_WEEKS)
        if p["status"] == "available" and home <= as_of:
            value = "можно забрать сейчас"
        else:
            value = f"не раньше {ru_date(home, year=False)}"
        rows.append({"label": "Переезд домой", "value": value})
    return rows


def gallery(p, parents, docs):
    """Thumbnails: the puppy, one parent (the first with a photo), video on request, documents."""
    ph = p["photo"]
    main_pos = ph.get("pos") or LIFE_POS.get(ph.get("class") or "", "50% 62%" if ph["kind"] == "studio" else "50% 55%")
    items = [{
        "kind": "photo", "src": ph["src"], "alt": ph["alt"], "label": p["name"], "pos": main_pos,
        "aria": f"Фото: {p['name']}", "cap": "", "tpos": "50% 62%" if ph["kind"] == "studio" else main_pos,
    }]
    first = next((x for x in parents if x["photo"]), None)
    if first:
        items.append({
            "kind": "parent", "src": first["photo"]["src"], "alt": first["photo"]["alt"], "label": first["role_label"],
            "pos": "50% 72%", "tpos": "50% 62%", "aria": f"Фото: {first['role_label'].lower()}",
            "cap": f"{first['role_label']} · {first['name']}",
        })
    items.append({
        "kind": "video", "src": "/assets/img/video-call.jpg", "alt": "Щенка показывают по видеосвязи на экране смартфона",
        "label": "Видео по запросу", "pos": "38% 50%", "tpos": "36% 50%", "aria": "Видео по запросу", "cap": "",
    })
    items.append({
        "kind": "docs", "src": "/assets/img/documents.jpg", "alt": "Лапа щенка рядом с папкой документов и ветпаспортом",
        "label": "Документы", "pos": "50% 50%", "tpos": "50% 50%", "aria": "Фото: документы",
        "cap": " · ".join(docs[:3]),
    })
    return items


def routes(data):
    bmap = data["breed_map"]
    as_of = dt.date.fromisoformat(data["site"]["as_of"])
    out = []
    for p in data["puppies"]:
        b = bmap[p["breed"]]
        gen = p.get("generation") or ""
        gen_sp = f" {gen}" if gen else ""
        sex_m = p["sex"] == "male"
        name = p["name"]

        parents = []
        for role in ("mother", "father"):
            par = p["parents"][role]
            photo, tone = parent_photo(par["breed"], bmap)
            parents.append({
                "role": role,
                "role_label": "Мама" if role == "mother" else "Папа",
                "name": cap(par["name"]),
                "breed": cap(par["breed"]),
                "photo": photo,
                "tone": tone or b["tone"],
                "facts": parent_facts(par["breed"], role),
            })
        # одно и то же фото дважды не показываем: второй родитель — «фото и видео по запросу»
        if parents[0]["photo"] and parents[1]["photo"] and parents[0]["photo"]["src"] == parents[1]["photo"]["src"]:
            parents[1]["photo"], parents[1]["tone"] = None, b["tone"]

        docs = documents(p, b)
        born = dt.date.fromisoformat(p["birth_date"])
        meta = [x for x in (gen, p["sex_label"], p["colour"], weeks(p["age_weeks"]),
                            f"{'родился' if sex_m else 'родилась'} {ru_date(born)}") if x]

        bg = b["name_gen"]
        if p["status"] == "reserved":
            title = fit([f"Щенок {bg}{gen_sp} {name} в Москве{BRAND}", f"Щенок {bg}{gen_sp} {name}{BRAND}",
                         f"Щенок {bg} {name}{BRAND}"], TITLE_MAX)
            tail = f"Сейчас {'забронирован' if sex_m else 'забронирована'} — покажем похожих щенков и расскажем о новом помёте."
        elif p["status"] == "soon":
            title = fit([f"Щенок {bg}{gen_sp} {name} — купить в Москве{BRAND}", f"Щенок {bg}{gen_sp} {name} в Москве{BRAND}",
                         f"Щенок {bg} {name} в Москве{BRAND}", f"Щенок {bg} {name}{BRAND}"], TITLE_MAX)
            tail = "Скоро в продаже: запишитесь в лист ожидания — пришлём видео и цену первыми."
        else:
            title = fit([f"Щенок {bg}{gen_sp} {name} — купить в Москве{BRAND}", f"Щенок {bg}{gen_sp} {name} в Москве{BRAND}",
                         f"Щенок {bg} {name} в Москве{BRAND}", f"Щенок {bg} {name}{BRAND}"], TITLE_MAX)
            tail = "Покажем по видео, доставим по России. Узнайте цену."
        head = f"{name} — щенок {bg}{gen_sp}, {p['sex_label']}, окрас {p['colour']}, {weeks(p['age_weeks'])}."
        short_head = f"{name} — щенок {bg}{gen_sp}, {p['sex_label']}, {weeks(p['age_weeks'])}."
        d3, d2 = doc_list(docs, 3) + ".", doc_list(docs, 2) + "."
        description = fit([f"{head} {d3} {tail}", f"{head} {d2} {tail}", f"{head} {tail}",
                           f"{short_head} {d3} {tail}", f"{short_head} {tail}"], DESC_MAX).replace(NBSP, " ")

        gets = [
            {"icon": "doc", "color": "sky", "title": "Документы",
             "line": doc_list(docs, 3)},
            {"icon": "syringe", "color": "mint", "title": "Прививки и осмотр",
             "line": "Прививки по возрасту, осмотр ветеринара перед переездом"},
            {"icon": "bowl", "color": "sun", "title": "Стартовый набор",
             "line": "[Корм, к которому привык, и пелёнка с запахом мамы]"},
            {"icon": "chat", "color": "lilac", "title": "Куратор на связи",
             "line": "Ответим на вопросы о корме, прививках и воспитании"},
        ]
        related = [
            {"url": b["urls"]["hub"], "title": b["name"], "line": b["tile_line"], "breed": b},
            {"url": b["urls"]["price"], "title": f"Цена {b['name_gen']}", "line": "От чего зависит цена щенка", "icon": "wallet", "color": "sun"},
            {"url": b["urls"]["varieties"], "title": "Виды и окрасы", "line": VARIETY_LINE[b["slug"]], "icon": "sparkle", "color": "lilac"},
            {"url": "/dokumenty-i-garantii/", "title": "Документы и гарантии", "line": "Что входит в договор", "icon": "doc", "color": "sky"},
        ]

        lead_line = f"Пришлём всех щенков {b['name_plural_gen']} в наличии, цены и видео"
        if len(lead_line) > 90:
            lead_line = "Пришлём щенков в наличии, цены и свежие видео"

        out.append(dict(
            url=p["url"],
            template="puppy/puppy.html.j2",
            context=dict(
                title=title,
                description=description,
                breadcrumbs=crumbs(("Щенки", "/shchenki/"), (b["name"], f"/shchenki/?breed={b['slug']}"), (name, None)),
                p=p,
                b=b,
                meta=meta,
                specs=specs(p, b, as_of),
                docs=docs,
                docs_note="Мальтипу — гибрид, РКФ его не регистрирует." if not b["rkf"] else None,
                colour_note=colour_note(p, b),
                parents=parents,
                gallery=gallery(p, parents, docs),
                gets=gets,
                steps=STEPS,
                related=related,
                lead_breed=b["slug"],
                lead_line=lead_line,
            ),
        ))
    return out
