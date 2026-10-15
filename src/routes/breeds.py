"""Breed hubs: /maltipu/, /francuzskij-buldog/, /toj-pudel/, /border-kolli/ — one data-driven template.
Owns: src/templates/breeds/, src/data/breeds-hub.json (copy per breed + "common"), assets/css/breeds.css.
Breed photos come from breeds.json; puppies (and every count) from puppies.json; the photo / video carousel from
media.json (the breed's set, ordered and topped up in breeds-hub.json → media); the colours from breedsub.json
(the colour cards of /<breed>/vidy-i-okrasy/ — the hub links to each one by its anchor).

Two layouts. "layout": "v2" in breeds-hub.json (maltipu first, client revisions 15.10) → breeds/breed.html.j2:
hero «Щенки в наличии» + «Получить консультацию» → every puppy of the breed → photo / video carousel like the
homepage → colour cards to scroll through, each with «Подобрать …» → «Какой он» → «Как мы отдаём щенка» (what
travels with the puppy, documents, guarantee, delivery, price) → FAQ → articles about the breed → SEO text and the
lead form as on the homepage. Without it — the first hub layout, breeds/hub.html.j2."""

import re

from markupsafe import Markup, escape

from _lib import by_id, crumbs, sort_puppies
from blog import rich
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


def copy_v2(hub):
    """Copy of a v2 breed page with every visible string passed through nobr() (SEO paragraphs: rich(), links allowed)."""
    h = dict(hub)
    for k in ("h1", "lead", "note", "pups_title", "pups_lead", "media_title", "media_lead", "colours_title",
              "colours_lead", "about_title", "faq_title", "blog_title", "blog_lead", "lead_title", "lead_line"):
        h[k] = nobr(h[k])
    h["media_label"] = hub["media_title"]
    h["band"] = dict(title=hub["band"]["title"], line=hub["band"]["line"])  # plain: the macro escapes it, also into data-*
    h["traits"] = [{k: (nobr(v) if k in ("label", "title", "line") else v) for k, v in t.items()} for t in h["traits"]]
    h["faq"] = [dict(q=Markup("<span>") + nobr(f["q"]) + Markup("</span>"), a=nobr(f["a"])) for f in h["faq"]]
    ho = hub["handover"]
    h["handover"] = dict(
        title=nobr(ho["title"]), lead=nobr(ho["lead"]),
        kit=dict(ho["kit"], title=nobr(ho["kit"]["title"]), line=nobr(ho["kit"]["line"]),
                 items=[dict(i, label=nobr(i["label"])) for i in ho["kit"]["items"]]),
        tiles=[dict(t, title=nobr(t["title"]), line=nobr(t["line"])) for t in ho["tiles"]],
    )
    h["seo"] = dict(title=nobr(hub["seo"]["title"]), lead=nobr(hub["seo"]["lead"]),
                    blocks=[dict(h=nobr(b["h"]), p=[rich(x) for x in (b["p"] if isinstance(b["p"], list) else [b["p"]])])
                            for b in hub["seo"]["blocks"]])
    return h


def _teasers(items, data, b):
    """Article cards «Всё о породе»: a blog slug (title, line, cover from blog-posts.json; cover may be overridden)
    or a ready card {url, title, line, cover, topic} (the breed's own guide pages: colours, price)."""
    meta = by_id(data["blog"], "slug")
    posts = data["blog_posts"]["posts"]
    out = []
    for it in items:
        if "slug" in it:
            post = posts[it["slug"]]
            out.append(dict(url=meta[it["slug"]]["url"], title=post["h1"], line=post["card_line"],
                            cover=it.get("cover") or post["cover"], topic=f"{b['name']} · {post['topic'].lower()}"))
        else:
            out.append(dict(it))
    return out


