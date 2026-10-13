"""Blog: /blog/ and the 9 articles /blog/<slug>/.
Owns: src/templates/blog/, src/data/blog-posts.json (all copy, keyed by slug), assets/css/blog.css, assets/js/blog.js.
The list of articles (url, breed, keywords) comes from the shared blog.json; everything shown on the pages —
titles, leads, covers, article text, FAQ — from blog-posts.json. Read time is computed from the article text."""

import json
import math
import re
from pathlib import Path

from markupsafe import Markup, escape

from _lib import by_id, crumbs

CHARS_PER_MIN = 1300                # silent reading speed, characters with spaces
TONES = Path(__file__).resolve().parents[2] / "tools" / "photo-tones.json"  # measured studio backdrops (read only)
NBSP = " "

# Visible copy never breaks inside «той-пуделя», «бордер-колли» or a range like «2–5 кг» (same rule as breeds.py).
_HYPHENATED = re.compile(r"(?<![\w-])((?:\w{1,2} )?\w+(?:-\w+)+)")
_RANGE = re.compile(r"(?<![\w,])(\d+(?:,\d+)?–\d+(?:,\d+)?)(?: (?=[а-яё])(?!(?:и|или|а|но|до|в|во|на|с|со|по|за|из|от|к|у|о)\b))?")
_LINK = re.compile(r"\[([^\]]+)\]\((/[^)\s]*)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def nobr(text):
    """Escaped text as Markup with hyphenated words and number ranges kept on one line."""
    s = _HYPHENATED.sub(r'<span class="nw">\1</span>', str(escape(text)))
    s = _RANGE.sub(lambda m: f'<span class="nw">{m.group(1)}</span>' + (NBSP if m.group(0).endswith(" ") else ""), s)
    return Markup(s)


def _inline(text):
    """nobr() + **bold**."""
    out, pos = [], 0
    for m in _BOLD.finditer(text):
        out.append(nobr(text[pos:m.start()]))
        out.append(Markup("<b>") + nobr(m.group(1)) + Markup("</b>"))
        pos = m.end()
    out.append(nobr(text[pos:]))
    return Markup("").join(out)


def rich(text):
    """Copy with the blog mini-markup: [label](/url/) → link (root-absolute, the build makes it relative), **x** → <b>."""
    out, pos = [], 0
    for m in _LINK.finditer(text):
        out.append(_inline(text[pos:m.start()]))
        out.append(Markup('<a href="{}">').format(m.group(2)) + _inline(m.group(1)) + Markup("</a>"))
        pos = m.end()
    out.append(_inline(text[pos:]))
    return Markup("").join(out)


def plain(text):
    """Mini-markup removed — for counting, meta and JSON-LD."""
    return _BOLD.sub(r"\1", _LINK.sub(r"\1", text))


def _block_text(b):
    if "p" in b or "h3" in b:
        return [plain(b.get("p") or b.get("h3"))]
    if "ul" in b or "ol" in b:
        return [plain(x) for x in (b.get("ul") or b.get("ol"))]
    if "table" in b:
        return [" ".join(r) for r in b["table"]["rows"]]
    if "callout" in b:
        return [b["callout"].get("title") or "", plain(b["callout"]["text"])]
    if "proscons" in b:
        return b["proscons"]["pros"] + b["proscons"]["cons"]
    if "figure" in b:
        return [b["figure"].get("caption", "")]
    return []


def read_minutes(post):
    parts = [post["intro"]] + [q["q"] + " " + plain(q["a"]) for q in post["faq"]]
    for s in post["sections"]:
        parts.append(s["h2"])
        for b in s["blocks"]:
            parts += _block_text(b)
    return max(3, math.ceil(len(" ".join(parts)) / CHARS_PER_MIN))


def plural(n, one, few, many):
    """plural(3, 'статья', 'статьи', 'статей') -> 'статьи' (same rule as the build's |plural filter)."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def minutes_label(n):
    return f"{n}{NBSP}{plural(n, 'минута', 'минуты', 'минут')}"


def _render_block(b):
    """A block of article copy → dict the template renders (all text as Markup)."""
    if "p" in b:
        return {"type": "p", "html": rich(b["p"])}
    if "h3" in b:
        return {"type": "h3", "html": rich(b["h3"])}
    if "ul" in b or "ol" in b:
        kind = "ul" if "ul" in b else "ol"
        return {"type": kind, "items": [rich(x) for x in b[kind]]}
    if "table" in b:
        t = b["table"]
        return {"type": "table", "caption": t["caption"], "head": [nobr(h) for h in t["head"]], "labels": t["head"],
                "rows": [[nobr(c) for c in r] for r in t["rows"]]}
    if "callout" in b:
        c = b["callout"]
        return {"type": "callout", "kind": c.get("kind", "info"), "title": c.get("title"), "html": rich(c["text"])}
    if "proscons" in b:
        return {"type": "proscons", "pros": [nobr(x) for x in b["proscons"]["pros"]],
                "cons": [nobr(x) for x in b["proscons"]["cons"]]}
    if "figure" in b:
        f = b["figure"]
        return {"type": "figure", "src": f["src"], "alt": f["alt"], "caption": nobr(f.get("caption", ""))}
    raise ValueError(f"unknown block {sorted(b)}")


def _tones():
    try:
        return json.loads(TONES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _card(meta, post, breed, tones, general):
    """Article card for /blog/ and «Читайте также». A measured studio cover takes its own backdrop colours."""
    cover = post["cover"]
    t = tones.get(Path(cover["src"]).stem)
    return dict(
        slug=meta["slug"],
        url=meta["url"],
        topic_key=breed["slug"] if breed else general["key"],
        topic=post["topic"],
        title=nobr(post["h1"]),
        line=nobr(post["card_line"]),
        read=minutes_label(read_minutes(post)),
        cover=cover,
        studio=bool(t),
        tone_class=breed["tone_class"] if breed else "tone--" + general["tone"],
        style=f"--tone:{t['top']};--tone-floor:{t['floor']}" if t else "",
    )


def _ld(meta, post, site_url, page_url, brand):
    """JSON-LD: BlogPosting + FAQPage (plain text, absolute URLs). No dates: the publication date is a placeholder."""
    url = site_url + page_url
    image = site_url + (post["hero"] or post["cover"])["src"]
    graph = [
        {"@type": "BlogPosting", "headline": post["h1"], "description": post["description"], "image": image,
         "inLanguage": "ru", "mainEntityOfPage": url, "keywords": ", ".join(meta.get("keywords") or []),
         "author": {"@type": "Organization", "name": brand, "url": site_url + "/"},
         "publisher": {"@type": "Organization", "name": brand, "url": site_url + "/"}},
        {"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q["q"], "acceptedAnswer": {"@type": "Answer", "text": plain(q["a"])}}
            for q in post["faq"]]},
    ]
    text = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)
    return Markup(text.replace("</", "<\\/"))


def routes(data):
    cfg = data["blog_posts"]
    hub, posts = cfg["hub"], cfg["posts"]
    general = hub["general"]
    metas = by_id(data["blog"], "slug")
    bmap = by_id(data["breeds"], "slug")
    tones = _tones()
    # JSON-LD needs absolute production URLs (the build does not rewrite <script> bodies)
    # the brand domain домщенков.рф in its ASCII (punycode) form — xn--b1adduihee9g.xn--p1ai
    site_url = "https://" + data["site"].get("domain_ascii", data["site"]["domain"].encode("idna").decode())

    cards = {}
    for slug in hub["order"]:
        meta, post = metas[slug], posts[slug]
        breed = bmap.get(meta["breed"]) if meta.get("breed") else None
        cards[slug] = _card(meta, post, breed, tones, general)

    topics = [dict(key=b["slug"], label=b["name_short"], tone_class=b["tone_class"],
                   n=sum(1 for c in cards.values() if c["topic_key"] == b["slug"])) for b in data["breeds"]]
    topics.append(dict(key=general["key"], label=general["label"], tone_class="tone--" + general["tone"],
                       n=sum(1 for c in cards.values() if c["topic_key"] == general["key"])))
    topics = [t for t in topics if t["n"]]

    out = [dict(
        url="/blog/",
        template="blog/hub.html.j2",
        context=dict(
            title=hub["title"],
            description=hub["description"],
            breadcrumbs=crumbs(("Блог", None)),
            hub=dict(hub, h1=nobr(hub["h1"]), lead=nobr(hub["lead"]),
                     more=dict(hub["more"], title=nobr(hub["more"]["title"]), line=nobr(hub["more"]["line"])),
                     seo=dict(title=nobr(hub["seo"]["title"]), lead=nobr(hub["seo"]["lead"]),
                              blocks=[dict(h=nobr(b["h"]), p=nobr(b["p"])) for b in hub["seo"]["blocks"]])),
            articles=[cards[s] for s in hub["order"]],
            topics=topics,
            hero_chips=[
                dict(icon="paw", label=f"{len(data['breeds'])}{NBSP}{plural(len(data['breeds']), 'порода', 'породы', 'пород')}"),
                dict(icon="clock", label="до " + minutes_label(max(read_minutes(posts[s]) for s in hub["order"])) + " чтения"),
            ],
        ),
    )]

    for slug in hub["order"]:
        meta, post = metas[slug], posts[slug]
        breed = bmap.get(meta["breed"]) if meta.get("breed") else None
        hero = post["hero"] or (breed["studio"] if breed else None)
        sections = [dict(id=s["id"], toc=s["toc"], h2=nobr(s["h2"]),
                         blocks=[_render_block(b) for b in s["blocks"]]) for s in post["sections"]]
        cta = post["cta"]
        out.append(dict(
            url=meta["url"],
            template="blog/post.html.j2",
            context=dict(
                title=post["title"],
                description=post["description"],
                breadcrumbs=crumbs(("Блог", "/blog/"), (post["crumb"], None)),
                post=dict(
                    slug=slug,
                    h1=post["h1"],
                    lead=post["lead"],
                    eyebrow=post["eyebrow"],
                    date=post["date"],
                    read=minutes_label(read_minutes(post)),
                    intro=rich(post["intro"]),
                    keyfacts=[dict(label=f["label"], value=nobr(f["value"])) for f in post["keyfacts"]],
                    toc=[[s["id"], s["toc"]] for s in post["sections"]],
                    sections=sections,
                    faq_title=post["faq_title"],
                    # the question sits in a flex button next to the «+» icon: one wrapping span = one flex item
                    faq=[dict(q=Markup("<span>") + nobr(q["q"]) + Markup("</span>"), a=rich(q["a"]))
                         for q in post["faq"]],
                    cta=dict(title=nobr(cta["title"]), line=nobr(cta["line"]),
                             button=cta.get("button") or (dict(url=breed["urls"]["hub"], label="Всё о породе")
                                                          if breed else dict(url="/shchenki/", label="Смотреть щенков")),
                             second=cta.get("second") or (dict(url="/shchenki/?breed=" + breed["slug"],
                                                               label="Щенки в наличии") if breed else None)),
                    related=[cards[s] for s in post["related"]],
                ),
                hero_photo=dict(src=hero["src"], alt=hero["alt"]) if hero else None,  # size: imgsize() in the template
                tone=breed["tone"] if breed else "cream",
                breed=breed,
                ld=_ld(meta, post, site_url, meta["url"], data["site"]["brand"]),
                pups_breed=breed,
                lead_breed=breed["slug"] if breed else None,
            ),
        ))
    return out
