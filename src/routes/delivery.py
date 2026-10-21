"""Service pages (group «delivery»):
    /dostavka/ (cities.json grouped by distance, links to the city pages /<slug>/ of routes/home.py), /rassrochka/,
    /shchenok-v-podarok/, /faq/, /kontakty/, /politika-konfidencialnosti/.
Owns: src/templates/delivery/, src/data/delivery.json, delivery-service.json, assets/css/delivery.css.
Copy lives in the data files; this module only prepares it (unbreakable words, filled placeholders)."""

import json
import re

from markupsafe import Markup

from _lib import NBSP, by_id, crumbs, nb, nobr

TITLE_MAX, DESC_MAX = 60, 160
BRAND = " | домщенков.рф"


# ---------------------------------------------------------------- helpers
def plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def fill(text, **kw):
    """str.format for copy templates; unknown keys stay as they are."""
    return re.sub(r"\{(\w+)\}", lambda m: str(kw.get(m.group(1), m.group(0))), text)


def qa(items):
    """FAQ items for blocks.faq_*: the question in one <span> (the button is a flex box), both kept unbroken."""
    return [{"q": Markup("<span>") + nobr(i["q"]) + Markup("</span>"), "a": nobr(i["a"])} for i in items]


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
    hub = nb(d["hub"], "lead", "lead_title", "lead_line")
    msk = nb(hub["moscow"], "lead", "box_line", "pickup")
    msk["steps"] = [nb(x, "title", "text") for x in msk["steps"]]
    hub["moscow"] = msk
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
    c = nb(data["delivery_service"]["contacts"], "lead", "lead_no_phone", "visit_note")
    c["visit"] = [nb(x, "title", "text") for x in c["visit"]]
    return page(
        "/kontakty/", "delivery/contacts.html.j2",
        "Контакты питомника домщенков.рф в Москве",
        "Контакты питомника щенков домщенков.рф: почта, адрес в Москве и карта проезда. Приезд по записи, "
        "ответим в течение рабочего дня.",
        [("Контакты", None)],
        c=c,
        pups_strip=False,
        blog_strip=False,
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
        "Как питомник домщенков.рф получает, хранит и защищает персональные данные посетителей сайта: "
        "цели, основания, сроки и ваши права по 152-ФЗ.",
        [("Политика конфиденциальности", None)],
        p=p,
        toc_items=[[s["id"], s["h"]] for s in p["sections"]],
        pups_strip=False,
    )


def routes(data):
    cities = data["cities"]
    return [hub_page(data, cities), rassrochka_page(data), gift_page(data), faq_page(data), contacts_page(data),
            privacy_page(data)]
