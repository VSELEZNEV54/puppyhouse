"""Puppy pages /shchenki/<slug>/ — one conversion page per puppy in puppies.json (layout of 13.10, client notes 19.10):
gallery of the puppy's own photos + info tile with the characteristics table → «Как купить щенка» → «Про <породу>»
(SEO text and facts) → «Кому подойдёт» (photo cards) → «Читайте о породе» (hub, price, colours) → what's included →
booking and delivery → similar puppies (cards.pups_std, 8) → FAQ → lead form. No status badges, no parents block (client 19.10).
Owns: src/routes/puppy.py, src/templates/puppy/, src/data/puppy.json, assets/css/puppy.css, assets/js/puppy.js.
The puppy card of «Похожие щенки» is the shared card cards.puppy_card (via src/templates/catalog/_card.html.j2, main.css)."""

import datetime as dt

from _lib import by_id, crumbs

NBSP = " "
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]
TITLE_MAX, DESC_MAX = 60, 160
BRAND = " | домщенков.рф"
GALLERY_MAX = 9

# крупный план лайфстайл-фото в кадре галереи (как object-position у карточек в main.css)
LIFE_POS = {
    "pup__img--mokka": "40% 70%",
    "pup__img--luiza": "40% 74%",
    "pup__img--charli": "48% 60%",
    "pup__img--tessa": "50% 50%",
}

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


def doc_list(docs, n):
    """«Метрика РКФ, ветпаспорт, договор» — the first n documents as one phrase."""
    return ", ".join([docs[0]] + [d[0].lower() + d[1:] for d in docs[1:n]])


def documents(p, b):
    """Documents: RKF metric only for FCI breeds; maltipu — vet passport, contract, pedigree copies."""
    if b["rkf"]:
        docs = ["Метрика РКФ", "Ветпаспорт", "Договор"]
    else:
        gen = (p.get("generation") or "").split()[0] if p.get("generation") else ""
        # F1: оба родителя чистопородные. F1b / F2: мама (и папа у F2) — мальтипу F1, у них родословной нет
        docs = ["Ветпаспорт", "Договор", "Копии родословных родителей" if gen in ("", "F1") else "Копии родословных породистых предков"]
    if "Чип" in p.get("badges", []):
        docs.append("Чип")
    return docs


def colour_note(p, b):
    for c in b.get("colours", {}).get("items", []):
        if c["name"] == p["colour"] and c.get("standard") is False:
            return f"{cap(p['colour'])} окрас не входит в стандарт FCI — щенок для дома, не для выставок."
    return None


# окрас в заголовке — прилагательным перед «щенок»: «Голубой мраморный щенок бордер-колли девочка»
COLOUR_ADJ = {"голубой мрамор": "голубой мраморный", "красный мрамор": "красный мраморный",
              "чёрный с подпалом": "чёрно-подпалый", "партиколор": "партиколорный"}


def colour_adj(colour):
    """«рыжий (красный)» → «Рыжий», «голубой мрамор» → «Голубой мраморный»."""
    c = colour.split(" (")[0].strip()
    return cap(COLOUR_ADJ.get(c, c))


def h1_of(p, b):
    """H1 под поисковый запрос, без клички (клиент 19.10): «Кремовый щенок мальтипу F1 мальчик»."""
    gen = p.get("generation") or ""
    return f"{colour_adj(p['colour'])} щенок {b['name_gen']}{(' ' + gen) if gen else ''} {p['sex_label']}"


def colour_url(p, b, data):
    """/<breed>/<colour>/ — the colour's own page (breedsub.json colour slug); the colours block of
    /<breed>/vidy-i-okrasy/ otherwise (client 21.10: that page shows the colours as the breed page's carousel, no
    anchored card per colour)."""
    base = b["urls"]["varieties"]
    try:
        blocks = data["breedsub"][b["slug"]]["varieties"]["blocks"]
        block = next(x for x in blocks if x.get("type") == "colours")
    except (KeyError, StopIteration, TypeError):
        return base
    want = p["colour"].lower()
    short = want.split(" (")[0]
    for c in block.get("items", []):
        name = str(c.get("name", "")).lower()
        if c.get("slug") and (name == want or name.split(" (")[0] == short):
            return f"{b['urls']['hub']}{c['slug']}/"
    return f"{base}#{block.get('id', 'okrasy')}"


def table(p, b, docs, data):
    """Characteristics table rows {label, value, url?}. Short (клиент 19.10): пол и поколение — в H1, прививки и чип —
    в «Что входит в покупку», без переезда домой."""
    born = dt.date.fromisoformat(p["birth_date"])
    rows = [
        {"label": "Порода", "value": b["name"], "url": b["urls"]["hub"]},
        {"label": "Окрас", "value": p["colour"], "url": colour_url(p, b, data)},
        {"label": "Возраст", "value": f"{weeks(p['age_weeks'])}, {'родился' if p['sex'] == 'male' else 'родилась'} {ru_date(born)}"},
        {"label": "Вес взрослой собаки", "value": p["weight_forecast"]},
        {"label": "Документы", "value": doc_list([d for d in docs if d != "Чип"], 3)},
    ]
    return rows


