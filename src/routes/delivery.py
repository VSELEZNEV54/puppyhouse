"""Service pages (group «delivery»):
    /dostavka/ + one page per city in cities.json (/dostavka/<slug>/), /rassrochka/, /shchenok-v-podarok/, /faq/,
    /kontakty/, /politika-konfidencialnosti/.
Owns: src/templates/delivery/, src/data/delivery.json, delivery-cities.json, delivery-service.json, assets/css/delivery.css.
Copy lives in the data files; this module only picks the right variant per city (distance, methods, time zone)."""

import json
import re

from markupsafe import Markup, escape

from _lib import by_id, crumbs

NBSP = " "
TITLE_MAX, DESC_MAX = 60, 160
BRAND = " | Puppy House"


# ---------------------------------------------------------------- helpers
def plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def km(n):
    """710 → «710 км», 9300 → «9 300 км» (non-breaking spaces)."""
    s = f"{int(n):,}".replace(",", NBSP)
    return f"{s}{NBSP}км"


def fill(text, **kw):
    """str.format for copy templates; unknown keys stay as they are."""
    return re.sub(r"\{(\w+)\}", lambda m: str(kw.get(m.group(1), m.group(0))), text)


# Visible copy never breaks inside «Санкт-Петербург», «о бордер-колли» or a range like «10–16 лет»: such words go into
# <span class="nw"> (the macros' |typo keeps Markup tags). Copy with a hand-written link (<a href="/…/">) is trusted
# Markup from our own data; everything else is escaped first. Meta title/description and attributes stay plain text.
_HYPHENATED = re.compile(r"(?<![\w-])((?:\w{1,2} )?\w+(?:-\w+)+)")
_RANGE = re.compile(r"(?<![\w,])(\d+(?:,\d+)?–\d+(?:,\d+)?)(?: (?=[а-яё])(?!(?:и|или|а|но|до|в|во|на|с|со|по|за|из|от|к|у|о)\b))?")
_TAG = re.compile(r"(<[^>]+>)")


def _nobr_text(s):
    s = _HYPHENATED.sub(r'<span class="nw">\1</span>', s)
    return _RANGE.sub(lambda m: f'<span class="nw">{m.group(1)}</span>' + (NBSP if m.group(0).endswith(" ") else ""), s)


def nobr(text):
    """Text → Markup with hyphenated words and number ranges kept on one line (links in our own copy stay links)."""
    if not isinstance(text, str):
        return text
    raw = text if "<a " in text else str(escape(text))
    return Markup("".join(p if p.startswith("<") else _nobr_text(p) for p in _TAG.split(raw)))


def nb(d, *keys):
    """Copy of dict d with the given text keys passed through nobr()."""
    return {k: (nobr(v) if k in keys else v) for k, v in d.items()}


def qa(items):
    """FAQ items for blocks.faq_*: the question in one <span> (the button is a flex box), both kept unbroken."""
    return [{"q": Markup("<span>") + nobr(i["q"]) + Markup("</span>"), "a": nobr(i["a"])} for i in items]


def join_or(words):
    words = list(words)
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " или " + words[-1]


def cap(s):
    return s[:1].upper() + s[1:]


def check_meta(url, title, description):
    """The build warns too; failing early here keeps a bad template from shipping 30 broken titles."""
    if len(title) > TITLE_MAX:
        raise ValueError(f"{url}: title is {len(title)} chars: {title}")
    if len(description) > DESC_MAX:
        raise ValueError(f"{url}: description is {len(description)} chars: {description}")


def page(url, template, title, description, crumb, **ctx):
    check_meta(url, title, description)
    return dict(url=url, template=template,
                context=dict(title=title, description=description, breadcrumbs=crumbs(*crumb), **ctx))


