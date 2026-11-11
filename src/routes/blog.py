"""Blog: /blog/ (filters «Тема» × «Порода») and the articles /blog/<slug>/.
Owns: src/templates/blog/, src/data/blog-posts.json (all copy, keyed by slug), assets/css/blog.css, assets/js/blog.js.
Two sources of articles, one format of copy:
  • the first eleven: list (url, breed, keywords) in the shared blog.json, copy in blog-posts.json → posts[slug];
  • the content factory (content/blog/README.md): one file per article, content/blog/posts/<slug>.json =
    {slug, breed, keywords, status, post: {…the same fields as blog-posts.json posts…}}.
An article goes out on its publication day: content/blog/published.json → posts[slug] = {date, links}. Its route then
carries live=True and the build publishes it without a line in publish.json. The date is shown on the page and goes
into JSON-LD; links=0 (the first month of the plan) renders the in-text links as plain words.
/blog/ lists the published articles, newest first, then the first eleven that are not out yet (as before: their cards
lead to the toast «Раздел скоро откроется»). Factory drafts that are not out are built only by --all / --full
(preview); a broken draft is skipped with a warning, a broken published article stops the module.
Read time is computed from the article text."""

import datetime
import json
import math
import re
import sys
from pathlib import Path

from markupsafe import Markup, escape

from _lib import by_id, crumbs

CHARS_PER_MIN = 1300                # silent reading speed, characters with spaces
TONES = Path(__file__).resolve().parents[2] / "tools" / "photo-tones.json"  # measured studio backdrops (read only)
FACTORY = Path(__file__).resolve().parents[2] / "content" / "blog"  # the content factory: posts/, published.json
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
          "ноября", "декабря")
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


def rich(text, links=True):
    """Copy with the blog mini-markup: [label](/url/) → link (root-absolute, the build makes it relative), **x** → <b>.
    links=False: the label stays, the link goes (articles of the first month: no links in the text)."""
    out, pos = [], 0
    for m in _LINK.finditer(text):
        out.append(_inline(text[pos:m.start()]))
        if links:
            out.append(Markup('<a href="{}">').format(m.group(2)) + _inline(m.group(1)) + Markup("</a>"))
        else:
            out.append(_inline(m.group(1)))
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
    return []  # photos: no text


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


def _render_block(b, links=True):
    """A block of article copy → dict the template renders (all text as Markup)."""
    if "p" in b:
        return {"type": "p", "html": rich(b["p"], links)}
    if "h3" in b:
        return {"type": "h3", "html": rich(b["h3"], links)}
    if "ul" in b or "ol" in b:
        kind = "ul" if "ul" in b else "ol"
        return {"type": kind, "items": [rich(x, links) for x in b[kind]]}
    if "table" in b:
        t = b["table"]
        return {"type": "table", "caption": t["caption"], "head": [nobr(h) for h in t["head"]], "labels": t["head"],
                "rows": [[nobr(c) for c in r] for r in t["rows"]]}
    if "callout" in b:
        c = b["callout"]
        return {"type": "callout", "kind": c.get("kind", "info"), "title": c.get("title"), "html": rich(c["text"], links)}
    if "proscons" in b:
        return {"type": "proscons", "pros": [nobr(x) for x in b["proscons"]["pros"]],
                "cons": [nobr(x) for x in b["proscons"]["cons"]]}
    if "figure" in b:
        f = b["figure"]
        return {"type": "figure", "src": f["src"], "alt": f["alt"], "caption": nobr(f.get("caption", ""))}
    if "photos" in b:
        return {"type": "photos", "items": [dict(src=p["src"], alt=p["alt"]) for p in b["photos"]]}
    raise ValueError(f"unknown block {sorted(b)}")


