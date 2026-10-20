"""SEO layer of the build (used by tools/build.py). Python 3 stdlib only.

Every page gets, in place of the <!--seo--> marker in base.html.j2:
  canonical (production domain, punycode), robots, Open Graph + Twitter card, favicons and the web manifest,
  search-engine verification tags (site.json → seo, empty = not written), a noindex guard for the GitHub Pages
  preview, and JSON-LD: BreadcrumbList on every inner page, WebSite + PetStore on the homepage and /kontakty/.
Pages keep their own JSON-LD (FAQPage, BlogPosting) — this module only adds.

The build also writes sitemap.xml (indexable pages, lastmod = the day the page last changed), robots.txt and
site.webmanifest at the repo root. See docs/seo.md.
"""
from __future__ import annotations

import datetime
import hashlib
import html as htmllib
import json
import re

MARKER = "<!--seo-->"

_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
_DESC_RE = re.compile(r'<meta name="description" content="([^"]*)"')
_MAIN_IMG_RE = re.compile(r'<img\b[^>]*\ssrc="(/assets/img/[^"?#]+\.(?:jpe?g|png|webp))"[^>]*>', re.I)
_ALT_RE = re.compile(r'\salt="([^"]*)"')
_LD_TYPE_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_VERSION_RE = re.compile(r"\?v=[0-9a-f]+")


def cfg(site: dict) -> dict:
    """site.json → seo, with defaults. base_url is the production origin (punycode, no trailing slash)."""
    s = dict(site.get("seo") or {})
    host = site.get("domain_ascii") or site.get("domain", "").encode("idna").decode()
    s.setdefault("base_url", "https://" + host)
    s.setdefault("site_name", "Дом щенков — домщенков.рф")
    s.setdefault("org_name", "Дом щенков")
    s.setdefault("og_image", "/assets/img/og/og-default.jpg")
    s.setdefault("noindex", [])
    s.setdefault("opening_hours", "")
    for k in ("yandex_verification", "google_verification", "yandex_metrika", "google_tag_manager"):
        s.setdefault(k, "")
    s["base_url"] = s["base_url"].rstrip("/")
    return s


def _attr(v: str) -> str:
    return htmllib.escape(v, quote=True)


def _text(raw: str) -> str:
    """Plain text of a title/description as written in HTML (entities and NBSP decoded)."""
    return re.sub(r"\s+", " ", htmllib.unescape(raw).replace(" ", " ").replace("⁠", "")).strip()


def _ld(obj) -> str:
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return '<script type="application/ld+json">' + s.replace("</", "<\\/") + "</script>"


def is_placeholder(v) -> bool:
    return not v or "[" in str(v)


def robots_for(url: str, ctx: dict, conf: dict) -> str:
    if ctx.get("robots"):
        return ctx["robots"]
    if url in conf["noindex"] or url.startswith("/_"):
        return "noindex, follow"
    return "index, follow, max-image-preview:large"


def indexable(robots: str) -> bool:
    return "noindex" not in robots


def organization(site: dict, conf: dict, imgsize) -> dict:
    base = conf["base_url"]
    org = {
        "@type": "PetStore",
        "@id": base + "/#org",
        "name": conf["org_name"],
        "alternateName": site.get("brand", "домщенков.рф"),
        "url": base + "/",
        "logo": base + "/assets/icons/icon-512.png",
        "image": base + conf["og_image"],
        "description": "Питомник собак в Москве: щенки мальтипу, французского бульдога, той-пуделя и бордер-колли.",
        "areaServed": {"@type": "Country", "name": "Россия"},
        "address": {"@type": "PostalAddress", "addressLocality": site.get("address", {}).get("city", "Москва"),
                    "addressRegion": "Москва", "addressCountry": "RU"},
    }
    street = site.get("address", {}).get("street")
    if not is_placeholder(street):
        org["address"]["streetAddress"] = street
    if not is_placeholder(site.get("email")):
        # the ASCII form (xn--…) of the address, as in the mailto: links: machine-read data
        org["email"] = (site.get("email_href") or "").removeprefix("mailto:") or site["email"]
    # contacts_ready = false: the number and messengers are not known yet — no telephone / sameAs
    ready = site.get("contacts_ready", True)
    tel = (site.get("phone") or {}).get("tel", "") if ready else ""
    if tel.startswith("tel:"):
        org["telephone"] = tel[4:]
    if conf.get("opening_hours"):
        org["openingHours"] = conf["opening_hours"]
    same = [m.get("url") for m in (site.get("messengers") or {}).values() if isinstance(m, dict)] if ready else []
    same = [u for u in same if u and u.startswith("http") and not is_placeholder(u)]
    if same:
        org["sameAs"] = same
    return org