# ---------------------------------------------------------------- /dostavka/
def method_tiles(methods, breeds, keys=None):
    out = []
    for key in keys or methods:
        m = nb(dict(methods[key], key=key), "title", "line", "note", "tag", "fit_label")
        m["fit_breeds"] = breeds if m.get("fit") == "all" else [b for b in breeds if b["slug"] in m.get("fit", [])]
        out.append(m)
    return out


def seo_copy(seo, **v):
    """Collapsed SEO text: placeholders filled, words kept unbroken."""
    return dict(title=nobr(fill(seo["title"], **v)), lead=nobr(fill(seo["lead"], **v)),
                blocks=[dict(h=nobr(fill(b["h"], **v)), p=nobr(fill(b["p"], **v))) for b in seo["blocks"]])


def hub_page(data, cities):
    d = data["delivery"]
    hub = nb(d["hub"], "lead", "geo_more", "lead_title", "lead_line")
    hub["steps"] = [nb(x, "title", "text") for x in hub["steps"]]
    hub["kit"] = [nb(x, "title", "line") for x in hub["kit"]]
    hub["seo"] = seo_copy(hub["seo"])
    breeds = data["breeds"]
    groups, lo = [], 0
    for g in hub["geo_groups"]:
        items = [c for c in cities if lo < c["km_approx"] <= g["max_km"]]
        groups.append(dict(nb(g, "title", "line"), cities=items))
        lo = g["max_km"]
    assert sum(len(g["cities"]) for g in groups) == len(cities), "a city fell outside the distance groups"
    n = len(cities)
    return page(
        "/dostavka/", "delivery/hub.html.j2",
        "Доставка щенков по России — перевозка собак" + BRAND,
        "Доставка щенков из питомника в Москве: на машине с куратором, как зоотакси, самолётом в салоне или поездом. "
        "Фото и видео в пути.",
        [("Доставка", None)],
        hub=hub,
        ways=method_tiles(d["methods"], breeds),
        groups=groups,
        geo_lead=fill(hub["geo_lead"], n=f"{n}{NBSP}{plural(n, 'город', 'города', 'городов')}"),
        faq_items=qa(hub["faq"]),
        pups_strip=False,
    )


