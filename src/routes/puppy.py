"""Puppy pages /shchenki/<slug>/ — one conversion page per puppy in puppies.json (typical strong-kennel layout, client 13.10):
gallery carousel + info tile with the characteristics table → character → parents → what's included → booking and
delivery → similar puppies → FAQ → lead form.
Owns: src/routes/puppy.py, src/templates/puppy/, src/data/puppy.json, assets/css/puppy.css, assets/js/puppy.js.
The puppy card of «Похожие щенки» is the shared card cards.puppy_card (via src/templates/catalog/_card.html.j2, main.css)."""

import datetime as dt

from _lib import by_id, crumbs

NBSP = " "
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]
TITLE_MAX, DESC_MAX = 60, 160
BRAND = " | домщенков.рф"
TAKE_HOME_WEEKS = 10  # content/home.md, FAQ «Во сколько щенка можно забрать домой?» — не раньше 10 недель
GALLERY_MAX = 9
IMG = "/assets/img/"

# крупный план лайфстайл-фото в кадре галереи (как object-position у карточек в main.css)
LIFE_POS = {
    "pup__img--mokka": "40% 70%",
    "pup__img--luiza": "40% 74%",
    "pup__img--charli": "48% 60%",
    "pup__img--tessa": "50% 50%",
}

# Заглушки фото родителей, пока питомник не пришлёт настоящие: по породе родителя — основное фото и запасное
# (второй родитель той же породы получает запасное, одно фото дважды не показываем).
PARENT_PHOTOS = (
    ("болонк", [("parents-maltipu.jpg", "Мама со щенками на лежанке", "40% 50%")]),
    ("мальтипу", [("parent-maltipu.jpg", "Взрослый абрикосовый мальтипу на персиковом фоне", "50% 40%"),
                  ("hero-maltipu-sofa.jpg", "Абрикосовый мальтипу на светлом диване", "50% 45%")]),
    ("пудел", [("parent-pudel.jpg", "Взрослый рыжий той-пудель на жёлтом фоне", "50% 40%"),
               ("grad-woman-pudel.jpg", "Той-пудель на руках у хозяйки в кресле у окна", "64% 60%")]),
    ("бульдог", [("parent-buldog.jpg", "Взрослый палевый французский бульдог на голубом фоне", "50% 40%"),
                 ("breed-francuzskij-buldog.jpg", "Голубой французский бульдог на скамье у окна", "52% 40%")]),
    ("колли", [("parent-kolli.jpg", "Взрослый чёрно-белый бордер-колли на мятном фоне", "50% 40%"),
               ("grad-man-kolli.jpg", "Бордер-колли играет с хозяином в осеннем парке", "64% 50%")]),
)
# короткие факты о родителях — образцы в скобках, заменить реальными
PARENT_FACTS = {
    "мальтийская болонка": ("[4 года]", "[3 кг]"),
    "мальтипу": ("[3 года]", "[4 кг]"),
    "той-пудель": ("[3 года]", "[3 кг]"),
    "французский бульдог": (("[4 года]", "[10 кг]"), ("[3 года]", "[12 кг]")),
    "бордер-колли": (("[4 года]", "[17 кг]"), ("[3 года]", "[20 кг]")),
}
# Лайфстайл-заглушки галереи по породе: (файл, alt, подпись, object-position). Первая — постер видео.
# Фото, которые уже стоят у других щенков в каталоге, сюда не берём — одного щенка не показываем под двумя кличками.
LIFE = {
    "maltipu": [
        ("hero-maltipu-sofa.jpg", "Абрикосовый щенок мальтипу на светлом диване", "Дома на диване", "50% 45%"),
        ("family-maltipu.jpg", "Девушка обнимает щенка мальтипу на диване", "Знакомство с семьёй", "56% 50%"),
    ],
    "francuzskij-buldog": [
        ("grad-family-buldog.jpg", "Семья с дочкой и щенком французского бульдога на диване", "Знакомство с семьёй", "50% 50%"),
        ("breed-francuzskij-buldog.jpg", "Голубой французский бульдог на скамье у окна", "У окна", "52% 40%"),
        ("delivery-carrier.jpg", "Щенок французского бульдога в переноске на сиденье машины", "Едет домой", "55% 50%"),
    ],
    "toj-pudel": [
        ("grad-woman-pudel.jpg", "Той-пудель на руках у хозяйки в кресле у окна", "На руках у хозяйки", "64% 60%"),
        ("vet-check.jpg", "Ветеринар осматривает щенка той-пуделя", "Осмотр ветеринара", "40% 50%"),
    ],
    "border-kolli": [
        ("grad-man-kolli.jpg", "Мужчина играет с бордер-колли в осеннем парке", "Игра в парке", "64% 50%"),
    ],
}
EXTRA = [  # общие кадры в конце галереи
    ("video-call.jpg", "video", "Щенок на экране смартфона во время видеозвонка", "Видеозвонок со щенком", "40% 50%"),
    ("starter-kit.jpg", "photo", "Стартовый набор для щенка: лежанка, переноска, миски и игрушки", "Стартовый набор", "50% 50%"),
    ("documents.jpg", "photo", "Лапа щенка рядом с папкой документов и ветпаспортом", "Ветпаспорт и договор", "50% 50%"),
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


def parent_photo(breed_text, used):
    """Placeholder photo {src, alt, pos} for a parent of this breed, not one already used on the page."""
    t = breed_text.strip("[]").lower()
    for key, options in PARENT_PHOTOS:
        if key in t:
            for name, alt, pos in options:
                if IMG + name not in used:
                    return {"src": IMG + name, "alt": alt, "pos": pos}
            return None
    return None


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
    """/<breed>/vidy-i-okrasy/#<colour> — the colour's own card (breedsub.json); the colours block otherwise."""
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
            return f"{base}#{c['slug']}"
    return f"{base}#{block.get('id', 'okrasy')}"


def take_home(p, as_of):
    born = dt.date.fromisoformat(p["birth_date"])
    home = born + dt.timedelta(weeks=TAKE_HOME_WEEKS)
    if p["status"] == "available" and home <= as_of:
        return "можно забрать сейчас"
    return f"не раньше {ru_date(home, year=False)}"


def table(p, b, docs, data, as_of):
    """Characteristics table rows {label, value, url?}. Short (клиент 19.10): пол и поколение — в H1, прививки и чип —
    в «Что входит в покупку»."""
    born = dt.date.fromisoformat(p["birth_date"])
    rows = [
        {"label": "Порода", "value": b["name"], "url": b["urls"]["hub"]},
        {"label": "Окрас", "value": p["colour"], "url": colour_url(p, b, data)},
        {"label": "Возраст", "value": f"{weeks(p['age_weeks'])}, {'родился' if p['sex'] == 'male' else 'родилась'} {ru_date(born)}"},
        {"label": "Вес взрослой собаки", "value": p["weight_forecast"]},
        {"label": "Документы", "value": doc_list([d for d in docs if d != "Чип"], 3)},
    ]
    if p["status"] != "reserved":
        rows.append({"label": "Переезд домой", "value": take_home(p, as_of)})
    return rows


def gallery(p, b, parents):
    """Photos and videos of the puppy: own photos and video first, then placeholders (lifestyle shots of the breed,
    parents, video call, starter kit, documents) — up to GALLERY_MAX. Items: {src, alt, kind, caption, video, pos, tone}."""
    name = p["name"]
    items, used = [], set()

    def add(src, kind, alt, caption, pos, video=None):
        if (src in used and not video) or len(items) >= GALLERY_MAX:
            return
        used.add(src)
        items.append({"src": src, "kind": kind, "alt": alt, "caption": caption, "video": video, "pos": pos})

    for ph in p["photos"]:
        pos = ph.get("pos") or LIFE_POS.get(ph.get("class") or "", "50% 60%" if ph["kind"] == "studio" else "50% 55%")
        add(ph["src"], "photo", ph["alt"], name, pos)
    for par in parents:  # parents' photos stay for their own slides further down
        if par["photo"]:
            used.add(par["photo"]["src"])
    life = [x for x in LIFE.get(b["slug"], []) if IMG + x[0] not in used]
    v = p.get("video")  # puppies.json: "video": "/assets/video/x.mp4" or {"src", "poster"} — the real video goes first
    if v:
        v = v if isinstance(v, dict) else {"src": v}
        add(v.get("poster") or p["photo"]["src"], "video", f"Видео: {name}", f"Видео: {name}", "50% 50%", v.get("src"))
    elif life:
        f, alt, caption, pos = life.pop(0)
        add(IMG + f, "video", alt, "Видео щенка", pos)
    for f, alt, caption, pos in life:
        add(IMG + f, "photo", alt, caption, pos)
    for par in parents:
        if par["photo"]:
            used.discard(par["photo"]["src"])
            add(par["photo"]["src"], "photo", par["photo"]["alt"], f"{par['role_label']} · {par['name']}", par["photo"]["pos"])
    for f, kind, alt, caption, pos in EXTRA:
        add(IMG + f, kind, alt, caption, pos)
    return items


def routes(data):
    bmap = data["breed_map"]
    as_of = dt.date.fromisoformat(data["site"]["as_of"])
    texts = data["puppy"]
    faq = by_id(data["faq"])
    out = []
    for p in data["puppies"]:
        b = bmap[p["breed"]]
        gen = p.get("generation") or ""
        gen_sp = f" {gen}" if gen else ""
        sex_m = p["sex"] == "male"
        name = p["name"]

        parents, used = [], set()
        for role in ("mother", "father"):
            par = p["parents"][role]
            photo = parent_photo(par["breed"], used)
            if photo:
                used.add(photo["src"])
            parents.append({
                "role": role,
                "role_label": "Мама" if role == "mother" else "Папа",
                "name": cap(par["name"]),
                "breed": cap(par["breed"]),
                "photo": photo,
                "facts": parent_facts(par["breed"], role),
            })

        docs = documents(p, b)
        h1 = h1_of(p, b)
        ca = colour_adj(p["colour"])

        bg = b["name_gen"]
        if p["status"] == "reserved":
            title = fit([f"{ca} щенок {bg}{gen_sp} {name} в Москве{BRAND}", f"{ca} щенок {bg}{gen_sp} {name}{BRAND}",
                         f"Щенок {bg}{gen_sp} {name} в Москве{BRAND}", f"Щенок {bg}{gen_sp} {name}{BRAND}",
                         f"Щенок {bg} {name}{BRAND}"], TITLE_MAX)
            tail = f"Сейчас {'забронирован' if sex_m else 'забронирована'} — покажем похожих щенков и расскажем о новом помёте."
        elif p["status"] == "soon":
            title = fit([f"{ca} щенок {bg}{gen_sp} {name} — купить в Москве{BRAND}",
                         f"{ca} щенок {bg}{gen_sp} {name} в Москве{BRAND}", f"{ca} щенок {bg}{gen_sp} {name}{BRAND}",
                         f"Щенок {bg}{gen_sp} {name} — купить в Москве{BRAND}", f"Щенок {bg}{gen_sp} {name} в Москве{BRAND}",
                         f"Щенок {bg} {name} в Москве{BRAND}", f"Щенок {bg} {name}{BRAND}"], TITLE_MAX)
            tail = "Скоро в продаже: запишитесь в лист ожидания — пришлём видео и цену первыми."
        else:
            title = fit([f"{ca} щенок {bg}{gen_sp} {name} — купить в Москве{BRAND}",
                         f"{ca} щенок {bg}{gen_sp} {name} в Москве{BRAND}", f"{ca} щенок {bg}{gen_sp} {name}{BRAND}",
                         f"Щенок {bg}{gen_sp} {name} — купить в Москве{BRAND}", f"Щенок {bg}{gen_sp} {name} в Москве{BRAND}",
                         f"Щенок {bg} {name} в Москве{BRAND}", f"Щенок {bg} {name}{BRAND}"], TITLE_MAX)
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
        about = [texts["puppies"].get(p["slug"], f"[{name}: характер щенка — заполнит питомник.]"), bt["about"], texts["home"]]
        breed_links = [
            {"url": b["urls"]["hub"], "label": f"{b['name']}: о породе"},
            {"url": b["urls"]["price"], "label": f"Цена щенка {bg}"},
            {"url": b["urls"]["varieties"], "label": f"Окрасы {bg}"},
        ]

        similar_pool = sorted([x for x in b["puppies"] if x["slug"] != p["slug"]], key=lambda x: x["status_order"])
        similar = similar_pool[:4]

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
                h1=h1,
                rows=table(p, b, docs, data, as_of),
                docs=docs,
                docs_note="Мальтипу — гибрид, РКФ его не регистрирует." if not b["rkf"] else None,
                colour_note=colour_note(p, b),
                parents=parents,
                gallery=gallery(p, b, parents),
                includes=includes,
                about=about,
                fits=bt["fits"],
                breed_links=breed_links,
                booking=texts["booking"],
                delivery=texts["delivery"],
                similar=similar,
                similar_total=len(b["puppies"]),
                faq_items=[faq[i] for i in texts["faq"]],
                lead_breed=b["slug"],
                lead_line=lead_line,
            ),
        ))
    return out