def breadcrumbs_ld(crumbs, url: str, conf: dict) -> dict | None:
    if not crumbs or len(crumbs) < 2:
        return None
    base = conf["base_url"]
    items = []
    for i, (label, href) in enumerate(crumbs, 1):
        href = href or url
        items.append({"@type": "ListItem", "position": i, "name": _text(str(label)), "item": base + href})
    return {"@type": "BreadcrumbList", "itemListElement": items}


def og_image(html: str, ctx: dict, conf: dict, imgsize):
    """The page's own picture for link previews: ctx['og_image'] or the first content photo in <main>."""
    src = ctx.get("og_image")
    alt = ""
    if not src:
        main = html[html.find("<main"):]
        m = _MAIN_IMG_RE.search(main)
        if m:
            src = m.group(1)
            a = _ALT_RE.search(m.group(0))
            alt = _text(a.group(1)) if a else ""
    if not src or not imgsize(src):
        src, alt = conf["og_image"], ""
    size = imgsize(src) or (1200, 630)
    return src, size, alt


def head_block(html: str, url: str, ctx: dict, site: dict, conf: dict, imgsize) -> str:
    base = conf["base_url"]
    canonical = base + url
    title_m, desc_m = _TITLE_RE.search(html), _DESC_RE.search(html)
    title = _text(title_m.group(1)) if title_m else ""
    desc = _text(desc_m.group(1)) if desc_m else ""
    og_title = ctx.get("og_title") or title.split(" | ")[0]
    robots = robots_for(url, ctx, conf)
    img, (w, h), alt = og_image(html, ctx, conf, imgsize)
    og_type = ctx.get("og_type") or ("article" if url.startswith("/blog/") and url != "/blog/" else "website")

    out = []
    if indexable(robots):
        out.append(f'<link rel="canonical" href="{_attr(canonical)}">')
    out.append(f'<meta name="robots" content="{robots}">')
    # превью на GitHub Pages — копия сайта: поисковикам её не показываем (боевой домен — в canonical)
    out.append("<script>/\\.github\\.io$/.test(location.hostname)&&document.write('<meta name=\"robots\" content=\"noindex, nofollow\">')</script>")
    out += [
        f'<meta property="og:type" content="{og_type}">',
        f'<meta property="og:site_name" content="{_attr(conf["site_name"])}">',
        '<meta property="og:locale" content="ru_RU">',
        f'<meta property="og:title" content="{_attr(og_title)}">',
        f'<meta property="og:description" content="{_attr(desc)}">',
        f'<meta property="og:image" content="{_attr(base + img)}">',
        f'<meta property="og:image:width" content="{w}">',
        f'<meta property="og:image:height" content="{h}">',
    ]
    if alt:
        out.append(f'<meta property="og:image:alt" content="{_attr(alt)}">')
    if indexable(robots):
        out.append(f'<meta property="og:url" content="{_attr(canonical)}">')
    out += [
        '<meta name="twitter:card" content="summary_large_image">',
        '<link rel="icon" href="/favicon.ico" sizes="32x32">',
        '<link rel="icon" href="/assets/icons/favicon.svg" type="image/svg+xml">',
        '<link rel="apple-touch-icon" href="/assets/icons/apple-touch-icon.png">',
        '<link rel="manifest" href="/site.webmanifest">',
    ]
    if conf["yandex_verification"]:
        out.append(f'<meta name="yandex-verification" content="{_attr(conf["yandex_verification"])}">')
    if conf["google_verification"]:
        out.append(f'<meta name="google-site-verification" content="{_attr(conf["google_verification"])}">')

    graph = []
    bc = breadcrumbs_ld(ctx.get("breadcrumbs"), url, conf) if indexable(robots) else None
    if bc:
        graph.append(bc)
    if url in ("/", "/kontakty/"):
        if url == "/":
            graph.append({"@type": "WebSite", "@id": base + "/#website", "url": base + "/", "name": conf["org_name"],
                          "alternateName": site.get("brand", "домщенков.рф"), "inLanguage": "ru",
                          "publisher": {"@id": base + "/#org"}})
        graph.append(organization(site, conf, imgsize))
    if graph:
        out.append(_ld({"@context": "https://schema.org", "@graph": graph}))
    return "\n  ".join(out)


