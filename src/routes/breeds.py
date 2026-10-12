"""Breed hubs: /maltipu/, /francuzskij-buldog/, /toj-pudel/, /border-kolli/ — one data-driven template.
Owns: src/templates/breeds/, src/data/breeds-hub.json (copy per breed), assets/css/breeds.css.
Breed facts, photos and colours come from breeds.json; puppies (and every count) from puppies.json."""

import json
import re
from pathlib import Path

from markupsafe import Markup, escape

from _lib import by_id, crumbs, sort_puppies

PHOTO_TILES = 3  # colour photos in the «Окрасы» row; the fourth tile lists the remaining colours
TONES = Path(__file__).resolve().parents[2] / "tools" / "photo-tones.json"  # measured studio backdrops (read only)


def _mix(hexes):
    """Average colour of '#RRGGBB' values."""
    rgb = [[int(h[i:i + 2], 16) for i in (1, 3, 5)] for h in hexes]
    return "#" + "".join(f"{round(sum(c) / len(c)):02X}" for c in zip(*rgb))


def _more_style(tiles):
    """«Ещё окрасы» tile: the average measured top / floor of the photo tiles beside it, so the row reads as one."""
    try:
        tones = json.loads(TONES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    found = [tones.get(Path(t["photo"]["src"]).stem) for t in tiles]
    found = [t for t in found if t]
    if not found:
        return ""
    return f"--tone-top:{_mix([t['top'] for t in found])};--tone-floor:{_mix([t['floor'] for t in found])}"


def _pair_url(a, b, order):
    """/sravnenie/<a>-ili-<b>/ — the pair is always written in breeds.json order (as in the brief)."""
    a, b = sorted((a, b), key=order.index)
    return f"/sravnenie/{a}-ili-{b}/"


# Visible copy never breaks inside «той-пуделя», «о бордер-колли» or a range like «2–5 кг»: such words go into
# <span class="nw"> (the macros' |typo keeps Markup tags). Meta title/description, photo alts and text that sits
# directly in a flex box (eyebrow, badges, chips — a span there would become a separate flex item) stay plain text.
_HYPHENATED = re.compile(r"(?<![\w-])((?:\w{1,2} )?\w+(?:-\w+)+)")
_RANGE = re.compile(r"(?<![\w,])(\d+(?:,\d+)?–\d+(?:,\d+)?)(?: (?=[а-яё])(?!(?:и|или|а|но|до|в|во|на|с|со|по|за|из|от|к|у|о)\b))?")
NBSP = "\u00a0"
TEXT_KEYS = ("h1", "lead", "pups_title", "about_title", "colours_title", "colours_lead", "more_title",
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
    # the question sits in a flex button next to the «+» icon: one wrapping span keeps it a single flex item
    h["faq"] = [dict(q=Markup("<span>") + nobr(f["q"]) + Markup("</span>"), a=nobr(f["a"])) for f in h["faq"]]
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
        more = [c["name"] for c in colours if c not in with_photo]

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
                more_style=_more_style(tiles),
                links=compare + reading,
                pups_strip=False,          # the hub lists every puppy of the breed itself
                lead_breed=b["slug"],
            ),
        ))
    return out
