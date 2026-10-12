"""Group «choice»: breed quiz /podbor-porody/, six breed comparisons /sravnenie/<a>-ili-<b>/ (one template + data)
and the starter-kit page /magazin/.
Owns: src/routes/choice.py, src/templates/choice/, src/data/choice.json, src/data/choice-pairs.json,
assets/css/choice.css, assets/js/choice.js.
Breed facts (compare rows, studio photos, urls) come from breeds.json; copy lives in choice*.json. No prices anywhere."""

import re

from markupsafe import Markup, escape

from _lib import by_id, crumbs, sort_puppies

BRAND = " | Puppy House"
TITLE_MAX = 60

# Visible copy never breaks inside «той-пуделя», «бордер-колли» or a range like «2–5 кг»: such words go into
# <span class="nw"> (the macros' |typo keeps Markup tags). Meta title/description and alts stay plain text.
_HYPHENATED = re.compile(r"(?<![\w-])((?:\w{1,2} )?\w+(?:-\w+)+)")
_RANGE = re.compile(r"(?<![\w,])(\d+(?:,\d+)?–\d+(?:,\d+)?)(?: (?=[а-яё])(?!(?:и|или|а|но|до|в|во|на|с|со|по|за|из|от|к|у|о)\b))?")
NBSP = " "


def nobr(text):
    """Escaped text as Markup with hyphenated words and number ranges kept on one line."""
    if text is None:
        return None
    s = _HYPHENATED.sub(r'<span class="nw">\1</span>', str(escape(text)))
    s = _RANGE.sub(lambda m: f'<span class="nw">{m.group(1)}</span>' + (NBSP if m.group(0).endswith(" ") else ""), s)
    return Markup(s)


def _title(t):
    return t + BRAND if len(t + BRAND) <= TITLE_MAX else t


def _faq(items):
    # the question sits in a flex button next to the «+» icon: one wrapping span keeps it a single flex item
    return [dict(q=Markup("<span>") + nobr(f["q"]) + Markup("</span>"), a=nobr(f["a"])) for f in items]


def _seo(s):
    return dict(title=nobr(s["title"]), lead=nobr(s["lead"]),
                blocks=[dict(h=nobr(b["h"]), p=nobr(b["p"])) for b in s["blocks"]])


def _rows(cfg, cols):
    """Comparison rows for ui.cmp_table: breeds.json «compare» + care / life / docs from choice.json."""
    out = []
    for key, label in cfg["compare_rows"]:
        row = [label]
        for b in cols:
            if key == "care":
                v = cfg["care"][b["slug"]]
            elif key == "life":
                v = next(f["value"] for f in b["facts"] if f["key"] == "life")
            elif key == "docs":
                v = cfg["docs"]["rkf" if b["rkf"] else "hybrid"]
            else:
                v = b["compare"][key]
            row.append(nobr(v[:1].upper() + v[1:]))
        out.append(row)
    return out


def _cols(breeds):
    """Table header columns for ui.cmp_table: breed dicts with the name kept on one line («Бордер-колли»)."""
    return [dict(b, name=nobr(b["name"])) for b in breeds]


def _pair_links(pairs, bm, exclude=None):
    """Pill links to the comparison pages: [{url, a, b, label}]"""
    return [dict(url=f"/sravnenie/{p['slug']}/", a=bm[p["a"]], b=bm[p["b"]], label=nobr(p["h1"]))
            for p in pairs if p["slug"] != exclude]


def _pair_pups(a, b, limit=4):
    """Puppies of both breeds for the comparison strip: alternate A and B (available first), fill up from the other."""
    pa, pb = sort_puppies(a["puppies"]), sort_puppies(b["puppies"])
    out = []
    while len(out) < limit and (pa or pb):
        for pool in (pa, pb):
            if pool and len(out) < limit:
                out.append(pool.pop(0))
    # available first inside the strip as well
    return sorted(out, key=lambda p: p["status_order"])