# Counters run only on the production host: the GitHub Pages preview and local builds stay out of the statistics.
_PROD_JS = 'location.hostname==="{host}"'


def _host(conf: dict) -> str:
    return conf["base_url"].split("://", 1)[-1]


def metrika(conf: dict) -> tuple[str, str]:
    """Yandex Metrika counter (site.json → seo.yandex_metrika) with the settings from the Metrika panel: Webvisor,
    click map, e-commerce from dataLayer. → (script for <head>, <noscript> for <body>); empty when not set."""
    cid = str(conf.get("yandex_metrika") or "").strip()
    if not cid.isdigit():
        return "", ""
    src = f"https://mc.yandex.ru/metrika/tag.js?id={cid}"
    head = (
        f'<script>if({_PROD_JS.format(host=_host(conf))}){{(function(m,e,t,r,i,k,a){{m[i]=m[i]||function(){{(m[i].a=m[i].a||[]).push(arguments)}};'
        'm[i].l=1*new Date();for(var j=0;j<document.scripts.length;j++){if(document.scripts[j].src===r){return;}}'
        'k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)})'
        f'(window,document,"script","{src}","ym");'
        f'ym({cid},"init",{{ssr:true,webvisor:true,clickmap:true,ecommerce:"dataLayer",referrer:document.referrer,'
        'url:location.href,accurateTrackBounce:true,trackLinks:true});}</script>'
    )
    body = (f'<noscript><div><img src="https://mc.yandex.ru/watch/{cid}" width="1" height="1" '
            'style="position:absolute;left:-9999px" alt=""></div></noscript>')
    return head, body


def gtm(conf: dict) -> tuple[str, str]:
    """Google Tag Manager container (site.json → seo.google_tag_manager, «GTM-…»): Google Analytics and other tags are
    set up in the GTM panel. → (script for <head>, <noscript> for <body>); empty when not set."""
    gid = str(conf.get("google_tag_manager") or "").strip()
    if not re.fullmatch(r"GTM-[A-Z0-9]+", gid):
        return "", ""
    head = (
        f'<script>if({_PROD_JS.format(host=_host(conf))}){{(function(w,d,s,l,i){{w[l]=w[l]||[];w[l].push({{"gtm.start":'
        'new Date().getTime(),event:"gtm.js"});var f=d.getElementsByTagName(s)[0],j=d.createElement(s),'
        'dl=l!="dataLayer"?"&l="+l:"";j.async=true;j.src="https://www.googletagmanager.com/gtm.js?id="+i+dl;'
        f'f.parentNode.insertBefore(j,f);}})(window,document,"script","dataLayer","{gid}");}}</script>'
    )
    body = (f'<noscript><iframe src="https://www.googletagmanager.com/ns.html?id={gid}" height="0" width="0" '
            'style="display:none;visibility:hidden"></iframe></noscript>')
    return head, body


_CHARSET_RE = re.compile(r'<meta charset="[^"]*">')
_BODY_RE = re.compile(r"<body\b[^>]*>")