# ---------------------------------------------------------------- /dostavka/<city>/
def city_pages(data, cities):
    d = data["delivery"]
    cc = d["city"]
    extra = data["delivery_cities"]
    breeds = data["breeds"]
    methods = d["methods"]
    out = []
    for c in cities:
        slug, ms = c["slug"], list(c["methods"])
        tz = extra["tz"][slug]
        ov = extra["overrides"].get(slug, {})
        dist = km(c["km_approx"])
        has_car, has_plane, has_train = "car" in ms, "plane" in ms, "train" in ms
        primary = ms[0]
        v = dict(name=c["name"], prep=c["prep"], acc=c["acc"], gen=c["gen"], km=dist,
                 methods=join_or(methods[m]["phrase"] for m in ms))
        tz_txt = f"+{tz}{NBSP}{plural(tz, 'час', 'часа', 'часов')}" if tz else ""

        # hero
        if ms == ["car"]:
            lead_key = "car_near" if c["km_approx"] <= 600 else "car"
        elif ms == ["plane"]:
            lead_key = "plane"
        elif has_car and has_train:
            lead_key = "car_train"
        else:
            lead_key = "car_plane"
        facts = [
            {"label": "От Москвы", "value": "≈" + NBSP + dist},
            {"label": "Как везём", "value": cap(join_or(methods[m]["short"] for m in ms))},
            {"label": "В пути", "value": nobr(c["duration"])},
        ]
        if tz:
            facts.append({"label": "Время", "value": f"{tz_txt} к Москве"})

        # how it works: 3 steps, travel and meeting by the primary method
        travel = "car" if primary in ("car", "train") else "plane"
        st = cc["steps"]
        steps = [nb({k: fill(x, **v) for k, x in s.items()}, "title", "text") for s in (st["book"], st[travel], st["meet_" + travel])]

        # ways for this city: available methods (city-specific line and note) + pick-up in Moscow
        ways = []
        for m in method_tiles(methods, breeds, ms):
            m = dict(m, fit_breeds=None)
            if m["key"] == "car":
                m["tag"] = dist
                m["line"] = "От двери до двери, с остановками на воду и отдых"
                m["note"] = next(n["note"] for n in cc["car_notes"] if c["km_approx"] <= n["max_km"])
            elif m["key"] == "plane":
                m["tag"] = f"Аэропорт {c['gen']}"
            elif m["key"] == "train":
                m["tag"] = f"Вокзал {c['gen']}"
            ways.append(nb(m, "tag", "line", "note"))
        # coming to Moscow yourself: by road or rail from nearer cities, by air from far ones
        fly_in = has_plane and (c["km_approx"] > 1200 or not (has_car or has_train))
        p = cc["pickup"]
        ways.append(nb(dict(p, key="pickup", tag="Москва", fit_breeds=None,
                            note=fill(p["note_plane"] if fly_in else p["note_car"], **v)),
                       "title", "line", "note"))

        # breeds: stock (computed from puppies.json) + how this breed travels to this city
        hint = cc["breed_hint"]
        btiles = []
        for b in breeds:
            h = hint["car"] if (has_car or has_train) else hint["plane"][b["slug"]]
            btiles.append({"url": b["urls"]["hub"], "title": nobr(b["name"]), "line": nobr(f"В наличии: {b['stock']} · {h}"), "breed": b})

        # local FAQ: 3 questions, wording by method, distance and time zone
        f = cc["faq"]
        trip = dict(f["trip_car" if travel == "car" else "trip_plane"])
        if tz:
            trip["a"] = trip["a"] + " " + fill(cc["tz_note"], tz=tz_txt)
        cost = f["cost_car" if has_car else "cost_plane"]
        self_ = f["self_train"] if has_train else (f["self_plane"] if fly_in else f["self_car"])
        faq = qa([{k: fill(x, **v) for k, x in q.items()} for q in (trip, cost, self_)])
        seo = seo_copy(ov.get("seo") or cc["seo"], **v)

        desc = ov.get("description") or (
            f"Щенки мальтипу, французского бульдога, той-пуделя и бордер-колли с доставкой {c['acc']}: "
            f"{dist}, {v['methods']}.")
        out.append(page(
            c["url"], "delivery/city.html.j2",
            f"Щенки с доставкой {c['acc']}" + BRAND, desc,
            [("Доставка", "/dostavka/"), (c["name"], None)],
            city=c,
            tone="sand" if travel == "car" else "sky",
            h1=nobr(f"Щенки с доставкой {c['acc']}"),
            lead=nobr(fill(cc["lead"][lead_key], km=dist)),
            facts=facts,
            steps=steps,
            ways=ways,
            breed_tiles=btiles,
            faq_items=faq,
            others=[o for o in cities if o["slug"] != slug],
            seo=seo,
            lead_title=nobr(fill(cc["lead_title"], **v)),
            lead_line=nobr(cc["lead_line"]),
            pups_strip=False,
        ))
    return out


# ---------------------------------------------------------------- service pages
def rassrochka_page(data):
    r = nb(data["delivery_service"]["rassrochka"], "lead", "bank_lead", "bank_note", "lead_line")
    r["steps"] = [nb(x, "title", "text") for x in r["steps"]]
    r["bank_steps"] = [nb(x, "title", "text") for x in r["bank_steps"]]
    r["terms"] = [nb(x, "value") for x in r["terms"]]
    r["bank_facts"] = [nb(x, "value") for x in r["bank_facts"]]
    faq = by_id(data["faq"])
    return page(
        "/rassrochka/", "delivery/rassrochka.html.j2",
        "Бронь и рассрочка на щенка" + BRAND,
        "Как забронировать щенка: договор и предоплата — и щенок закреплён за вами. "
        "Остаток можно оплатить в рассрочку через банк-партнёр.",
        [("Бронь и рассрочка", None)],
        r=r,
        faq_items=qa([faq[i] for i in r["faq_ids"]] + r["faq_extra"]),
        pups_strip=False,
    )


