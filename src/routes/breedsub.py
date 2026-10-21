"""Breed sub-pages: price /<breed>/cena/ ×4 and varieties /<breed>/vidy-i-okrasy/ ×4 — two data-driven templates.
Owns: src/routes/breedsub.py, src/templates/breedsub/, src/data/breedsub.json, assets/css/breedsub.css.
Copy lives in breedsub.json (common.* + per-breed keys); breed urls and photo alts come from breeds.json,
puppies (the «Щенки в наличии» strip) from puppies.json via the layout (pups_breed). Prices: only the approximate
ranges of the price pages (client 21.10: price_cheap / price_kennel in breedsub.json), never a puppy's own price."""

import copy as _copy
import pathlib
import re

from markupsafe import Markup, escape

from _lib import by_id, crumbs

# Visible copy never breaks inside «той-пуделя», «по-разному» or a range like «2–5 кг»: such words go into
# <span class="nw"> (the macros' |typo keeps Markup tags). Meta title/description, photo alts and text that sits
# directly in a flex box (eyebrow, chips, badges) stay plain text.
_HYPHENATED = re.compile(r"(?<![\w-])((?:\w{1,2} )?\w+(?:-\w+)+)")
_RANGE = re.compile(r"(?<![\w,])(\d+(?:,\d+)?–\d+(?:,\d+)?)(?: (?=[а-яё])(?!(?:и|или|а|но|до|в|во|на|с|со|по|за|из|от|к|у|о)\b))?")
NBSP = " "

# optional keys of a varieties block / a comparison tile (the templates run with StrictUndefined)
BLOCK = dict(lead=None, note=None)
KIND = dict(face=None, tag=None, icon=None, color="sun", badge=None, off=False)

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _big(src):
    """okras-<breed>-<colour>-big.jpg next to the colour photo (tools/okras_tiles.py): the same puppy close up for the
    first screen of the colour page; None when there is no such shot."""
    big = src.replace(".jpg", "-big.jpg")
    return big if (ROOT / big.lstrip("/")).is_file() else None


def nobr(text):
    """Escaped text as Markup with hyphenated words and number ranges kept on one line."""
    if text is None:
        return None
    s = _HYPHENATED.sub(r'<span class="nw">\1</span>', str(escape(text)))
    s = _RANGE.sub(lambda m: f'<span class="nw">{m.group(1)}</span>' + (NBSP if m.group(0).endswith(" ") else ""), s)
    return Markup(s)


def _nb(d, *keys):
    """Copy of dict d with the given text keys passed through nobr()."""
    out = dict(d)
    for k in keys:
        if out.get(k) is not None:
            out[k] = nobr(out[k])
    return out


def _faq(items):
    # the question sits in a flex button next to the «+» icon: one wrapping span keeps it a single flex item
    return [dict(q=Markup("<span>") + nobr(f["q"]) + Markup("</span>"), a=nobr(f["a"])) for f in items]


def _seo(s):
    return dict(title=nobr(s["title"]), lead=nobr(s["lead"]),
                blocks=[dict(h=nobr(b["h"]), p=nobr(b["p"])) for b in s["blocks"]])


def _alts(b):
    """src → alt for every photo of the breed listed in breeds.json (studio, adult, colours)."""
    alts = {b["studio"]["src"]: b["studio"]["alt"], b["adult"]["src"]: b["adult"]["alt"]}
    for c in b["colours"]["items"]:
        if c.get("photo"):
            alts.setdefault(c["photo"]["src"], c["photo"]["alt"])
    return alts


def _price(common, own):
    """Price page copy: common.price + the breed's own keys. «DOCS» in common.incl = the breed's document item."""
    pg = _copy.deepcopy(common)
    pg.update({k: v for k, v in own.items() if k not in ("docs", "cheap_bad", "cheap_good")})
    docs = own.get("docs") or common["docs_rkf"]
    pg["incl"] = [_nb(docs if i == "DOCS" else i, "title", "line") for i in common["incl"]]
    pg["factors"] = [_nb(f, "title", "line") for f in own["factors"]]
    # «Почему не бывает дёшево» (client 21.10): what a cheap puppy saves on vs what the kennel's price is made of —
    # the common points + the breed's own (lists), each side with its price range and a closing line
    pg["cheap_bad"] = [_nb(i, "title", "line") for i in common["cheap_bad"] + own["cheap_bad"]]
    pg["cheap_good"] = [_nb(i, "title", "line") for i in common["cheap_good"] + own["cheap_good"]]
    pg["booking"] = [_nb(s, "title", "text") for s in common["booking"]]
    for k in ("h1", "lead", "factors_lead", "incl_lead", "cheap_lead", "cheap_bad_note", "cheap_good_note", "cta_line",
              "booking_lead", "lead_line"):
        pg[k] = nobr(pg[k])
    pg["faq"] = _faq(own["faq"])
    pg["seo"] = _seo(own["seo"])
    return pg


