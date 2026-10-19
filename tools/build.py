#!/usr/bin/env python3
"""домщенков.рф — static site generator.

    python3 tools/build.py            build every route into <url>/index.html
    python3 tools/build.py --clean    also delete pages from earlier builds that no route produces now
    python3 tools/build.py --kit      also write the developer UI kit to /_kit/ (git-ignored)
    python3 tools/build.py --all      build EVERY route into _all/ (git-ignored) for local review; the published
                                      tree is not touched (serve it: python3 -m http.server 8765 --directory _all)

Published pages: src/data/publish.json → pages. A normal build renders only them and deletes the other generated
pages, so the repo (GitHub Pages) and the server get just the published site. Links to the rest go to a block on a
published page (publish.json → link_fallbacks) or stay root-absolute: toast «Раздел скоро откроется…», rel=nofollow.
A broken publish.json stops the build before anything is written. Full site of 19.10: branch backup/full-site-2026-10-19.

Also writes 404.html, sitemap.xml, robots.txt and site.webmanifest at the repo root (tools/seo.py, docs/seo.md).

Sources: src/data/*.json (data), src/routes/*.py (URLs), src/templates/ (Jinja2).
See src/CONVENTIONS.md. Python 3 stdlib + Jinja2 only.
"""
from __future__ import annotations

import argparse
import collections
import copy
import datetime as dt
import hashlib
import html as htmllib
import importlib.util
import json
import os
import posixpath
import re
import struct
import sys
import tempfile
import traceback
from pathlib import Path

import jinja2
from markupsafe import Markup, escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seo  # noqa: E402  (tools/seo.py: canonical, Open Graph, JSON-LD, sitemap, robots.txt)

sys.dont_write_bytecode = True  # no __pycache__ next to route modules

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
TEMPLATES = SRC / "templates"
DATA_DIR = SRC / "data"
ROUTES_DIR = SRC / "routes"
MANIFEST = ROOT / ".build-manifest.json"
PHOTO_TONES = ROOT / "tools" / "photo-tones.json"  # measured backdrop colours of studio photos

# Top-level folders a route may never write into.
PROTECTED = {"assets", "src", "tools", "docs", "content", ".github", ".git", "node_modules"}
URL_RE = re.compile(r"^/(?:[a-z0-9]+(?:-[a-z0-9]+)*/)*$")
KIT_URL = "/_kit/"

# Attributes whose root-absolute values are rewritten to page-relative ones.
URL_ATTRS = ("href", "src", "poster", "action", "data-src", "data-href")


# ---------------------------------------------------------------- typography
_SHORT_WORD = re.compile(r"(?<![\w&;\-])(?!(?:ли|же|бы|кг|см|мм|км|мл)\b)([а-яёa-z]{1,2}) (?=\S|$)", re.IGNORECASE)
_PARTICLE = re.compile(r" (?=(?:ли|же|бы)\b)", re.IGNORECASE)
_DASH = re.compile(r" (?=[—–](?:\s|$))")
# 15 минут, 2,5 кг; not times («9:00 до»), not «2026 Puppy», not before a preposition
_NUM_UNIT = re.compile(r"(?<![\d:])(\d+(?:[.,]\d+)?) (?=[а-яё%])(?!(?:и|или|а|но|до|в|во|на|с|со|по|за|из|от|к|у|о)\b)")
_TAG = re.compile(r"(<[^>]+>)")
# «что-то», «как-нибудь», «кое-где»: no line break after the hyphen (U+2060 word joiner — invisible, font-independent)
_HYPHEN_WORD = re.compile(r"(?<=[а-яё])-(?=(?:то|нибудь|либо|ка|таки)\b)|(?<=\bкое)-(?=[а-яё])", re.IGNORECASE)
WJ = "\u2060"
NBSP = " "


def _typo_text(s: str) -> str:
    s = _DASH.sub(NBSP, s)
    s = _SHORT_WORD.sub(lambda m: m.group(1) + NBSP, s)
    s = _PARTICLE.sub(NBSP, s)
    s = _NUM_UNIT.sub(lambda m: m.group(1) + NBSP, s)
    s = _HYPHEN_WORD.sub("-" + WJ, s)
    return s


def typo(value) -> Markup:
    """Non-breaking spaces after 1–2 letter words, before dashes and between a number and its unit.
    Plain strings are escaped first; Markup is processed outside tags only."""
    if value is None:
        return Markup("")
    if isinstance(value, Markup) or hasattr(value, "__html__"):
        parts = _TAG.split(str(value.__html__()))
        return Markup("".join(p if p.startswith("<") else _typo_text(p) for p in parts))
    return Markup(_typo_text(str(escape(str(value)))))