def gift_page(data):
    g = nb(data["delivery_service"]["gift"], "lead", "think_lead", "think_note", "lead_line")
    g["ideas"] = [nb(x, "title", "line", "note") for x in g["ideas"]]
    g["think"] = [nobr(x) for x in g["think"]]
    g["seo"] = seo_copy(g["seo"])
    return page(
        "/shchenok-v-podarok/", "delivery/gift.html.j2",
        "Собака в подарок — как подарить щенка" + BRAND,
        "Щенок в подарок: привезём точно к празднику, поможем с сюрпризом и сертификатом. "
        "И честно расскажем, о чём подумать заранее.",
        [("Щенок в подарок", None)],
        g=g,
        faq_items=qa(g["faq"]),
        pups_strip=False,
    )


def _plain(text):
    return re.sub(r"<[^>]+>", "", str(text))


def faq_page(data):
    f = nb(data["delivery_service"]["faq"], "lead")
    cats = []
    used = set()
    for cat in f["categories"]:
        items = [q for q in data["faq"] if q["topic"] in cat["topics"]]
        used.update(q["id"] for q in items)
        cats.append(dict(cat, qs=items + cat["extra"]))
    # every question of faq.json is on this page: a new topic lands in «О питомнике» until it gets its own group
    rest = [q for q in data["faq"] if q["id"] not in used]
    if rest:
        cats[-1]["qs"] = rest + cats[-1]["qs"]
    ld = {  # plain text, before the questions become Markup
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q["q"], "acceptedAnswer": {"@type": "Answer", "text": _plain(q["a"])}}
            for cat in cats for q in cat["qs"]
        ],
    }
    return page(
        "/faq/", "delivery/faq.html.j2",
        "Вопросы и ответы о покупке щенка" + BRAND,
        "Цена и бронь, документы и прививки, доставка, первые дни дома и знакомство с питомником — "
        "короткие ответы на частые вопросы.",
        [("Вопросы и ответы", None)],
        f=f,
        cats=[dict(cat, qs=qa(cat["qs"])) for cat in cats],
        faq_ld=Markup(json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")),
        pups_strip=False,
    )


def contacts_page(data):
    c = nb(data["delivery_service"]["contacts"], "lead", "visit_note")
    c["visit"] = [nb(x, "title", "text") for x in c["visit"]]
    return page(
        "/kontakty/", "delivery/contacts.html.j2",
        "Контакты питомника Puppy House в Москве",
        "Телефон, Telegram и WhatsApp питомника щенков Puppy House. Москва, приезд по записи. "
        "Ответим за 15 минут, ежедневно с 9:00 до 21:00.",
        [("Контакты", None)],
        c=c,
    )


def privacy_page(data):
    p = dict(data["delivery_service"]["privacy"])
    p["sections"] = [dict(s, h=nobr(s["h"]), body=[{k: (nobr(v) if k == "p" else [nobr(li) for li in v]) for k, v in b.items()}
                                                   for b in s["body"]])
                     for s in p["sections"]]
    p["facts"] = [nb(x, "value") for x in p["facts"]]
    return page(
        "/politika-konfidencialnosti/", "delivery/privacy.html.j2",
        "Политика конфиденциальности" + BRAND,
        "Как питомник Puppy House получает, хранит и защищает персональные данные посетителей сайта: "
        "цели, основания, сроки и ваши права по 152-ФЗ.",
        [("Политика конфиденциальности", None)],
        p=p,
        toc_items=[[s["id"], s["h"]] for s in p["sections"]],
        pups_strip=False,
    )


def routes(data):
    cities = data["cities"]
    return ([hub_page(data, cities)] + city_pages(data, cities)
            + [rassrochka_page(data), gift_page(data), faq_page(data), contacts_page(data), privacy_page(data)])