def _varieties(b, common, own, alts):
    """Varieties page copy. own.blocks are rendered in their order: kinds | colours | std | tips."""
    v = _copy.deepcopy(common)
    v.update(own)
    v["h1"], v["lead"], v["lead_line"] = nobr(v["h1"]), nobr(v["lead"]), nobr(v["lead_line"])
    v["facts"] = [dict(f, value=nobr(f["value"])) for f in own["facts"]]
    v["hero_photo"] = dict(src=own["hero_photo"], alt=alts.get(own["hero_photo"], f"Щенок {b['name_gen']}"))
    blocks = []
    for s in own["blocks"]:
        s = _nb({**BLOCK, **s}, "title", "lead")
        if s["type"] == "kinds":
            s["items"] = [dict(_nb({**KIND, **k}, "title", "line"), rows=[[r[0], nobr(r[1])] for r in k.get("rows", [])])
                          for k in s["items"]]
        elif s["type"] == "colours":
            s["items"] = colour_items(b, s["items"], alts)
            s["note"] = nobr(s["note"])
        elif s["type"] == "std":
            for side in ("ok", "no"):
                c = s[side]
                s[side] = dict(title=nobr(c["title"]), note=nobr(c.get("note")),
                               items=[_nb({"line": None, **i}, "title", "line") for i in c["items"]])
        elif s["type"] == "tips":
            s["title"] = nobr(common["tips_title"])
            s["items"] = [_nb(t, "title", "text") for t in common["tips"] + [own["tip"]]]
        blocks.append(s)
    v["blocks"] = blocks
    v["faq"] = _faq(own["faq"])
    v["seo"] = _seo(own["seo"])
    return v


def colour_items(b, items, alts=None):
    """Colours of a breed (breedsub.json → varieties → the "colours" block): one anchored card each on
    /<breed>/vidy-i-okrasy/ (id = slug) and a round face in the compact colour list on the breed hub.
    photo → its studio shot (alt from breeds.json); no photo → swatch (CSS background of the colour dot)."""
    alts = alts if alts is not None else _alts(b)
    out = []
    for c in items:
        src = c.get("photo")
        out.append(dict(
            slug=c["slug"], label=c["name"], name=nobr(c["name"]), text=nobr(c["text"]),
            badge=c["badge"], std=c.get("std"), swatch=c.get("swatch"), photo_note=c.get("photo_note"),
            pick=c.get("pick"),  # «кремового мальтипу» — the CTA of the colour card on the breed page
            # breed pages v2: the colour's own page /<breed>/<slug>/ (title, one-line card text, facts, about, care)
            title=c.get("title") or c["name"], short=nobr(c["short"]) if c.get("short") else None,
            facts=[dict(label=lb, value=c[k]) for k, lb in (("rarity", "Как часто"), ("age", "С возрастом"), ("nose", "Нос и глаза"))
                   if c.get(k)],
            about=[nobr(x) for x in c.get("about", [])], care=nobr(c["care"]) if c.get("care") else None,
            photo=dict(src=src, alt=alts.get(src, f"{c['name']} щенок {b['name_gen']}"), big=_big(src)) if src else None,
        ))
    return out


def breed_colours(data, b):
    """Colour cards of breed b for other pages (the breed hub): colour_items() of its varieties block."""
    blocks = data["breedsub"][b["slug"]]["varieties"]["blocks"]
    return colour_items(b, next(s["items"] for s in blocks if s["type"] == "colours"))


def _faces(colours, limit=4):
    """Studio photos of the breed's colours for the round faces in the CTA band (puppies only, no adults)."""
    return [c["photo"] for c in colours if c["photo"] and "/parent-" not in c["photo"]["src"]][:limit]


def routes(data):
    copy = data["breedsub"]
    common = copy["common"]
    blog = by_id(data["blog"], "slug")
    out = []
    for b in data["breeds"]:
        own = copy[b["slug"]]
        urls = b["urls"]
        alts = _alts(b)
        links_title = nobr(f"Ещё о {own['name_prep']}")
        hub_tile = dict(url=urls["hub"], title=b["name"], line="О породе и щенки в наличии", breed=b)

        v = _varieties(b, common["varieties"], own["varieties"], alts)
        colours = next((s["items"] for s in v["blocks"] if s["type"] == "colours"), [])
        pg = _price(common["price"], own["price"])

        out.append(dict(
            url=urls["price"],
            template="breedsub/price.html.j2",
            context=dict(
                title=own["price"]["title"],
                description=own["price"]["description"],
                breadcrumbs=crumbs((b["name"], urls["hub"]), ("Цена", None)),
                b=b,
                pg=pg,
                tint=own["tint"],
                faces=_faces(colours),
                links_title=links_title,
                links=[
                    hub_tile,
                    dict(url=urls["varieties"], title=common["price"]["links_varieties_title"],
                         line=nobr(own["price"]["links_varieties_line"]), icon="sparkle", color="lilac"),
                    dict(url="/dokumenty-i-garantii/", title="Документы и гарантии",
                         line="Что получите вместе со щенком", icon="doc", color="sky"),
                    dict(url="/dostavka/", title="Доставка", line="Стоимость назовём при брони",
                         icon="car", color="mint"),
                ],
                pups_breed=b,
                lead_breed=b["slug"],
            ),
        ))

        var_links = [
            hub_tile,
            dict(url=urls["price"], title=common["varieties"]["links_price_title"],
                 line=common["varieties"]["links_price_line"], icon="wallet", color="sun"),
        ]
        care = blog.get(f"{b['slug']}-uhod")
        if care:
            var_links.append(dict(url=care["url"], title=nobr(own["varieties"]["links_care_title"]),
                                  line=nobr(own["varieties"]["links_care_line"]), icon="book", color="mint"))
        var_links.append(dict(url="/podbor-porody/", title="Подобрать породу", line="Тест на 2 минуты",
                              icon="sparkle", color="lilac"))
        out.append(dict(
            url=urls["varieties"],
            template="breedsub/varieties.html.j2",
            context=dict(
                title=own["varieties"]["title"],
                description=own["varieties"]["description"],
                breadcrumbs=crumbs((b["name"], urls["hub"]), ("Виды и окрасы", None)),
                b=b,
                v=v,
                tint=own["tint"],
                links_title=links_title,
                links=var_links,
                pups_breed=b,
                lead_breed=b["slug"],
            ),
        ))
    return out
