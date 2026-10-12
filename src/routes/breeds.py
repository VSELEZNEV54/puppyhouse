"""Breed hubs: /maltipu/, /francuzskij-buldog/, /toj-pudel/, /border-kolli/ — one data-driven template.
Owns: src/templates/breeds/, src/data/breeds-hub.json (copy per breed), assets/css/breeds.css.
Breed facts, photos and colours come from breeds.json; puppies (and every count) from puppies.json."""

import re

from markupsafe import Markup, escape

from _lib import by_id, crumbs, sort_puppies

PHOTO_TILES = 3  # colour photos in the «Окрасы» row; the fourth tile lists the remaining colours


def _pair_url(a, b, order):
    """/sravnenie/<a>-ili-<b>/ — the pair is always written in breeds.json order (as in the brief)."""
    a, b = sorted((a, b), key=order.index)
    return f"/sravnenie/{a}-ili-{b}/"


# Visible copy never breaks inside «той-пуделя», «о бордер-колли» or a range like «2–5 кг»: such words go into
# <span class="nw"> (the macros' |typo keeps Markup tags). Meta title/description and photo alts stay plain text.
_HYPHENATED = re.compile(r"(?<![\w-])((?:\w{1,2} )?\w+(?:-\w+)+)")
_RANGE = re.compile(r"(?<![\w,])(\d+(?:,\d+)?–\d+(?:,\d+)?)(?: (?=[а-яё])(?!(?:и|или|а|но|до|в|во|на|с|со|по|за|из|от|к|у|о)\b))?")
NBSP = "\u00a0"
TEXT_KEYS = ("h1", "eyebrow", "lead", "pups_title", "about_title", "colours_title", "colours_lead", "more_title",
             "price_title", "parents_line", "docs_line", "faq_title", "lead_title", "lead_line")


def nobr(text):
    """Escaped text as Markup with hyphenated words and number ranges kept on one line."""
    s = _HYPHENATED.sub(r'<span class="nw">\1</span>', str(escape(text)))
    s = _RANGE.sub(lambda m: f'<span class="nw">{m.group(1)}</span>' + (NBSP if m.group(0).endswith(" ") else ""), s)
    return Markup(s)


def copy_markup(hub):
    """The page copy with every visible string passed through nobr()."""
    h = dict(hub)
    for k in TEXT_KEYS:
        h[k] = nobr(h[k])
    h["facts"] = [dict(f, value=nobr(f["value"])) for f in h["facts"]]
    h["traits"] = [{k: (nobr(v) if k in ("label", "title", "line") else v) for k, v in t.items()} for t in h["traits"]]
    h["price_factors"] = [nobr(f) for f in h["price_factors"]]
    h["docs"] = [nobr(d) for d in h["docs"]]
    h["faq"] = [dict(q=nobr(f["q"]), a=nobr(f["a"])) for f in h["faq"]]
    h["seo"] = dict(title=nobr(h["seo"]["title"]), lead=nobr(h["seo"]["lead"]),
                    blocks=[dict(h=nobr(b["h"]), p=nobr(b["p"])) for b in h["seo"]["blocks"]])
    return h


def _lower(name):
    """«Той-пудель» → «той-пудель» for the second name in «Мальтипу или той-пудель»."""
    return name[:1].lower() + name[1:]


def routes(data):
    breeds = data["breeds"]
    order = [b["slug"] for b in breeds]
    hubs = data["breeds_hub"]
    blog = by_id(data["blog"], "slug")
    out = []
    for b in breeds:
        hub = copy_markup(hubs[b["slug"]])

        # «Окрасы»: up to three photo tiles (standard colours first), the rest by name in one tile
        colours = b["colours"]["items"]
        with_photo = [c for c in colours if c.get("photo") and c.get("standard") is not False][:PHOTO_TILES]
        tiles = [dict(photo=c["photo"], title=nobr(c["name"][:1].upper() + c["name"][1:]),
                      badge="стандарт FCI" if c.get("standard") else None) for c in with_photo]
        more = [nobr(c["name"]) for c in colours if c not in with_photo]

        compare = []
        for other in breeds:
            if other is b:
                continue
            url = _pair_url(b["slug"], other["slug"], order)
            pair = url.strip("/").split("/")[-1]
            first, second = (b, other) if order.index(b["slug"]) < order.index(other["slug"]) else (other, b)
            compare.append(dict(url=url, title=nobr(f"{first['name']} или {_lower(second['name'])}"),
                                line=nobr(hubs["compare"][pair]), breed=other))

        reading = [dict(url=blog[a["slug"]]["url"], title=nobr(a["title"]), line=nobr(a["line"]), icon="book",
                        color=("sun" if i == 0 else "sky")) for i, a in enumerate(hub["articles"])]
        reading.append(dict(url="/podbor-porody/", title="Подобрать породу", line="Тест на 2 минуты",
                            icon="sparkle", color="lilac"))

        out.append(dict(
            url=b["urls"]["hub"],
            template="breeds/hub.html.j2",
            context=dict(
                title=hub["title"],
                description=hub["description"],
                breadcrumbs=crumbs((b["name"], None)),
                b=b,
                hub=hub,
                pups=sort_puppies(b["puppies"]),
                colour_tiles=tiles,
                more_colours=more,
                links=compare + reading,
                pups_strip=False,          # the hub lists every puppy of the breed itself
                lead_breed=b["slug"],
            ),
        ))
    return out