def _quiz(cfg, breeds, bm):
    q = dict(cfg["quiz"])
    order = cfg["breed_order"]
    q["breeds"] = [bm[s] for s in order]
    q["questions"] = [dict(key=x["key"], q=nobr(x["q"]),
                           options=[dict(o, label=nobr(o["label"]), line=nobr(o["line"]), s=",".join(str(n) for n in o["s"]))
                                    for o in x["options"]])
                      for x in cfg["quiz"]["questions"]]
    # per breed: reasons keyed by question (shown when the breed scored ≥ 2 on that answer), defaults, honest note
    q["results"] = []
    for i, slug in enumerate(order):
        b = bm[slug]
        q["results"].append(dict(
            b=b, idx=i,
            reasons=[dict(key=k, text=nobr(v)) for k, v in cfg["quiz"]["reasons"][slug].items()],
            defaults=[nobr(t) for t in cfg["quiz"]["defaults"][slug]],
            honest=nobr(cfg["quiz"]["honest"][slug]),
            facts=[dict(label=f["label"], value=nobr(f["value"])) for f in b["facts"] if f["key"] in ("weight", "height", "life")],
            description=nobr(b["description"]),
        ))
    q["answers"] = [dict(a, title=nobr(a["title"]), line=nobr(a["line"]), breeds=[bm[s] for s in a["breeds"]])
                    for a in cfg["quiz"]["answers"]]
    for k in ("h1", "lead", "test_title", "test_lead", "nojs", "allergy_note", "answers_title", "answers_lead",
              "table_title", "table_lead"):
        q[k] = nobr(q[k])
    q["seo"] = _seo(cfg["quiz"]["seo"])
    q["rows"] = _rows(cfg, q["breeds"])
    q["cols"] = _cols(q["breeds"])
    return q


def _shop(cfg, bm):
    s = dict(cfg["shop"])
    order = cfg["breed_order"]
    s["cats"] = [dict(c, title=nobr(c["title"]), line=nobr(c["line"])) for c in s["cats"]]
    s["groups"] = [dict(title=nobr(g["title"]), items=[nobr(i) for i in g["items"]]) for g in s["groups"]]
    s["tips"] = [dict(url=f"/blog/{slug}-uhod/", breed=bm[slug], title=bm[slug]["name"],
                      line=s["breed_tips"][slug]) for slug in order]
    for k in ("h1", "lead", "cats_title", "cats_lead", "list_title", "list_lead", "breeds_title", "breeds_lead",
              "band_title", "band_line"):
        s[k] = nobr(s[k])
    s["faq"] = _faq(s["faq"])
    s["seo"] = _seo(cfg["shop"]["seo"])
    return s


def routes(data):
    cfg = data["choice"]
    pairs = data["choice_pairs"]
    breeds = data["breeds"]
    bm = by_id(breeds, "slug")
    out = []

    quiz = _quiz(cfg, breeds, bm)
    out.append(dict(
        url="/podbor-porody/",
        template="choice/quiz.html.j2",
        context=dict(
            title=cfg["quiz"]["title"],
            description=cfg["quiz"]["description"],
            breadcrumbs=crumbs((cfg["quiz"]["crumb"], None)),
            qz=quiz,
            pair_links=_pair_links(pairs, bm),
        ),
    ))

    for p in pairs:
        a, b = bm[p["a"]], bm[p["b"]]
        pg = dict(p)
        for k in ("h1", "lead", "verdict"):
            pg[k] = nobr(p[k])
        pg["pick"] = [dict(b=br, title=nobr(f"Выбирайте {br['name_gen']}, если…"), items=[nobr(t) for t in items])
                      for br, items in ((a, p["choose_a"]), (b, p["choose_b"]))]
        pg["pups_title"] = nobr(f"Щенки {a['name_plural_gen']} и {b['name_plural_gen']}")
        pg["faq"] = _faq(p["faq"])
        pg["seo"] = _seo(p["seo"])
        out.append(dict(
            url=f"/sravnenie/{p['slug']}/",
            template="choice/pair.html.j2",
            context=dict(
                title=_title(p["title"]),
                description=p["description"],
                breadcrumbs=crumbs(("Подбор породы", "/podbor-porody/"), (p["h1"], None)),
                pg=pg, a=a, b=b,
                rows=_rows(cfg, [a, b]),
                cols=_cols([a, b]),
                pair_pups=_pair_pups(a, b),
                pair_links=_pair_links(pairs, bm, exclude=p["slug"]),
                links=[
                    dict(url=a["urls"]["price"], breed=a, title=nobr(f"Цена щенка {a['name_gen']}"), line="От чего зависит и что входит"),
                    dict(url=b["urls"]["price"], breed=b, title=nobr(f"Цена щенка {b['name_gen']}"), line="От чего зависит и что входит"),
                    dict(url="/podbor-porody/", icon="sparkle", color="lilac", title="Подбор породы", line="Тест на 2 минуты"),
                ],
            ),
        ))

    shop = _shop(cfg, bm)
    out.append(dict(
        url="/magazin/",
        template="choice/shop.html.j2",
        context=dict(
            title=cfg["shop"]["title"],
            description=cfg["shop"]["description"],
            breadcrumbs=crumbs((cfg["shop"]["crumb"], None)),
            sh=shop,
        ),
    ))
    return out
