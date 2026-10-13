#!/usr/bin/env python3
"""Puppy House static site generator.

    python3 tools/build.py            build every route into <url>/index.html
    python3 tools/build.py --clean    also delete pages from earlier builds that no route produces now
    python3 tools/build.py --kit      also write the developer UI kit to /_kit/ (git-ignored)

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
NBSP = " "


def _typo_text(s: str) -> str:
    s = _DASH.sub(NBSP, s)
    s = _SHORT_WORD.sub(lambda m: m.group(1) + NBSP, s)
    s = _PARTICLE.sub(NBSP, s)
    s = _NUM_UNIT.sub(lambda m: m.group(1) + NBSP, s)
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


def out_path_for(url: str) -> Path:
    return ROOT / url.strip("/") / "index.html" if url != "/" else ROOT / "index.html"


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
    def __init__(self, built: set[str]):
        self.built = built
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
    text = _TEXT_RE.sub(" ", html)
    if _PRICE_RE.search(text):
        rep.warn(f"{where} looks like a price: «{_PRICE_RE.search(text).group(0)}» (no prices on the site)")
    if _BANNED_RE.search(text):
        rep.warn(f"{where} banned wording: «{_BANNED_RE.search(text).group(0)}»")
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
    ap = argparse.ArgumentParser(description="Build the Puppy House static site.")
    ap.add_argument("--clean", action="store_true", help="delete pages listed in the manifest that this build no longer produces")
    ap.add_argument("--kit", action="store_true", help="also write the UI kit page to /_kit/ (git-ignored)")
    ap.add_argument("--verbose", action="store_true", help="list every unbuilt link target and the pages using it")
    args = ap.parse_args(argv)

    rep = Report()
    load_tones(rep)
    data = load_data(rep)
    enrich(data, rep)
    env = make_env(data)

    routes, failed_modules = discover_routes(data, rep)
    if args.kit:
        routes.append(("(kit)", {"url": KIT_URL, "template": "_dev/kit.html.j2",
                                 "context": {"title": "UI-кит — Puppy House", "description": "Компоненты внутренних страниц",
                                             "breadcrumbs": [("Главная", "/"), ("UI-кит", None)]}}))

    # 1. validate + render
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
            ctx = dict(r.get("context") or {})
            ctx["page"] = {"url": url, "depth": url.strip("/").count("/") + (url != "/"), "module": module}
            html = env.get_template(tpl).render(**ctx)
            rendered[url] = (module, html)
            per_module[module] += 1
        except Exception as e:  # noqa: BLE001
            if isinstance(r, dict) and isinstance(r.get("url"), str):
                failed_urls.add(r["url"])
            tb = traceback.format_exc() if not isinstance(e, (ValueError, TypeError, jinja2.TemplateNotFound)) else ""
            rep.error(f"routes/{module}.py: {r.get('url') if isinstance(r, dict) else r!r}: {type(e).__name__}: {e}" + ("\n" + _indent(tb) if tb else ""))

    # 2. pages of a failed module (or a failed page) keep their file from the previous build, and links to them
    #    stay relative — a broken module must not turn working links on every other page into toasts
    old = read_manifest()
    old_routes = old.get("routes") if isinstance(old.get("routes"), dict) else {}
    kept = {u: m for u, m in sorted(old_routes.items())
            if u not in rendered and (m in failed_modules or u in failed_urls) and out_path_for(u).is_file()}
    kept_files = {out_path_for(u).relative_to(ROOT).as_posix() for u in kept}

    # 3. rewrite links (only now we know which routes exist), lint, write
    rw = Rewriter(set(rendered) | set(kept))
    written, changed = [], 0
    for url in sorted(rendered):
        module, html = rendered[url]
        html = rw.page(html, url)
        lint(html, url, rep)
        out = out_path_for(url)
        if write_if_changed(out, html):
            changed += 1
        if url != KIT_URL:  # the dev kit is git-ignored and never listed in the manifest
            written.append(out.relative_to(ROOT).as_posix())

    lint_css(rep)

    for path, pages in sorted(rw.missing.items()):
        rep.warn(f"missing file {path} (used on {', '.join(sorted(pages)[:3])}{' …' if len(pages) > 3 else ''})")

    # 4. manifest + stale pages
    old_files = set(old.get("files", []))
    new_files = set(written)
    kit_file = out_path_for(KIT_URL).relative_to(ROOT).as_posix()
    stale = sorted(f for f in old_files - new_files - kept_files if f != kit_file and (ROOT / f).is_file())
    removed = []
    if args.clean and rep.errors:
        rep.warn("--clean skipped: the build has errors (a broken module must not delete its pages)")
    elif args.clean:
        for rel in stale:
            p = safe_generated(rel)
            if p is None:
                rep.warn(f"--clean: refusing to delete {rel}")
                continue
            p.unlink()
            removed.append(rel)
            d = p.parent
            while d != ROOT and d.is_dir() and not any(d.iterdir()):
                d.rmdir()
                d = d.parent
        stale = [s for s in stale if s not in removed]
    manifest = {
        "note": "Written by tools/build.py. Lists generated pages; --clean deletes only files listed here.",
        "files": sorted(new_files | set(stale) | kept_files),
        "routes": dict(sorted({**kept, **{url: rendered[url][0] for url in rendered if url != KIT_URL}}.items())),
    }
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if not MANIFEST.is_file() or MANIFEST.read_text(encoding="utf-8") != text:
        fd, tmp = tempfile.mkstemp(dir=ROOT, prefix=".tmp-manifest-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, MANIFEST)

    # 5. summary
    print("Puppy House build")
    mods = ", ".join(f"{m} ({n})" for m, n in sorted(per_module.items()))
    print(f"  routes: {mods or '—'}")
    print(f"  pages written: {len(rendered)} ({changed} changed, {len(rendered) - changed} unchanged)")
    if kept:
        print(f"  NOT rebuilt (module or page failed): {len(kept)} page(s) kept from the previous build, links to them stay relative")
        for url, mod in kept.items():
            print(f"    = {url}  (routes/{mod}.py)")
    if removed:
        print(f"  removed stale pages: {len(removed)}")
        for rel in removed:
            print(f"    - {rel}")
    if stale:
        print(f"  stale pages from earlier builds: {len(stale)} (run with --clean to delete)")
        for rel in stale:
            print(f"    ~ {rel}")
    if rw.unbuilt:
        total = sum(rw.unbuilt.values())
        print(f"  unbuilt link targets: {len(rw.unbuilt)} URLs, {total} links (stay root-absolute → toast)")
        for url, n in sorted(rw.unbuilt.items(), key=lambda kv: (-kv[1], kv[0])):
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