def _tones():
    try:
        return json.loads(TONES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _card(meta, post, breed, tones, tag):
    """Article card for /blog/ and «Читайте также». A measured studio cover takes its own backdrop colours.
    tag / breed: the two filters of /blog/ (data-tag, data-breed on the card's <li>)."""
    cover = post["cover"]
    t = tones.get(Path(cover["src"]).stem)
    return dict(
        slug=meta["slug"],
        url=meta["url"],
        tag=tag,
        breed=breed["slug"] if breed else "",
        topic=post["topic"],
        title=nobr(post["h1"]),
        line=nobr(post["card_line"]),
        read=minutes_label(read_minutes(post)),
        cover=cover,
        studio=bool(t),
        tone_class=breed["tone_class"] if breed else "tone--cream",
        style=f"--tone:{t['top']};--tone-floor:{t['floor']}" if t else "",
    )


def _ld(meta, post, site_url, page_url, brand, date=None):
    """JSON-LD: BlogPosting + FAQPage (plain text, absolute URLs). datePublished only for a published article
    (content/blog/published.json); before that the date is a placeholder."""
    url = site_url + page_url
    image = site_url + (post["hero"] or post["cover"])["src"]
    posting = {"@type": "BlogPosting", "headline": post["h1"], "description": post["description"], "image": image,
               "inLanguage": "ru", "mainEntityOfPage": url, "keywords": ", ".join(meta.get("keywords") or []),
               "author": {"@type": "Organization", "name": brand, "url": site_url + "/"},
               "publisher": {"@type": "Organization", "name": brand, "url": site_url + "/"}}
    if date:
        posting.update(datePublished=date, dateModified=date)
    graph = [
        posting,
        {"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q["q"], "acceptedAnswer": {"@type": "Answer", "text": plain(q["a"])}}
            for q in post["faq"]]},
    ]
    text = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)
    return Markup(text.replace("</", "<\\/"))


def _date_label(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{d.day}{NBSP}{MONTHS[d.month - 1]} {d.year}"


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _factory(legacy_slugs):
    """(metas, posts, published) of the content factory. published: slug → {date, links} for every article that is
    out, the first eleven included. A draft whose file is broken is skipped with a warning (it is not out);
    a published one that is broken raises: the build must not silently drop a page that is on the site."""
    pub = _read_json(FACTORY / "published.json", {}).get("posts", {})
    for slug, e in pub.items():
        datetime.date.fromisoformat(e["date"])  # a bad date stops the module
    metas, posts = {}, {}
    for path in sorted((FACTORY / "posts").glob("*.json")):
        slug = path.stem
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            if d.get("slug") != slug:
                raise ValueError(f"slug «{d.get('slug')}» ≠ file name")
            if slug in legacy_slugs:
                raise ValueError("this slug is already an article of blog-posts.json")
            post = d["post"]
            for k in ("title", "description", "h1", "crumb", "eyebrow", "lead", "topic", "card_line", "cover",
                      "intro", "sections", "faq_title", "faq", "cta"):
                if k not in post:
                    raise ValueError(f"post.{k} is missing")
            post.setdefault("hero", None)
            post.setdefault("date", "")
        except (ValueError, KeyError, TypeError) as e:
            if slug in pub:
                raise ValueError(f"content/blog/posts/{path.name} (published): {e}") from e
            print(f"  ! blog: content/blog/posts/{path.name}: {e} — skipped (not published)", file=sys.stderr)
            continue
        metas[slug] = dict(slug=slug, url=f"/blog/{slug}/", breed=d.get("breed"), keywords=d.get("keywords") or [])
        posts[slug] = post
    missing = [s for s in pub if s not in metas and s not in legacy_slugs]
    if missing:
        raise ValueError(f"content/blog/published.json: no article for {', '.join(missing)}")
    return metas, posts, pub


def routes(data):
    cfg = data["blog_posts"]
    hub, posts = cfg["hub"], dict(cfg["posts"])
    # «Тема» filter: post topic label → tag key (a topic missing from hub.tags is a data error)
    tag_of = {t["label"]: t["key"] for t in hub["tags"]}
    metas = by_id(data["blog"], "slug")
    f_metas, f_posts, published = _factory(set(hub["order"]))
    metas.update(f_metas)
    posts.update(f_posts)
    bmap = by_id(data["breeds"], "slug")
    tones = _tones()
    # JSON-LD needs absolute production URLs (the build does not rewrite <script> bodies)
    # the brand domain домщенков.рф in its ASCII (punycode) form — xn--b1adduihee9g.xn--p1ai
    site_url = "https://" + data["site"].get("domain_ascii", data["site"]["domain"].encode("idna").decode())

    every = list(hub["order"]) + sorted(f_posts)  # every article that has a page (published or not)
    cards = {}
    for slug in every:
        meta, post = metas[slug], posts[slug]
        breed = bmap.get(meta["breed"]) if meta.get("breed") else None
        if post["topic"] not in tag_of:
            raise ValueError(f"blog: {slug}: topic «{post['topic']}» is not in blog-posts.json hub.tags")
        cards[slug] = _card(meta, post, breed, tones, tag_of[post["topic"]])

    # /blog/: published articles newest first (same day: the order of `every`), then the first eleven not out yet
    out_now = sorted((s for s in every if s in published), key=lambda s: (published[s]["date"], -every.index(s)),
                     reverse=True)
    listed = out_now + [s for s in hub["order"] if s not in published]

    # filter chips: only tags and breeds that have articles (hub.tags / breeds.json order)
    shown = [cards[s] for s in listed]
    tags = [t for t in hub["tags"] if any(c["tag"] == t["key"] for c in shown)]
    breed_chips = [dict(key=b["slug"], label=b["name"], tone_class=b["tone_class"])
                   for b in data["breeds"] if any(c["breed"] == b["slug"] for c in shown)]

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
            articles=shown,
            tags=tags,
            breed_chips=breed_chips,
            hero_chips=[
                dict(icon="paw", label=f"{len(data['breeds'])}{NBSP}{plural(len(data['breeds']), 'порода', 'породы', 'пород')}"),
                dict(icon="clock", label="до " + minutes_label(max(read_minutes(posts[s]) for s in listed)) + " чтения"),
            ],
        ),
    )]

    for slug in every:
        meta, post = metas[slug], posts[slug]
        pub = published.get(slug)
        try:
            out.append(_post_route(slug, meta, post, pub, bmap, site_url, data["site"]["brand"]))
        except (KeyError, TypeError, ValueError) as e:
            if pub or slug in hub["order"]:
                raise
            print(f"  ! blog: content/blog/posts/{slug}.json: {type(e).__name__}: {e} — skipped (not published)",
                  file=sys.stderr)
    return out


