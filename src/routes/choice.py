"""Group «choice»: breed quiz /podbor-porody/, «Сравнение пород» — four breed pages /sravnenie/<breed>/
«Чем хорош щенок …» (one template + data; client 15.10: they replaced the six pair pages /sravnenie/<a>-ili-<b>/).
The starter-kit page /magazin/ was removed (client 21.10).
Owns: src/routes/choice.py, src/templates/choice/, src/data/choice.json, src/data/choice-breeds.json,
assets/css/choice.css, assets/js/choice.js.
Breed facts (compare rows, studio photos, urls) come from breeds.json; copy lives in choice*.json. No prices anywhere."""

import re

from markupsafe import Markup, escape

from _lib import by_id, crumbs
from breedsub import breed_colours

BRAND = " | домщенков.рф"
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


_LINK = re.compile(r"\[([^\]]+)\]\((/[^)\s]*)\)")


def md(text):
    """nobr() + «[label](/url/)» links (FAQ answers): the URL itself is never touched by nobr()."""
    out, pos = Markup(""), 0
    for m in _LINK.finditer(text):
        out += nobr(text[pos:m.start()]) + Markup('<a href="%s">') % m.group(2) + nobr(m.group(1)) + Markup("</a>")
        pos = m.end()
    return out + nobr(text[pos:])


def _title(t):
    return t + BRAND if len(t + BRAND) <= TITLE_MAX else t


def _faq(items):
    # the question sits in a flex button next to the «+» icon: one wrapping span keeps it a single flex item
    return [dict(q=Markup("<span>") + nobr(f["q"]) + Markup("</span>"), a=md(f["a"])) for f in items]


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


def _lower(name):
    """«Той-пудель» → «той-пудель» (inside a sentence)."""
    return name[:1].lower() + name[1:]


def _why_url(b, other=None):
    """/sravnenie/<breed>/ — «Чем хорош щенок …»; other → the card «<breed> или <other>» on that page."""
    return f"/sravnenie/{b['slug']}/" + (f"#ili-{other['slug']}" if other else "")


def _why_links(cfg, breeds):
    """Pill links to the four breed pages: [{url, faces, label}]"""
    tpl = cfg["common"]["more"]
    return [dict(url=_why_url(b), faces=[b], label=nobr(tpl.format(lname=_lower(b["name"])))) for b in breeds]


def _fmt(tpl, b):
    return tpl.format(name=b["name"], lname=_lower(b["name"]), gen=b["name_gen"], pgen=b["name_plural_gen"])


def _breed_page(cfg, b, bm, order, blog, colours):
    """Context of /sravnenie/<breed>/: copy (Markup), the other three breeds as pair cards, links."""
    com, own = cfg["common"], cfg["breeds"][b["slug"]]
    pg = dict(own)
    for k in ("h1", "lead"):
        pg[k] = nobr(own[k])
    pg["adv"] = [dict(a, title=nobr(a["title"]), line=nobr(a["line"])) for a in own["advantages"]]
    pg["adv_title"] = nobr(own["adv_title"])
    pg["adv_lead"] = nobr(_fmt(com["adv_lead"], b))
    pg["fit_title"] = nobr(_fmt(com["fit_title"], b))
    pg["fit"] = [nobr(t) for t in own["fit"]]
    pg["unfit"] = [nobr(t) for t in own["unfit"]]
    pg["others_title"] = nobr(_fmt(com["others_title"], b))
    pg["band_line"] = nobr(_fmt(com["band_line"], b))
    pg["pups_title"] = nobr(_fmt(com["pups_title"], b))
    pg["faq"] = _faq(own["faq"])

    # «<порода> и другие породы»: one card per other breed (breeds.json order), this breed always first.
    # A pair's «lead» is written in a → b order; on b's page «lead_b» (if any) names the two breeds the other way round.
    pairs = {frozenset((p["a"], p["b"])): p for p in cfg["pairs"]}
    others = []
    for o in sorted((x for x in bm.values() if x is not b), key=lambda x: order.index(x["slug"])):
        p = pairs[frozenset((b["slug"], o["slug"]))]
        is_a = p["a"] == b["slug"]
        mine, theirs = (p["a_if"], p["b_if"]) if is_a else (p["b_if"], p["a_if"])
        others.append(dict(
            id=f"ili-{o['slug']}", b=b, o=o, title=nobr(f"{b['name']} или {_lower(o['name'])}"),
            lead=nobr(p["lead"] if is_a else p.get("lead_b") or p["lead"]),
            picks=[dict(b=x, name=nobr(x["name"]), text=nobr(com["pick"].format(text=t))) for x, t in ((b, mine), (o, theirs))],
            more=dict(url=_why_url(o), label=_fmt(com["more"], o)),
        ))
    pg["others"] = others
    # collapsed SEO text «Почему выбирают …»: about this breed only (client 15.10: no comparison with our other dogs)
    pg["seo"] = _seo(own["seo"])

    ln, cl = com["links"], own["links"]
    links = [
        dict(url=b["urls"]["hub"], breed=b, title=nobr(f"Щенки {b['name_gen']}"), line=ln["hub_line"]),
        dict(url=b["urls"]["price"], icon="wallet", color="sun", title=nobr(f"Цена щенка {b['name_gen']}"), line=ln["price_line"]),
        dict(url=b["urls"]["varieties"], icon="ruler", color="mint", title=ln["varieties_title"], line=ln["varieties_line"]),
        dict(url=blog[f"{b['slug']}-harakter"]["url"], icon="book", color="coral", title=nobr(cl["char_title"]), line=cl["char_line"], cta="Читать"),
        dict(url=blog[f"{b['slug']}-uhod"]["url"], icon="book", color="sky", title=nobr(cl["care_title"]), line=cl["care_line"], cta="Читать"),
        dict(url="/podbor-porody/", icon="sparkle", color="lilac", title=ln["quiz_title"], line=ln["quiz_line"]),
    ]
    # round faces in the CTA band: the breed's colours (studio shots of puppies, as on /<breed>/cena/)
    faces = [c["photo"] for c in colours if c["photo"] and "/parent-" not in c["photo"]["src"]][:4]
    return pg, links, faces


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
    q["cols"] = q["breeds"]  # ui.cmp_table keeps «Бордер-колли» on one line itself
    return q


def routes(data):
    cfg = data["choice"]
    why = data["choice_breeds"]
    breeds = data["breeds"]
    bm = by_id(breeds, "slug")
    order = [b["slug"] for b in breeds]
    blog = by_id(data["blog"], "slug")
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
            why_links=_why_links(why, quiz["breeds"]),
        ),
    ))

    com = why["common"]
    for b in breeds:
        own = why["breeds"][b["slug"]]
        pg, links, faces = _breed_page(why, b, bm, order, blog, breed_colours(data, b))
        out.append(dict(
            url=_why_url(b),
            template="choice/breed.html.j2",
            context=dict(
                title=_title(own["title"]),
                description=own["description"],
                breadcrumbs=crumbs((b["name"], b["urls"]["hub"]), (own["crumb"], None)),
                pg=pg, com=com, b=b,
                links=links,
                faces=faces,
                pups_breed=b,
                lead_breed=b["slug"],
            ),
        ))

    return out
