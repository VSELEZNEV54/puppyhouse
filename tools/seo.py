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
    s.setdefault("site_name", "Дом щенков — дом-щенков.рф")
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
        "alternateName": site.get("brand", "дом-щенков.рф"),
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
                          "alternateName": site.get("brand", "дом-щенков.рф"), "inLanguage": "ru",
                          "publisher": {"@id": base + "/#org"}})
        graph.append(organization(site, conf, imgsize))
    if graph:
        out.append(_ld({"@context": "https://schema.org", "@graph": graph}))
    return "\n  ".join(out)


# Counters run only on the production host: the GitHub Pages preview and local builds stay out of the statistics.
# Opt-out (client 22.10): they run from the first visit until the visitor picks «Принять только необходимые» or
# «Отказаться» in the cookie banner (partials/cookie.html.j2, main.js). window.dshStats() loads them; the <head> script
# queues it unless localStorage 'dsh:cookie' holds such a refusal (refusals do not expire). Network scripts wait
# for the first screen and an idle slot; refusal is checked again immediately before inserting them.
_PROD_JS = 'location.hostname==="{host}"'
COOKIE_KEY = "dsh:cookie"                   # main.js: the same key and the same term


def _host(conf: dict) -> str:
    return conf["base_url"].split("://", 1)[-1]


def metrika(conf: dict) -> str:
    """Yandex Metrika network script; counters() queues its Webvisor, click map and e-commerce settings first.
    Empty when not set. No <noscript> pixel: it could not respect the visitor's refusal."""
    cid = str(conf.get("yandex_metrika") or "").strip()
    if not cid.isdigit():
        return ""
    src = f"https://mc.yandex.ru/metrika/tag.js?id={cid}"
    return (
        '(function(d,s){var j=d.createElement("script");j.async=true;j.src=s;d.head.appendChild(j)})'
        f'(document,"{src}");'
    )


def gtm(conf: dict) -> str:
    """Google Tag Manager container (site.json → seo.google_tag_manager, «GTM-…»): Google Analytics and other tags are
    set up in the GTM panel. → JS for counters(); empty when not set. No <noscript> iframe (see metrika())."""
    gid = str(conf.get("google_tag_manager") or "").strip()
    if not re.fullmatch(r"GTM-[A-Z0-9]+", gid):
        return ""
    return (
        '(function(w,d,s,l,i){var f=d.getElementsByTagName(s)[0],j=d.createElement(s),'
        'dl=l!="dataLayer"?"&l="+l:"";j.async=true;j.src="https://www.googletagmanager.com/gtm.js?id="+i+dl;'
        f'f.parentNode.insertBefore(j,f);}})(window,document,"script","dataLayer","{gid}");'
    )


def counters(conf: dict) -> str:
    """Keep early goals in queues; load counters after the first screen, only while statistics remain enabled.

    Existing opt-out behaviour is preserved. A refusal while waiting (including a failed storage write) cancels
    startup. No network request, pixel or iframe is made by the queues themselves.
    """
    js = gtm(conf) + metrika(conf)
    if not js:
        return ""
    queue = ''
    if gtm(conf):
        queue += 'window.dataLayer=window.dataLayer||[];window.dataLayer.push({"gtm.start":Date.now(),event:"gtm.js"});'
    cid = str(conf.get("yandex_metrika") or "").strip()
    if cid.isdigit():
        queue += (
            'window.ym=window.ym||function(){(window.ym.a=window.ym.a||[]).push(arguments)};window.ym.l=Date.now();'
            f'window.dshYm={cid};ym({cid},"init",{{ssr:true,webvisor:true,clickmap:true,ecommerce:"dataLayer",'
            'referrer:document.referrer,url:location.href,accurateTrackBounce:true,trackLinks:true});'
        )
    return (
        '<script data-dsh-counters>(function(){'
        'function allowed(){if(window.dshStats.disabled)return false;'
        f'if(!({_PROD_JS.format(host=_host(conf))}))return false;'
        f'var c=null;try{{c=localStorage.getItem("{COOKIE_KEY}")}}catch(e){{return false}}'
        'try{c=JSON.parse(c)}catch(e){c=null}'
        'return !(c&&(c.choice==="necessary"||c.choice==="declined"))}'
        'window.dshStats=function(){var s=window.dshStats;if(s.on||s.pending||!allowed())return;'
        f'if(!s.prepared){{s.prepared=true;{queue}}}'
        's.pending=true;function start(){s.pending=false;if(s.on||!allowed())return;'
        f's.on=true;{js}}}'
        'function idle(){requestAnimationFrame(function(){requestAnimationFrame(function(){'
        'if(window.requestIdleCallback)requestIdleCallback(start,{timeout:1500});else setTimeout(start,0)})})}'
        'function ready(){Promise.resolve(window.__siteReady).then(idle,idle)}'
        'if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",ready,{once:true});else ready()};'
        'window.dshStats.cancel=function(){var s=window.dshStats;s.disabled=true;'
        'if(!s.on){s.pending=false;s.prepared=false;if(window.ym&&window.ym.a)window.ym.a.length=0;'
        'if(Array.isArray(window.dataLayer))window.dataLayer.length=0}};'
        'window.dshStats()})()</script>'
    )


_CHARSET_RE = re.compile(r'<meta charset="[^"]*">')


def finalize(html: str, url: str, ctx: dict, site: dict, conf: dict, imgsize) -> str:
    if MARKER in html:
        html = html.replace(MARKER, head_block(html, url, ctx, site, conf, imgsize), 1)
    head = counters(conf)
    if head:   # early queues preserve goals; external scripts wait for the first screen
        m = _CHARSET_RE.search(html)
        if m:
            html = html[:m.end()] + "\n  " + head + html[m.end():]
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
        "# дом-щенков.рф — правила для поисковых роботов (собирается tools/build.py)\n"
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