def gallery(p):
    """The puppy's own photos and video only (client 19.10: no generated shots in the gallery), up to GALLERY_MAX.
    Items: {src, alt, kind, caption, video, pos}."""
    name = p["name"]
    items = []
    for ph in p["photos"][:GALLERY_MAX]:
        pos = ph.get("pos") or LIFE_POS.get(ph.get("class") or "", "50% 60%" if ph["kind"] == "studio" else "50% 55%")
        items.append({"src": ph["src"], "kind": "photo", "alt": ph["alt"], "caption": name, "video": None, "pos": pos})
    v = p.get("video")  # puppies.json: "video": "/assets/video/x.mp4" or {"src", "poster"} — second, after the main photo
    if v:
        v = v if isinstance(v, dict) else {"src": v}
        items.insert(1, {"src": v.get("poster") or p["photo"]["src"], "kind": "video", "alt": f"Видео: {name}",
                         "caption": f"Видео: {name}", "video": v.get("src"), "pos": "50% 50%"})
    return items[:GALLERY_MAX]


def routes(data):
    bmap = data["breed_map"]
    texts = data["puppy"]
    faq = by_id(data["faq"])
    out = []
    for p in data["puppies"]:
        b = bmap[p["breed"]]
        gen = p.get("generation") or ""
        gen_sp = f" {gen}" if gen else ""
        sex_m = p["sex"] == "male"
        name = p["name"]

        docs = documents(p, b)
        h1 = h1_of(p, b)
        ca = colour_adj(p["colour"])

        bg = b["name_gen"]
        # one wording for every status: the site shows no «забронирован» / «скоро» (client 19.10).
        # The query («купить» + colour + breed) always stays; ≤ 60 is counted without BRAND (the search engine may cut it)
        title = fit([f"{ca} щенок {bg}{gen_sp} {name} — купить в Москве", f"{ca} щенок {bg}{gen_sp} {name} — купить",
                     f"Щенок {bg}{gen_sp} {name} — купить в Москве", f"Щенок {bg} {name} — купить в Москве",
                     f"Щенок {bg} {name} — купить"], TITLE_MAX) + BRAND
        tail = "Покажем по видео, доставим по России. Узнайте цену."
        head = f"{name} — щенок {bg}{gen_sp}, {p['sex_label']}, окрас {p['colour']}, {weeks(p['age_weeks'])}."
        short_head = f"{name} — щенок {bg}{gen_sp}, {p['sex_label']}, {weeks(p['age_weeks'])}."
        d3, d2 = doc_list(docs, 3) + ".", doc_list(docs, 2) + "."
        description = fit([f"{head} {d3} {tail}", f"{head} {d2} {tail}", f"{head} {tail}",
                           f"{short_head} {d3} {tail}", f"{short_head} {tail}"], DESC_MAX).replace(NBSP, " ")

        # «Что входит»: привит, ветпаспорт, договор, метрика / родословные, чип, пожизненные гарантия и консультация, набор
        pedigree = ("Метрика РКФ", "Потом обменяете на родословную РКФ") if b["rkf"] else \
            ("Копии родословных", "Родословные родителей и предков")
        includes = [
            {"icon": "syringe", "color": "mint", "title": "Привит по возрасту" if sex_m else "Привита по возрасту",
             "line": "Прививки и обработки от паразитов"},
            {"icon": "book", "color": "sky", "title": "Ветпаспорт", "line": "С отметками о прививках и осмотре"},
            {"icon": "doc", "color": "sand", "title": "Договор", "line": "Бронь, гарантия и условия — на бумаге"},
            {"icon": "users", "color": "lilac", "title": pedigree[0], "line": pedigree[1]},
            {"icon": "paw", "color": "sun", "title": "Чип",
             "line": "Уже стоит, номер — в ветпаспорте" if "Чип" in docs else "[Поставим по запросу до переезда]"},
            {"icon": "shield", "color": "coral", "title": "Пожизненная гарантия", "line": "Условия гарантии прописаны в договоре"},
            {"icon": "chat", "color": "lilac", "title": "Пожизненная консультация", "line": "На связи по уходу, корму и здоровью"},
            {"icon": "bowl", "color": "mint", "title": "Стартовый набор", "line": "[Корм, к которому привык, и пелёнка с запахом мамы]"},
        ]

        bt = texts["breeds"][b["slug"]]

        lead_line = f"Пришлём всех щенков {b['name_plural_gen']} в наличии, цены и видео"
        if len(lead_line) > 90:
            lead_line = "Пришлём щенков в наличии, цены и свежие видео"

        out.append(dict(
            url=p["url"],
            template="puppy/puppy.html.j2",
            context=dict(
                title=title,
                description=description,
                breadcrumbs=crumbs(("Щенки", "/shchenki/"), (b["name"], b["urls"]["hub"]), (name, None)),
                p=p,
                b=b,
                h1=h1,
                rows=table(p, b, docs, data),
                docs=docs,
                docs_note="Мальтипу — гибрид, РКФ его не регистрирует." if not b["rkf"] else None,
                colour_note=colour_note(p, b),
                gallery=gallery(p),
                includes=includes,
                intro=bt["intro"],
                facts=bt["facts"],
                fits=bt["fits"],
                booking=texts["booking"],
                delivery=texts["delivery"],
                faq_items=[faq[i] for i in texts["faq"]],
                lead_breed=b["slug"],
                lead_line=lead_line,
            ),
        ))
    return out
