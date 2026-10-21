"""Group «choice»: breed quiz /podbor-porody/, «Сравнение пород» — four breed pages /sravnenie/<breed>/
«Чем хорош щенок …» (one template + data; client 15.10: they replaced the six pair pages /sravnenie/<a>-ili-<b>/).
Client 21.10: «Кому подойдёт» = the photo cards of the puppy pages (puppy.json → breeds → fits), then three plates
«Лучше подобрать другую породу» with the reason, the comparison table of all breeds, 8 puppies of the breed.
The starter-kit page /magazin/ was removed (client 21.10).
Owns: src/routes/choice.py, src/templates/choice/, src/data/choice.json, src/data/choice-breeds.json,
assets/css/choice.css, assets/js/choice.js.
Breed facts (compare rows, studio photos, urls) come from breeds.json; copy lives in choice*.json. No prices anywhere."""

import re

from markupsafe import Markup, escape

from _lib import by_id, crumbs, sort_puppies
from breedsub import breed_colours

BRAND = " | домщенков.рф"
TITLE_MAX = 60
CATALOG_PUPS = 8  # «Щенки <породы> в наличии» on /sravnenie/<breed>/: 4 / 2 per row; 6 at three per row (choice.css)

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


def _why_url(b):
    """/sravnenie/<breed>/ — «Чем хорош щенок …» (its comparison table: #sravnenie)."""
    return f"/sravnenie/{b['slug']}/"


def _why_links(cfg, breeds):
    """Pill links to the four breed pages: [{url, faces, label}]"""
    tpl = cfg["common"]["more"]
    return [dict(url=_why_url(b), faces=[b], label=nobr(tpl.format(lname=_lower(b["name"])))) for b in breeds]


def _fmt(tpl, b):
    return tpl.format(name=b["name"], lname=_lower(b["name"]), gen=b["name_gen"], pgen=b["name_plural_gen"])


def _breed_page(cfg, b, bm, order, colours, compare, fits):
    """Context of /sravnenie/<breed>/: copy (Markup), «Кому подойдёт» photo cards, «Лучше подобрать другую породу»,
    the comparison table (this breed first). «Читайте также» — blocks.read_more."""
    com, own = cfg["common"], cfg["breeds"][b["slug"]]
    pg = dict(own)
    for k in ("h1", "lead"):
        pg[k] = nobr(own[k])
    pg["adv"] = [dict(a, title=nobr(a["title"]), line=nobr(a["line"])) for a in own["advantages"]]
    pg["adv_title"] = nobr(own["adv_title"])
    pg["adv_lead"] = nobr(_fmt(com["adv_lead"], b))
    pg["fit_title"] = nobr(_fmt(com["fit_title"], b))
    pg["fits"] = [dict(f, title=nobr(f["title"]), line=nobr(f["line"])) for f in fits]
    pg["unfit_title"] = nobr(com["unfit_title"])
    pg["unfit_lead"] = nobr(_fmt(com["unfit_lead"], b))
    pg["unfit"] = [dict(title=nobr(u["title"]), text=nobr(u["text"])) for u in own["unfit"]]
    pg["table_title"] = nobr(_fmt(com["table_title"], b))
    pg["table_lead"] = nobr(com["table_lead"])
    cols = [b] + sorted((x for x in bm.values() if x is not b), key=lambda x: order.index(x["slug"]))
    pg["table_cols"], pg["table_rows"] = cols, _rows(compare, cols)
    pg["band_line"] = nobr(_fmt(com["band_line"], b))
    pg["pups_title"] = nobr(_fmt(com["pups_title"], b))
    # inside the flex button «Все щенки <span>бордер-колли</span>» must stay one flex item: no gap before the breed
    pg["catalog_button"] = Markup("<span>") + nobr(_fmt(com["catalog_button"], b)) + Markup("</span>")
    pg["catalog"] = sort_puppies(b["puppies"])[:CATALOG_PUPS]
    pg["faq"] = _faq(own["faq"])
    # collapsed SEO text «Почему выбирают …»: about this breed only (client 15.10: no comparison with our other dogs)
    pg["seo"] = _seo(own["seo"])

    # round faces in the CTA band: the breed's colours (studio shots of puppies, as on /<breed>/cena/)
    faces = [c["photo"] for c in colours if c["photo"] and "/parent-" not in c["photo"]["src"]][:4]
    return pg, faces


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
    # «Щенки в наличии» (client 21.10): two puppies of every breed, breed after breed in each row of four
    per = [sort_puppies(b["puppies"]) for b in q["breeds"]]
    q["catalog"] = [pups[i] for i in range(2) for pups in per if len(pups) > i]
    return q


def routes(data):
    cfg = data["choice"]
    why = data["choice_breeds"]
    breeds = data["breeds"]
    bm = by_id(breeds, "slug")
    order = [b["slug"] for b in breeds]
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
        pg, faces = _breed_page(why, b, bm, order, breed_colours(data, b), cfg,
                                data["puppy"]["breeds"][b["slug"]]["fits"])
        out.append(dict(
            url=_why_url(b),
            template="choice/breed.html.j2",
            context=dict(
                title=_title(own["title"]),
                description=own["description"],
                breadcrumbs=crumbs((b["name"], b["urls"]["hub"]), (own["crumb"], None)),
                pg=pg, com=com, b=b,
                faces=faces,
                pups_breed=b,
                lead_breed=b["slug"],
            ),
        ))

    return out