def plural(n, one: str, few: str, many: str) -> str:
    """Russian plural form for n: plural(3, 'щенок', 'щенка', 'щенков') -> 'щенка'."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]


def ru_date(value, year: bool = True) -> str:
    d = value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))
    return f"{d.day}{NBSP}{MONTHS_GEN[d.month - 1]}" + (f" {d.year}" if year else "")


def weeks(n) -> str:
    return f"{n}{NBSP}{plural(n, 'неделя', 'недели', 'недель')}"


# ---------------------------------------------------------------- images
_size_cache: dict[str, tuple[int, int] | None] = {}


def imgsize(src: str):
    """(width, height) of an image under the repo, by its root-absolute src ('/assets/img/x.jpg')."""
    if src in _size_cache:
        return _size_cache[src]
    path = ROOT / src.split("?")[0].lstrip("/")
    size = None
    try:
        with open(path, "rb") as f:
            head = f.read(26)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                size = struct.unpack(">II", head[16:24])
            elif head[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    marker = f.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        break
                    if marker[1] in (0xD8, 0x01) or 0xD0 <= marker[1] <= 0xD7:
                        continue
                    seg_len = struct.unpack(">H", f.read(2))[0]
                    if marker[1] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        h, w = struct.unpack(">xHH", f.read(5))
                        size = (w, h)
                        break
                    f.seek(seg_len - 2, 1)
    except OSError:
        size = None
    _size_cache[src] = size
    return size


# ---------------------------------------------------------------- studio photo tones
_tones: dict = {}


def load_tones(rep) -> None:
    try:
        _tones.update(json.loads(PHOTO_TONES.read_text(encoding="utf-8")))
    except FileNotFoundError:
        pass
    except ValueError as e:
        rep.warn(f"{PHOTO_TONES.relative_to(ROOT)}: {e}")


def photo_tone(src: str):
    """Measured backdrop of a studio photo by its src: {top, wall, wall_right, floor, floor_line} or None."""
    return _tones.get(Path(str(src).split("?")[0]).stem)


def tone_style(src: str) -> str:
    """Inline CSS custom properties that make a tile match one specific studio photo:
    --tone-top (top strip), --tone-hi (left wall), --tone-floor, --fa / --fb (floor line, 0–1 of photo height).
    Empty string when the photo was not measured (the tile keeps its tone--* class colours)."""
    t = photo_tone(src)
    if not t:
        return ""
    fl = float(t.get("floor_line", 0.82))
    return (f"--tone-top:{t['top']};--tone-hi:{t['wall']};--tone-floor:{t['floor']};"
            f"--fa:{max(fl - 0.04, 0):.2f};--fb:{min(fl + 0.12, 1):.2f}")


# ---------------------------------------------------------------- data
class Report:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)


def load_data(rep: Report) -> dict:
    data = {}
    for path in sorted(DATA_DIR.glob("*.json")):
        key = path.stem.replace("-", "_")
        try:
            data[key] = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 — report and keep going
            rep.error(f"data: {path.relative_to(ROOT)}: {e}")
    return data


STATUS = {
    "available": ("В наличии", "В наличии", "ok"),
    "reserved": ("Забронирован", "Забронирована", "res"),
    "soon": ("Скоро в продаже", "Скоро в продаже", "soon"),
}
STATUS_ORDER = {"available": 0, "soon": 1, "reserved": 2}


def enrich(data: dict, rep: Report) -> None:
    """Computed fields shared by every route and template (documented in CONVENTIONS.md)."""
    site = data.get("site", {})
    as_of = dt.date.fromisoformat(site.get("as_of", dt.date.today().isoformat()))
    breeds = data.get("breeds", [])
    bmap = {b["slug"]: b for b in breeds}
    data["breed_map"] = bmap
    for b in breeds:
        b["tone_class"] = "tone--" + b["tone"]
        b["puppies"] = []
    for p in data.get("puppies", []):
        try:
            b = bmap[p["breed"]]
            born = dt.date.fromisoformat(p["birth_date"])
            age = (as_of - born).days // 7
            if p.get("age_weeks") not in (None, age):
                rep.warn(f"puppies.json: {p['slug']}: age_weeks {p['age_weeks']} ≠ {age} computed from birth_date on {as_of}")
            p["age_weeks"] = age
            p["url"] = f"/shchenki/{p['slug']}/"
            p["breed_name"] = b["name"]
            p["tone"] = b["tone"]
            p["tone_class"] = b["tone_class"]
            p["sex_label"] = "мальчик" if p["sex"] == "male" else "девочка"
            male, female, dot = STATUS[p["status"]]
            p["status_label"] = male if p["sex"] == "male" else female
            p["status_dot"] = dot
            p["status_order"] = STATUS_ORDER[p["status"]]
            age_txt = weeks(age)
            gen = (" " + p["generation"]) if p.get("generation") else ""
            p["meta"] = f"{b['name']} · {age_txt} · {p['sex_label']}"
            p["desc"] = f"{b['name']}{gen} · {age_txt} · {p['sex_label']}"
            p["photo"] = p["photos"][0]
            b["puppies"].append(p)
        except Exception as e:  # noqa: BLE001
            rep.error(f"puppies.json: {p.get('slug', '?')}: {e!r}")
    for b in breeds:  # one source for every puppy count on the site: puppies.json
        n = len(b["puppies"])
        if "stock" in b and b["stock"] != n:
            rep.warn(f"breeds.json: {b['slug']}: stock {b['stock']} ≠ {n} puppies in puppies.json — the count is computed, remove stock")
        b["stock"] = n


# ---------------------------------------------------------------- routes
def discover_routes(data: dict, rep: Report):
    """[(module, route)] from every src/routes/*.py, and the set of modules that failed."""
    sys.path.insert(0, str(ROUTES_DIR))
    routes, failed = [], set()
    for path in sorted(ROUTES_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        name = path.stem
        try:
            spec = importlib.util.spec_from_file_location(f"routes_{name}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            items = mod.routes(copy.deepcopy(data))  # a module cannot change what the others see
            if not isinstance(items, list):
                raise TypeError("routes(data) must return a list of dicts")
        except Exception:  # noqa: BLE001
            rep.error(f"routes/{path.name}: module failed, its pages are not rebuilt\n" + _indent(traceback.format_exc()))
            failed.add(name)
            continue
        for r in items:
            routes.append((name, r))
    return routes, failed


def _indent(text: str) -> str:
    return "\n".join("      " + line for line in text.rstrip().splitlines())


ALL_DIR = ROOT / "_all"  # --all output (every route), git-ignored


def out_path_for(url: str, base: Path = ROOT) -> Path:
    return base / url.strip("/") / "index.html" if url != "/" else base / "index.html"


# ---------------------------------------------------------------- post-processing
_ATTR_RE = re.compile(r"(\s(?:%s)\s*=\s*)([\"'])(.*?)\2" % "|".join(re.escape(a) for a in URL_ATTRS), re.S)
_SRCSET_RE = re.compile(r"(\ssrcset\s*=\s*)([\"'])(.*?)\2", re.S)
_CSSURL_RE = re.compile(r"url\(\s*([\"']?)(/[^\"')\s]*)\1\s*\)")
_SCRIPT_RE = re.compile(r"(<script\b[^>]*>)(.*?)(</script>)", re.S | re.I)
_hash_cache: dict[Path, str] = {}


def content_hash(path: Path) -> str:
    if path not in _hash_cache:
        _hash_cache[path] = hashlib.sha1(path.read_bytes()).hexdigest()[:8]
    return _hash_cache[path]


class Rewriter:
    def __init__(self, built: set[str], fallbacks: dict | None = None):
        self.built = built
        self.fallbacks = fallbacks or {}  # unpublished url → ["#id" on this page, "/#id" on the homepage, …]
        self.rerouted = collections.Counter()
        self.ids: set[str] = set()
        self.unbuilt = collections.Counter()
        self.unbuilt_pages = collections.defaultdict(set)
        self.missing = collections.defaultdict(set)

    def rel(self, target: str, page_url: str, is_dir: bool) -> str:
        r = posixpath.relpath(target.rstrip("/") or "/", page_url.rstrip("/") or "/")
        if is_dir:
            return "./" if r == "." else r + "/"
        return r

    def value(self, val: str, page_url: str, is_link: bool) -> str:
        if not val.startswith("/") or val.startswith("//"):
            return val
        m = re.match(r"([^?#]*)(\?[^#]*)?(#.*)?$", val)
        path, query, frag = m.group(1), m.group(2) or "", m.group(3) or ""
        if path.startswith("/assets/") or (path != "/" and not path.endswith("/") and (ROOT / path.lstrip("/")).is_file()):
            f = ROOT / path.lstrip("/")
            if not f.is_file():
                self.missing[path].add(page_url)
            elif f.suffix in (".css", ".js"):
                query = "?v=" + content_hash(f)
            return self.rel(path, page_url, False) + query + frag
        norm = path if path.endswith("/") else path + "/"
        if norm in self.built:
            return self.rel(norm, page_url, True) + query + frag
        if is_link and norm in self.fallbacks:
            for cand in self.fallbacks[norm]:
                if cand.startswith("#") and cand[1:] in self.ids:
                    self.rerouted[norm] += 1
                    return cand
                if cand.startswith("/#") and "/" in self.built:
                    self.rerouted[norm] += 1
                    return cand[1:] if page_url == "/" else self.rel("/", page_url, True) + cand[1:]
        if is_link:
            self.unbuilt[norm] += 1
            self.unbuilt_pages[norm].add(page_url)
        else:
            self.missing[path].add(page_url)
        return val

    def _tags(self, html: str, page_url: str) -> str:
        def attr(m):
            is_link = m.group(1).strip().startswith(("href", "data-href", "action"))
            return m.group(1) + m.group(2) + self.value(m.group(3), page_url, is_link) + m.group(2)

        def srcset(m):
            parts = []
            for item in m.group(3).split(","):
                bits = item.strip().split(None, 1)
                if bits:
                    bits[0] = self.value(bits[0], page_url, False)
                parts.append(" ".join(bits))
            return m.group(1) + m.group(2) + ", ".join(parts) + m.group(2)

        def cssurl(m):
            return "url(" + m.group(1) + self.value(m.group(2), page_url, False) + m.group(1) + ")"

        html = _ATTR_RE.sub(attr, html)
        html = _SRCSET_RE.sub(srcset, html)
        return _CSSURL_RE.sub(cssurl, html)

    def page(self, html: str, page_url: str) -> str:
        self.ids = set(re.findall(r'\sid="([^"]+)"', html))
        out, pos = [], 0
        for m in _SCRIPT_RE.finditer(html):  # never touch inline script bodies
            out.append(self._tags(html[pos:m.start()], page_url))
            out.append(self._tags(m.group(1), page_url) + m.group(2) + m.group(3))
            pos = m.end()
        out.append(self._tags(html[pos:], page_url))
        return "".join(out)


# ---------------------------------------------------------------- lint
_ID_RE = re.compile(r"\sid=\"([^\"]+)\"")
_REF_RE = re.compile(r"\s(aria-controls|aria-labelledby|aria-describedby|for)=\"([^\"]+)\"")
_IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
_PRICE_RE = re.compile(r"\d[\d  ]*(?:₽|руб\.?|рублей)", re.I)
_BANNED_RE = re.compile(r"лучш(?:ий|ая|ее|ие|его|их)|№\s?1\b", re.I)
_TEXT_RE = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.S | re.I)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
_DESC_RE = re.compile(r'<meta name="description" content="([^"]*)"')
TITLE_MAX, DESC_MAX = 60, 160
# Стиль клиента: без капса и без жирных начертаний (максимум 500).
_CAPS_WORD_RE = re.compile(r"\b[А-ЯЁA-Z]{4,}\b")
CAPS_OK = {"FCI", "ФКС", "ДНК", "ИНН", "ОГРН", "ОГРНИП", "КПП", "БИК", "ОКПО", "ОКВЭД", "MAX", "HTML", "SMS", "PDF", "WhatsApp"}
_CSS_CAPS_RE = re.compile(r"text-transform\s*:\s*uppercase|font-variant(?:-caps)?\s*:\s*(?:all-)?small-caps", re.I)
_CSS_WEIGHT_RE = re.compile(r"font-weight\s*:\s*(\d{3}|bold|bolder)", re.I)
# Бренд с 13.10 — «домщенков.рф» (строчными, без дефиса): старое имя и вариант с дефисом не должны попадать на страницы
_OLD_BRAND_RE = re.compile(r"puppy\s*house|дом-щенков\.рф", re.I)  # «Puppy House», «puppyhouse.ru», hyphenated form


def lint_css(rep: "Report") -> None:
    """Каждый stylesheet: без капса и весов больше 500 (замечание клиента 12.10)."""
    for css in sorted((ROOT / "assets" / "css").glob("*.css")):
        for n, line in enumerate(css.read_text(encoding="utf-8").splitlines(), 1):
            if _CSS_CAPS_RE.search(line):
                rep.warn(f"{css.relative_to(ROOT)}:{n}: uppercase text is not allowed (client style rule) — use normal case")
            for w in _CSS_WEIGHT_RE.findall(line):
                if w.lower() in ("bold", "bolder") or int(w) > 500:
                    rep.warn(f"{css.relative_to(ROOT)}:{n}: font-weight {w} — max 500 on this site (client style rule)")


def lint(html: str, url: str, rep: Report) -> None:
    where = f"{url}:"
    ids = _ID_RE.findall(html)
    dups = sorted({i for i in ids if ids.count(i) > 1})
    if dups:
        rep.warn(f"{where} duplicate id: {', '.join(dups)}")
    idset = set(ids)
    bad = sorted({f"{a}={r}" for a, v in _REF_RE.findall(html) for r in v.split() if r not in idset})
    if bad:
        rep.warn(f"{where} reference to a missing id: {', '.join(bad)}")
    h1 = len(re.findall(r"<h1\b", html))
    if h1 != 1:
        rep.warn(f"{where} {h1} <h1> (need exactly one)")
    for tag in _IMG_RE.findall(html):
        if " alt=" not in tag:
            rep.warn(f"{where} <img> without alt: {tag[:90]}")
        if " width=" not in tag or " height=" not in tag:
            rep.warn(f"{where} <img> without width/height: {tag[:90]}")
    m = _TITLE_RE.search(html)
    title = htmllib.unescape(m.group(1)).strip() if m else ""
    if not title:
        rep.warn(f"{where} empty <title>")
    elif len(title) > TITLE_MAX:
        rep.warn(f"{where} <title> is {len(title)} chars (≤ {TITLE_MAX}): «{title}»")
    m = _DESC_RE.search(html)
    desc = htmllib.unescape(m.group(1)).strip() if m else ""
    if not desc:
        rep.warn(f"{where} empty meta description")
    elif len(desc) > DESC_MAX:
        rep.warn(f"{where} meta description is {len(desc)} chars (≤ {DESC_MAX})")
    elif len(desc) < 70:
        rep.warn(f"{where} meta description is only {len(desc)} chars (aim for 110–160)")
    if 'name="robots" content="index' in html and 'rel="canonical"' not in html:
        rep.warn(f"{where} indexable page without rel=canonical")
    text = _TEXT_RE.sub(" ", html)
    if _PRICE_RE.search(text):
        rep.warn(f"{where} looks like a price: «{_PRICE_RE.search(text).group(0)}» (no prices on the site)")
    if _BANNED_RE.search(text):
        rep.warn(f"{where} banned wording: «{_BANNED_RE.search(text).group(0)}»")
    m = _OLD_BRAND_RE.search(htmllib.unescape(text + " " + title + " " + desc))
    if m:
        rep.warn(f"{where} old brand name «{m.group(0)}» — the brand is «домщенков.рф» (site.brand)")
    caps = sorted({w for w in _CAPS_WORD_RE.findall(htmllib.unescape(text)) if w not in CAPS_OK and not re.fullmatch(r"[A-Z]\d*", w)})
    if caps:
        rep.warn(f"{where} words in capitals: {', '.join(caps[:6])} — write in normal case (client style rule)")


# ---------------------------------------------------------------- output
def write_if_changed(path: Path, content: str) -> bool:
    data = content.encode("utf-8")
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".html")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    return True


def read_manifest() -> dict:
    try:
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
        return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        return {}


def safe_generated(rel: str) -> Path | None:
    """A manifest entry is deletable only if it is an index.html inside the repo, outside protected folders."""
    p = (ROOT / rel).resolve()
    if p.name != "index.html" or ROOT not in p.parents:
        return None
    first = Path(rel).parts[0] if Path(rel).parts else ""
    if first in PROTECTED or rel.startswith(("/", "..")):
        return None
    return p


# ---------------------------------------------------------------- main
# ---------------------------------------------------------------- publishing
def publish_config(data: dict, rep: Report):
    """(pages, fallbacks) from src/data/publish.json, or None if it is missing or malformed (the build then stops:
    a typo must never publish the whole site)."""
    pub = data.get("publish")
    pages = pub.get("pages") if isinstance(pub, dict) else None
    if not isinstance(pages, list) or not pages or not all(isinstance(p, str) and p.startswith("/") for p in pages):
        rep.error("src/data/publish.json: needs \"pages\": [\"/\", \"/maltipu/\", …] (URLs from the site root). "
                  "Nothing was written. To look at every page: python3 tools/build.py --all")
        return None
    fb = pub.get("link_fallbacks") if isinstance(pub.get("link_fallbacks"), dict) else {}
    fallbacks = {k: [c for c in v if isinstance(c, str) and c.startswith(("#", "/#"))]
                 for k, v in fb.items() if not k.startswith("_") and isinstance(v, list)}
    return pages, fallbacks


def publish_matcher(pages):
    """url → True if the page goes out («/x/*» = the whole section). pages=None → everything (--all)."""
    if pages is None:
        return lambda url: True
    exact = {p for p in pages if not p.endswith("*")}
    prefixes = tuple(p[:-1] for p in pages if p.endswith("*"))
    return lambda url: url in exact or (bool(prefixes) and url.startswith(prefixes))


def url_of_file(rel: str) -> str:
    """'maltipu/belyj/index.html' → '/maltipu/belyj/'."""
    return "/" if rel == "index.html" else "/" + rel[: -len("index.html")]


_A_ROOT_RE = re.compile(r'<a\b[^>]*\shref="/(?!/)[^"]*"[^>]*>', re.I)


def nofollow_unbuilt(html: str) -> str:
    """Links that stayed root-absolute lead to pages that are not built (not published yet): the site shows a
    toast instead of the page, robots get rel=nofollow so they do not walk into 404s."""
    def fix(m):
        tag = m.group(0)
        rel = re.search(r'\srel="([^"]*)"', tag)
        if rel:
            return tag if "nofollow" in rel.group(1).split() else tag.replace(rel.group(0), f' rel="{rel.group(1)} nofollow"', 1)
        return tag[:-1] + ' rel="nofollow">'
    return _A_ROOT_RE.sub(fix, html)


def link_root_files(out: Path) -> None:
    """_all/ shares assets and root files with the published tree through symlinks."""
    out.mkdir(exist_ok=True)
    for name in ("assets", "favicon.ico", "robots.txt", "site.webmanifest"):
        link, target = out / name, ROOT / name
        if target.exists() and not link.exists() and not link.is_symlink():
            os.symlink(os.path.relpath(target, out), link)


def make_env(data: dict) -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)),
        autoescape=True,
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters.update(typo=typo, plural=plural, ru_date=ru_date, weeks=weeks)
    env.globals.update(
        data=data,
        site=data.get("site", {}),
        breeds=data.get("breeds", []),
        breed_map=data.get("breed_map", {}),
        puppies=data.get("puppies", []),
        imgsize=imgsize,
        plural=plural,
        photo_tone=photo_tone,
        tone_style=tone_style,
    )
    return env


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the домщенков.рф static site.")
    ap.add_argument("--clean", action="store_true", help="delete pages listed in the manifest that this build no longer produces")
    ap.add_argument("--kit", action="store_true", help="also write the UI kit page to /_kit/ (git-ignored)")
    ap.add_argument("--verbose", action="store_true", help="list every unbuilt link target and the pages using it")
    ap.add_argument("--all", action="store_true", help="build every route, not only src/data/publish.json (local review, do not commit)")
    args = ap.parse_args(argv)

    rep = Report()
    load_tones(rep)
    data = load_data(rep)
    enrich(data, rep)
    env = make_env(data)

    routes, failed_modules = discover_routes(data, rep)
    if args.kit:
        routes.append(("(kit)", {"url": KIT_URL, "template": "_dev/kit.html.j2",
                                 "context": {"title": "UI-кит — домщенков.рф", "description": "Компоненты внутренних страниц",
                                             "breadcrumbs": [("Главная", "/"), ("UI-кит", None)]}}))

    if args.all:
        published, fallbacks, out_base = publish_matcher(None), {}, ALL_DIR
        link_root_files(ALL_DIR)
    else:
        cfg = publish_config(data, rep)
        if cfg is None:
            for e in rep.errors:
                print(f"  ✗ {e}")
            return 1
        published, fallbacks, out_base = publish_matcher(cfg[0]), cfg[1], ROOT
    all_urls: set[str] = set()
    unpublished: list[str] = []

    # 1. validate + render
    seo_conf = seo.cfg(data.get("site", {}))
    robots: dict[str, str] = {}
    rendered: dict[str, tuple[str, str]] = {}
    failed_urls: set[str] = set()
    per_module = collections.Counter()
    for module, r in routes:
        try:
            if isinstance(r, (tuple, list)) and len(r) == 3:  # (url, template, context) is accepted too
                r = dict(url=r[0], template=r[1], context=r[2])
            if not isinstance(r, dict):
                raise TypeError("route must be a dict(url=..., template=..., context=...)")
            url, tpl = r.get("url"), r.get("template")
            if not isinstance(url, str) or not (URL_RE.match(url) or (url == KIT_URL and module == "(kit)")):
                raise ValueError(f"bad url {url!r}: must look like /a/b-c/ (lowercase latin, digits, dashes, trailing slash)")
            if url != "/" and url.strip("/").split("/")[0] in PROTECTED:
                raise ValueError(f"url {url} would write into a protected folder")
            if url in rendered:
                raise ValueError(f"url {url} is already produced by routes/{rendered[url][0]}.py")
            all_urls.add(url)
            if url != KIT_URL and not published(url):
                unpublished.append(url)  # not out yet: not rendered, its old file is removed below
                continue
            ctx = dict(r.get("context") or {})
            ctx["page"] = {"url": url, "depth": url.strip("/").count("/") + (url != "/"), "module": module}
            html = env.get_template(tpl).render(**ctx)
            html = seo.finalize(html, url, ctx, data.get("site", {}), seo_conf, imgsize)
            robots[url] = seo.robots_for(url, ctx, seo_conf)
            rendered[url] = (module, html)
            per_module[module] += 1
        except Exception as e:  # noqa: BLE001
            if isinstance(r, dict) and isinstance(r.get("url"), str):
                failed_urls.add(r["url"])
            tb = traceback.format_exc() if not isinstance(e, (ValueError, TypeError, jinja2.TemplateNotFound)) else ""
            rep.error(f"routes/{module}.py: {r.get('url') if isinstance(r, dict) else r!r}: {type(e).__name__}: {e}" + ("\n" + _indent(tb) if tb else ""))

    # 2. pages of a failed module (or a failed page) keep their file from the previous build, and links to them
    #    stay relative — a broken module must not turn working links on every other page into toasts
    old = read_manifest() if not args.all else {}
    old_routes = old.get("routes") if isinstance(old.get("routes"), dict) else {}
    kept = {u: m for u, m in sorted(old_routes.items())
            if u not in rendered and published(u) and (m in failed_modules or u in failed_urls) and out_path_for(u).is_file()}
    kept_files = {out_path_for(u).relative_to(ROOT).as_posix() for u in kept}

    if not args.all:
        pub_pages = publish_config(data, Report())[0]
        for p in pub_pages:
            if not any(publish_matcher([p])(u) for u in all_urls):
                rep.warn(f"src/data/publish.json: «{p}» matches no route")
        if "/" not in pub_pages:
            rep.warn("src/data/publish.json: the homepage «/» is not published")
        home_ids = set(re.findall(r'\sid="([^"]+)"', rendered["/"][1])) if "/" in rendered else set()
        for k, cands in fallbacks.items():
            for c in cands:
                if c.startswith("/#") and c[2:] not in home_ids:
                    rep.warn(f"publish.json link_fallbacks: {k} → {c}: the homepage has no id «{c[2:]}»")

    # 3. rewrite links (only now we know which routes exist), lint, write.
    #    Root files that pages link to are written first, so the rewriter finds them.
    root_files = {"site.webmanifest": seo.webmanifest(data.get("site", {}), seo_conf), "robots.txt": seo.robots_txt(seo_conf)}
    for name, text in root_files.items():
        if not args.all or not (ROOT / name).is_file():
            write_if_changed(ROOT / name, text)
    if args.all:
        link_root_files(ALL_DIR)
    rw = Rewriter(set(rendered) | set(kept), fallbacks)
    written, changed = [], 0
    old_lastmod = old.get("lastmod") if isinstance(old.get("lastmod"), dict) else {}
    lastmod: dict[str, list[str]] = {}
    for url in sorted(rendered):
        module, html = rendered[url]
        html = nofollow_unbuilt(rw.page(html, url))
        lint(html, url, rep)
        out = out_path_for(url, out_base)
        if write_if_changed(out, html):
            changed += 1
        if url != KIT_URL:  # the dev kit is git-ignored and never listed in the manifest
            written.append(out.relative_to(out_base).as_posix())
            fp = seo.page_fingerprint(html)
            prev = old_lastmod.get(url)
            lastmod[url] = [fp, prev[1]] if isinstance(prev, list) and len(prev) == 2 and prev[0] == fp else [fp, seo.today()]
    for url in kept:  # pages kept from the previous build keep their date
        if isinstance(old_lastmod.get(url), list):
            lastmod[url] = old_lastmod[url]

    # 3b. 404 page and sitemap.xml (root files, not listed in the manifest)
    try:
        ctx404 = {"title": "Страница не найдена | домщенков.рф",
                  "description": "Такой страницы на сайте нет. Щенки в наличии, породы и контакты питомника — по ссылкам ниже.",
                  "breadcrumbs": [("Главная", "/"), ("Страница не найдена", None)], "robots": "noindex, follow",
                  "page": {"url": "/404.html", "depth": 0, "module": "(404)"}}
        html = env.get_template("pages/404.html.j2").render(**ctx404)
        html = seo.finalize(html, "/404.html", ctx404, data.get("site", {}), seo_conf, imgsize)
        html = nofollow_unbuilt(rw.page(html, "/"))  # links relative to the site root; the page sets <base> itself
        lint(html, "/404.html", rep)
        write_if_changed(out_base / "404.html", html)
    except Exception as e:  # noqa: BLE001
        rep.error(f"404.html: {type(e).__name__}: {e}")
    entries = [(u, lastmod[u][1]) for u in sorted(set(rendered) | set(kept))
               if u != KIT_URL and u in lastmod and seo.indexable(robots.get(u, ""))]
    if not args.all:  # sitemap lists what is published; a local --all review must not change it
        write_if_changed(ROOT / "sitemap.xml", seo.sitemap_xml(entries, seo_conf))

    lint_css(rep)

    for path, pages in sorted(rw.missing.items()):
        rep.warn(f"missing file {path} (used on {', '.join(sorted(pages)[:3])}{' …' if len(pages) > 3 else ''})")

    # 4. manifest + stale pages (the published tree only; --all writes just a route list into _all/)
    if args.all:
        (ALL_DIR / ".build-manifest.json").write_text(json.dumps(
            {"note": "tools/build.py --all: every route, for local review. Not deployed.", "routes": dict(sorted(
                {u: rendered[u][0] for u in rendered if u != KIT_URL}.items()))}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        return summary(args, rep, rw, per_module, rendered, changed, entries, unpublished, all_urls, kept, [], [])
    old_files = set(old.get("files", []))
    new_files = set(written)
    kit_file = out_path_for(KIT_URL).relative_to(ROOT).as_posix()
    stale = sorted(f for f in old_files - new_files - kept_files if f != kit_file and (ROOT / f).is_file())
    removed = []

    def delete_page(rel: str) -> None:
        p = safe_generated(rel)
        if p is None:
            rep.warn(f"refusing to delete {rel}")
            return
        p.unlink()
        removed.append(rel)
        d = p.parent
        while d != ROOT and d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            d = d.parent

    # pages that are not published (any more) leave the repo on every normal build, errors or not —
    # also files of unpublished routes the manifest does not know (e.g. brought in by a merge)
    for rel in [r for r in stale if not published(url_of_file(r))]:
        delete_page(rel)
    for url in unpublished:
        rel = out_path_for(url).relative_to(ROOT).as_posix()
        if (ROOT / rel).is_file() and rel not in removed:
            delete_page(rel)
    stale = [r for r in stale if r not in removed]
    if args.clean and rep.errors:
        rep.warn("--clean skipped: the build has errors (a broken module must not delete its pages)")
    elif args.clean:
        for rel in stale:
            delete_page(rel)
        stale = [s for s in stale if s not in removed]
    manifest = {
        "note": "Written by tools/build.py. Lists generated pages; --clean deletes only files listed here.",
        "files": sorted(new_files | set(stale) | kept_files),
        "routes": dict(sorted({**kept, **{url: rendered[url][0] for url in rendered if url != KIT_URL}}.items())),
        "lastmod": dict(sorted(lastmod.items())),  # [content hash, date it last changed] → sitemap.xml <lastmod>
    }
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if not MANIFEST.is_file() or MANIFEST.read_text(encoding="utf-8") != text:
        fd, tmp = tempfile.mkstemp(dir=ROOT, prefix=".tmp-manifest-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, MANIFEST)

    return summary(args, rep, rw, per_module, rendered, changed, entries, unpublished, all_urls, kept, removed, stale)


def summary(args, rep, rw, per_module, rendered, changed, entries, unpublished, all_urls, kept, removed, stale) -> int:
    # 5. summary
    print("домщенков.рф build")
    mods = ", ".join(f"{m} ({n})" for m, n in sorted(per_module.items()))
    print(f"  routes: {mods or '—'}")
    print(f"  pages written: {len(rendered)} ({changed} changed, {len(rendered) - changed} unchanged)")
    if args.all:
        print("  --all: every route → _all/ (git-ignored, not deployed): python3 -m http.server 8765 --directory _all")
    else:
        print(f"  sitemap.xml: {len(entries)} pages · robots.txt · 404.html · site.webmanifest")
    if rw.rerouted:
        print(f"  links to unpublished pages sent to a block on a published page: "
              + ", ".join(f"{u} ×{n}" for u, n in sorted(rw.rerouted.items())))
    if not args.all and unpublished:
        print(f"  published (src/data/publish.json): {len(rendered) - (KIT_URL in rendered)} pages; "
              f"{len(unpublished)} more routes wait (python3 tools/build.py --all to see them)")
    if kept:
        print(f"  NOT rebuilt (module or page failed): {len(kept)} page(s) kept from the previous build, links to them stay relative")
        for url, mod in kept.items():
            print(f"    = {url}  (routes/{mod}.py)")
    if removed:
        print(f"  removed pages: {len(removed)}")
        for rel in removed[:12]:
            print(f"    - {rel}")
        if len(removed) > 12:
            print(f"    … and {len(removed) - 12} more")
    if stale:
        print(f"  stale pages from earlier builds: {len(stale)} (run with --clean to delete)")
        for rel in stale:
            print(f"    ~ {rel}")
    waiting = {u: n for u, n in rw.unbuilt.items() if u in all_urls}  # not published yet — expected
    missing_pages = {u: n for u, n in rw.unbuilt.items() if u not in all_urls}  # no route at all
    if waiting:
        print(f"  links to not-yet-published pages: {sum(waiting.values())} links to {len(waiting)} pages "
              f"(toast + nofollow; --verbose lists them)")
        if args.verbose:
            for url, n in sorted(waiting.items(), key=lambda kv: (-kv[1], kv[0])):
                print(f"    {n:4d}  {url}   ← " + ", ".join(sorted(rw.unbuilt_pages[url])))
    if missing_pages:
        total = sum(missing_pages.values())
        print(f"  unbuilt link targets: {len(missing_pages)} URLs, {total} links (no route — stay root-absolute → toast)")
        for url, n in sorted(missing_pages.items(), key=lambda kv: (-kv[1], kv[0])):
            extra = ""
            if args.verbose:
                extra = "   ← " + ", ".join(sorted(rw.unbuilt_pages[url]))
            print(f"    {n:4d}  {url}{extra}")
    if rep.warnings:
        print(f"  warnings: {len(rep.warnings)}")
        for w in rep.warnings:
            print(f"    ! {w}")
    if rep.errors:
        print(f"  ERRORS: {len(rep.errors)}")
        for e in rep.errors:
            print(f"    ✗ {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