def _post_route(slug, meta, post, pub, bmap, site_url, brand):
    """The route of one article. pub: its content/blog/published.json entry or None (not out yet)."""
    links = not pub or pub.get("links", 3) != 0  # links=0: the first month — no links in the text
    breed = bmap.get(meta["breed"]) if meta.get("breed") else None
    hero = post["hero"] or (breed["studio"] if breed else None)
    sections = [dict(id=s["id"], toc=s["toc"], h2=nobr(s["h2"]),
                     blocks=[_render_block(b, links) for b in s["blocks"]]) for s in post["sections"]]
    cta = post["cta"]
    route = dict(
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
                date=_date_label(pub["date"]) if pub else (post.get("date") or "Скоро"),
                read=minutes_label(read_minutes(post)),
                intro=rich(post["intro"], links),
                toc=[[s["id"], s["toc"]] for s in post["sections"]],
                sections=sections,
                faq_title=post["faq_title"],
                # the question sits in a flex button next to the «+» icon: one wrapping span = one flex item
                faq=[dict(q=Markup("<span>") + nobr(q["q"]) + Markup("</span>"), a=rich(q["a"], links))
                     for q in post["faq"]],
                cta=dict(title=nobr(cta["title"]), line=nobr(cta["line"]),
                         button=cta.get("button") or (dict(url=breed["urls"]["hub"], label="Всё о породе")
                                                      if breed else dict(url="/shchenki/", label="Смотреть щенков")),
                         second=cta.get("second") or (dict(url=breed["urls"]["hub"] + "#shchenki",
                                                           label="Щенки в наличии") if breed else None)),
            ),
            hero_photo=dict(src=hero["src"], alt=hero["alt"]) if hero else None,  # size: imgsize() in the template
            # a landscape hero (four breeds in a row) takes the wide-photo hero of /o-pitomnike/
            hero_wide=bool(post["hero"]) and not breed,
            tone=breed["tone"] if breed else "cream",
            breed=breed,
            ld=_ld(meta, post, site_url, meta["url"], brand, pub["date"] if pub else None),
            pups_breed=breed,
            lead_breed=breed["slug"] if breed else None,
        ),
    )
    if pub:
        route["live"] = True  # out from its publication day: the build publishes it without publish.json
    return route
