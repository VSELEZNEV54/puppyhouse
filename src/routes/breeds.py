"""Breed hubs: /maltipu/, /francuzskij-buldog/, /toj-pudel/, /border-kolli/ — one data-driven template.
Owns: src/templates/breeds/, src/data/breeds-hub.json (copy per breed + "common"), assets/css/breeds.css.
Breed photos come from breeds.json; puppies (and every count) from puppies.json; the photo / video carousel from
media.json (the breed's set, ordered and topped up in breeds-hub.json → media); the colours from breedsub.json
(the colour cards of /<breed>/vidy-i-okrasy/ — the hub links to each one by its anchor)."""

import re

from markupsafe import Markup, escape

from _lib import by_id, crumbs, sort_puppies
from breedsub import breed_colours


def _media(hub, shared, slug):
    """Photo / video carousel of a hub: breeds-hub.json → media in its order — a string is the src of an item of
    the breed's media.json set (so a video file added there shows here too), a dict is an extra placeholder item.
    Items of the shared set the list forgets are appended, so nothing the client adds there gets lost."""
    by_src = {m["src"]: m for m in shared}
    out, used = [], set()
    for m in hub.get("media", []):
        if isinstance(m, str):
            if m not in by_src:
                raise ValueError(f"breeds-hub.json {slug}.media: {m} is not in media.json → {slug}")
            used.add(m)
            m = by_src[m]
        out.append(dict({"video": None, "pos": None}, **m))
    out += [dict({"video": None, "pos": None}, **m) for m in shared if m["src"] not in used]
    return out


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
TEXT_KEYS = ("h1", "lead", "note", "pups_title", "about_title", "colours_title", "colours_lead",
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
    h["media_label"] = h["media_title"]          # plain text for the carousel's aria-label
    h["media_title"] = nobr(h["media_title"])
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
    common = hubs["common"]
    blog = by_id(data["blog"], "slug")
    out = []
    for b in breeds:
        own = dict(hubs[b["slug"]])
        own["faq"] = own["faq"] + common["faq_more"]   # every hub: vaccinations and the lifelong guarantee
        hub = copy_markup(own)

        compare = []
        for other in breeds:
            if other is b:
                continue
            url = _pair_url(b["slug"], other["slug"], order)
            pair = url.strip("/").split("/")[-1]
            first, second = (b, other) if order.index(b["slug"]) < order.index(other["slug"]) else (other, b)
            # «Мальтипу или француз», «Француз или той-пудель»: the long bulldog name would wrap the tile title
            short = lambda x: "Француз" if x["slug"] == "francuzskij-buldog" else x["name"]
            compare.append(dict(url=url, title=nobr(f"{short(first)} или {_lower(short(second))}"),
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
                common=common,
                reel=_media(own, data["media"].get(b["slug"], []), b["slug"]),
                pups=sort_puppies(b["puppies"]),
                colours=breed_colours(data, b),
                links=compare + reading,
                pups_strip=False,          # the hub lists every puppy of the breed itself
                lead_breed=b["slug"],
            ),
        ))
    return out