def finalize(html: str, url: str, ctx: dict, site: dict, conf: dict, imgsize) -> str:
    if MARKER in html:
        html = html.replace(MARKER, head_block(html, url, ctx, site, conf, imgsize), 1)
    counters = [gtm(conf), metrika(conf)]
    head = "".join(h for h, _ in counters if h)
    body = "".join(b for _, b in counters if b)
    if head:   # as early in <head> as possible (GTM asks for it), right after the charset
        m = _CHARSET_RE.search(html)
        if m:
            html = html[:m.end()] + "\n  " + head + html[m.end():]
    if body:   # right after the opening <body>
        m = _BODY_RE.search(html)
        if m:
            html = html[:m.end()] + "\n" + body + html[m.end():]
    return html


# ---------------------------------------------------------------- site files
def page_fingerprint(html: str) -> str:
    """Content hash that ignores ?v= asset versions: a CSS change alone does not bump lastmod."""
    return hashlib.sha1(_VERSION_RE.sub("", html).encode("utf-8")).hexdigest()[:12]


def priority(url: str) -> tuple[str, str]:
    """(priority, changefreq) by page type."""
    parts = url.strip("/").split("/") if url != "/" else []
    if url == "/":
        return "1.0", "daily"
    if url == "/shchenki/":
        return "0.9", "daily"
    if len(parts) == 1 and parts[0] in ("maltipu", "francuzskij-buldog", "toj-pudel", "border-kolli"):
        return "0.9", "daily"
    if parts and parts[0] == "shchenki":
        return "0.7", "daily"
    if len(parts) == 2 and parts[0] in ("maltipu", "francuzskij-buldog", "toj-pudel", "border-kolli"):
        return "0.8", "weekly"
    if parts and parts[0] in ("dostavka", "blog", "sravnenie"):
        return ("0.7" if len(parts) == 1 else "0.6"), "monthly"
    return "0.6", "monthly"


def sitemap_xml(entries: list[tuple[str, str]], conf: dict) -> str:
    """entries: [(url, lastmod YYYY-MM-DD)] — indexable pages only."""
    base = conf["base_url"]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url, lastmod in sorted(entries, key=lambda e: (e[0] != "/", e[0])):
        pr, freq = priority(url)
        lines.append(f"  <url><loc>{base}{url}</loc><lastmod>{lastmod}</lastmod>"
                     f"<changefreq>{freq}</changefreq><priority>{pr}</priority></url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def robots_txt(conf: dict) -> str:
    base = conf["base_url"]
    # /admin/ — the request panel, /api/ — the forms' API (both on the server only, backend/)
    hidden = sorted({u for u in conf["noindex"] if u.startswith("/_")} | {"/_kit/", "/admin/", "/api/"})
    dis = "".join(f"Disallow: {u}\n" for u in hidden)
    utm = "utm_source&utm_medium&utm_campaign&utm_content&utm_term&yclid&ysclid&gclid&fbclid&from&openstat"
    return (
        "# домщенков.рф — правила для поисковых роботов (собирается tools/build.py)\n"
        "User-agent: *\n" + dis + "Allow: /\n\n"
        "# Яндекс: фильтры каталога и блога и метки рекламы не создают новых страниц\n"
        "User-agent: Yandex\n" + dis + "Allow: /\n"
        "Clean-param: breed&sex&status\n"
        "Clean-param: tema /blog/\n"
        f"Clean-param: {utm}\n\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )


def webmanifest(site: dict, conf: dict) -> str:
    m = {
        "name": conf["site_name"],
        "short_name": conf["org_name"],
        "lang": "ru",
        "start_url": "./",
        "display": "browser",
        "background_color": site.get("theme_color", "#F3F2EF"),
        "theme_color": site.get("theme_color", "#F3F2EF"),
        "icons": [
            {"src": "assets/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "assets/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "assets/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return json.dumps(m, ensure_ascii=False, indent=2) + "\n"


def today() -> str:
    return datetime.date.today().isoformat()