def _colour_pages(b, hub, colours):
    """/<breed>/<colour>/ for every colour of a v2 breed page — one template, copy from breedsub.json."""
    out = []
    for c in colours:
        low = c["title"][:1].lower() + c["title"][1:]
        faq = [
            dict(q=f"{c['title']}: насколько редкий окрас?",
                 a=f"{c['facts'][0]['value']}. Расскажем, есть ли сейчас такие щенки или когда ждём помёт с этим окрасом."),
            dict(q="Изменится ли окрас с возрастом?",
                 a=f"{c['facts'][1]['value']}. Окончательный оттенок видно ближе к году — каким он станет, подскажем по родителям щенка."),
            dict(q=f"Сколько стоит {low}?",
                 a="Цена зависит от поколения, размера, пола и родителей щенка. Пришлём цену щенков этого окраса за 15 минут после заявки."),
            dict(q=f"Можно ли заказать {c['pick']}?",
                 a="Да. Оставьте заявку — подберём щенка из текущих помётов или запишем в лист ожидания и напишем, когда появится малыш этого окраса."),
        ]
        faq = [dict(q=Markup("<span>") + nobr(f["q"]) + Markup("</span>"), a=nobr(f["a"])) for f in faq]
        pups = [p for p in sort_puppies(b["puppies"]) if p["colour"].lower().split(" (")[0] == c["label"].lower()]
        title = f"{c['title']} — купить щенка в Москве | домщенков.рф"
        desc = (f"{c['title']}: {str(c['short'] or '').lower()}. {c['facts'][0]['value']}. Фото и описание окраса, "
                f"щенки в наличии, видео и цена за 15 минут.")
        if len(desc) > 160:   # без строки о редкости
            desc = f"{c['title']}: {str(c['short'] or '').lower()}. Фото и описание окраса, щенки в наличии, видео и цена за 15 минут."
        out.append(dict(
            url=f"{b['urls']['hub']}{c['slug']}/",
            template="breeds/colour.html.j2",
            context=dict(
                title=title,
                description=desc,
                breadcrumbs=crumbs((b["name"], b["urls"]["hub"]), (c["title"], None)),
                b=b, hub=hub, c=c,
                others=[o for o in colours if o["slug"] != c["slug"]],
                pups=pups,
                faq=faq,
                pups_strip=False,
                lead_breed=b["slug"],
            ),
        ))
    return out


def _lower(name):
    """«Той-пудель» → «той-пудель» inside a title: «Чем хорош той-пудель»."""
    return name[:1].lower() + name[1:]


def routes(data):
    breeds = data["breeds"]
    hubs = data["breeds_hub"]
    common = hubs["common"]
    blog = by_id(data["blog"], "slug")
    out = []
    for b in breeds:
        own = dict(hubs[b["slug"]])
        own["faq"] = own["faq"] + common["faq_more"]   # every hub: vaccinations and the lifelong guarantee
        if own.get("layout") == "v2":
            hub = copy_v2(own)
            colours = breed_colours(data, b)
            out.append(dict(
                url=b["urls"]["hub"],
                template="breeds/breed.html.j2",
                context=dict(
                    title=own["title"],
                    description=own["description"],
                    breadcrumbs=crumbs((b["name"], None)),
                    b=b,
                    hub=hub,
                    common=common,
                    reel=_media(own, data["media"].get(b["slug"], []), b["slug"]),
                    pups=sort_puppies(b["puppies"]),
                    colours=colours,
                    # round faces in the band under the carousel: the breed's colours named in breeds-hub.json
                    band_faces=[dict(src=c["photo"]["src"], tone=b["tone"]) for slug in own["band"]["faces"]
                                for c in colours if c["slug"] == slug and c["photo"]],
                    posts=_teasers(own["blog"], data, b),
                    pups_strip=False,          # the page lists every puppy of the breed itself
                    lead_breed=b["slug"],
                ),
            ))
            out += _colour_pages(b, hub, colours)
            continue
        hub = copy_markup(own)

        # «Сравнение пород» (client 15.10): the breed's own page «Чем хорош щенок …» instead of three pair pages,
        # plus its price and varieties pages
        more = hubs["more"]
        compare = [
            dict(url=f"/sravnenie/{b['slug']}/", title=nobr(f"Чем хорош {_lower(b['name'])}"), line=nobr(more["why"]), breed=b),
            dict(url=b["urls"]["price"], title=nobr(f"Цена щенка {b['name_gen']}"), line=nobr(more["price"]),
                 icon="wallet", color="coral"),
            dict(url=b["urls"]["varieties"], title=nobr(more["varieties_title"]), line=nobr(more["varieties"]),
                 icon="ruler", color="mint"),
        ]

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
