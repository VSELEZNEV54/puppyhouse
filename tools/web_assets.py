"""Build page-specific CSS and minified JS without changing their source files.

Only provably absent required class/id selectors are removed. Selectors inside
functions (:is, :not, :has, etc.) are deliberately kept, as are all names found
in scripts and runtime state classes. This is not browser coverage-based purging:
menus, modals, hover states, breakpoints and future user interactions remain styled.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import os
import posixpath
import re
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import rcssmin
import rjsmin
import tinycss2


_LINK = re.compile(r"<link\b[^>]*>", re.I)
_ATTR = re.compile(r"([\w-]+)\s*=\s*([\"'])(.*?)\2", re.S)
_SCRIPT = re.compile(r"(<script\b[^>]*\bsrc=)([\"'])(.*?)\2", re.I)
_URL = re.compile(r"url\(\s*([\"']?)([^\"')\s]+)\1\s*\)")
_TOKEN = re.compile(r"[a-zA-Z_][\w-]*")
_STATE_PREFIXES = ("is-", "has-")


class _HeroImage(HTMLParser):
    """Pick the first eager content image, using exactly the browser's responsive candidates."""

    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.in_main = False
        self.image: dict[str, str] = {}
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.in_main = True
        if self.in_main and tag == "img" and not self.image:
            image = dict(attrs)
            if image.get("fetchpriority") == "high" and image.get("loading") != "lazy":
                self.image = image

    def handle_endtag(self, tag):
        if tag == "main":
            self.in_main = False


def preload_hero(source: str) -> str:
    image = _HeroImage(source).image
    if not image or not image.get("src") or 'data-hero-preload' in source:
        return source
    attrs = {"rel": "preload", "as": "image", "href": image["src"], "fetchpriority": "high"}
    if image.get("srcset"):
        attrs["imagesrcset"] = image["srcset"]
        if image.get("sizes"):
            attrs["imagesizes"] = image["sizes"]
    link = '<link data-hero-preload ' + ' '.join(
        f'{key}="{html_lib.escape(value, quote=True)}"' for key, value in attrs.items()
    ) + '>'
    # viewport must precede imagesizes evaluation; insert before fonts and other downloads.
    viewport = re.search(r'<meta\b[^>]*\bname=[\"\']viewport[\"\'][^>]*>', source, re.I)
    if not viewport:
        return source
    return source[:viewport.end()] + '\n  ' + link + source[viewport.end():]


class _Names(HTMLParser):
    """Read actual attributes; text and embedded SVG/CSS strings are not classes."""

    def __init__(self, source: str, first_screen: bool = False):
        super().__init__(convert_charrefs=True)
        self.classes: set[str] = set()
        self.ids: set[str] = set()
        self.first_screen = first_screen
        self.in_main = False
        self.section_depth = 0
        self.sections_seen = 0
        self.section_limit = 2
        self.finished = False
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        if self.finished:
            return
        attrs = dict(attrs)
        self.classes.update(attrs.get("class", "").split())
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "main":
            self.in_main = True
        if self.in_main and tag == "section":
            if not self.section_depth:
                self.sections_seen += 1
                if self.sections_seen == 1 and self.classes.intersection({"hero--full", "phero--full", "pp"}):
                    self.section_limit = 1
            self.section_depth += 1

    def handle_endtag(self, tag):
        if self.in_main and tag == "section" and self.section_depth:
            self.section_depth -= 1
            if not self.section_depth and self.first_screen and self.sections_seen >= self.section_limit:
                self.finished = True


def _selectors(tokens):
    """Split only top-level commas, not :is() or attribute values."""
    group = []
    for token in tokens:
        if token.type == "literal" and token.value == ",":
            yield group
            group = []
        else:
            group.append(token)
    yield group


def _possible(tokens, classes: set[str], ids: set[str]) -> bool:
    for i, token in enumerate(tokens):
        # Functional selectors may match alternatives or negation. Do not infer
        # a required class from their arguments. Attribute blocks are also opaque.
        if token.type == "literal" and token.value == "." and i + 1 < len(tokens):
            name = tokens[i + 1]
            if name.type == "ident" and name.value not in classes and not name.value.startswith(_STATE_PREFIXES):
                return False
        if token.type == "hash" and token.is_identifier and token.value not in ids:
            return False
    return True


def filter_css(css: str, classes: set[str], ids: set[str]) -> str:
    def rules(items):
        out = []
        for rule in items:
            if rule.type == "qualified-rule":
                selectors = [tinycss2.serialize(s).strip() for s in _selectors(rule.prelude) if _possible(s, classes, ids)]
                if selectors:
                    out.append(",".join(selectors) + "{" + tinycss2.serialize(rule.content) + "}")
            elif rule.type == "at-rule":
                if rule.lower_at_keyword == "charset":
                    continue
                if rule.content is not None and rule.lower_at_keyword in {"media", "supports", "layer", "container"}:
                    children = rules(tinycss2.parse_rule_list(rule.content, skip_whitespace=True, skip_comments=True))
                    if children:
                        out.append("@" + rule.at_keyword + tinycss2.serialize(rule.prelude) + "{" + children + "}")
                else:
                    # Font faces and keyframes are not selector rules.
                    out.append(tinycss2.serialize([rule]))
            elif rule.type == "error":
                raise ValueError(f"Invalid CSS: {rule.message}")
        return "".join(out)

    return rcssmin.cssmin(rules(tinycss2.parse_stylesheet(css, skip_whitespace=True, skip_comments=True)))


def _absolute_urls(css: str, source_url: str) -> str:
    def replace(match):
        value = match.group(2)
        if value.startswith(("/", "#", "data:", "http:", "https:")):
            return match.group(0)
        value = posixpath.normpath(posixpath.join(posixpath.dirname(source_url), value))
        return 'url("' + value + '")'
    return _URL.sub(replace, css)


class WebAssets:
    def __init__(self, root: Path):
        self.root = root
        self.scripts: dict[str, str] = {}
        self.runtime_names: set[str] = {"js", "rv"}
        self.styles: dict[str, str] = {}
        self.cache: dict[tuple, tuple[str, str]] = {}
        self.used: set[Path] = set()
        for path in sorted((root / "assets" / "js").glob("*.js")):
            if path.name.endswith(".min.js"):
                continue
            source = path.read_text(encoding="utf-8")
            self.runtime_names.update(_TOKEN.findall(source))
            url = "/" + path.relative_to(root).as_posix()
            self.scripts[url] = self._write(path.stem, ".js", rjsmin.jsmin(source))
        for path in sorted((root / "assets" / "css").glob("*.css")):
            if path.name.endswith(".min.css"):
                continue
            url = "/" + path.relative_to(root).as_posix()
            self.styles[url] = _absolute_urls(path.read_text(encoding="utf-8"), url)

    def _write(self, name: str, suffix: str, content: str) -> str:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        path = self.root / "assets" / suffix.lstrip(".") / f"{name}.{digest}.min{suffix}"
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
                output.write(content)
                temporary = output.name
            os.replace(temporary, path)
        self.used.add(path)
        return "/" + path.relative_to(self.root).as_posix()

    def page(self, source: str) -> str:
        """Call after template/SEO rendering, before build.py's relative URL rewrite."""
        source = preload_hero(source)
        links = []
        for match in _LINK.finditer(source):
            attrs = {k.lower(): html_lib.unescape(v) for k, _, v in _ATTR.findall(match.group())}
            href = attrs.get("href", "").split("?", 1)[0]
            if attrs.get("rel") == "stylesheet" and href in self.styles and not attrs.get("media"):
                links.append((match, href))
        if links:
            names = _Names(source)
            critical_names = _Names(source, first_screen=True)
            # Cookie consent is inserted by main.js and may appear on first paint.
            critical_names.classes.update(n for n in self.runtime_names if n.startswith(("cookie", "consent")))
            critical_names.classes.update({"js", "rv", "hp", "sr-only", "section", "section--tight", "sec-head"})
            key = (tuple(url for _, url in links), tuple(sorted(names.classes)), tuple(sorted(names.ids)),
                   tuple(sorted(critical_names.classes)), tuple(sorted(critical_names.ids)))
            if key not in self.cache:
                css = "\n".join(self.styles[url] for _, url in links)
                filtered = filter_css(css, names.classes | self.runtime_names, names.ids | self.runtime_names)
                critical = filter_css(css, critical_names.classes, critical_names.ids)
                # External CSS URLs are relative to /assets/css; inline CSS stays
                # root-absolute so Rewriter can make it correct on every route.
                external = _URL.sub(lambda m: 'url("' + posixpath.relpath(m.group(2), "/assets/css") + '")'
                                    if m.group(2).startswith("/") and not m.group(2).startswith("//") else m.group(0), filtered)
                href = self._write("site", ".css", external)
                self.cache[key] = (href, critical)
            href, critical = self.cache[key]
            replacement = (f'<style data-critical-css>{critical}</style>\n'
                           f'  <link rel="preload" as="style" href="{href}" data-site-styles '
                           'onload="this.onload=null;this.rel=\'stylesheet\'">\n'
                           f'  <noscript><link rel="stylesheet" href="{href}"></noscript>')
            for i, (match, _) in reversed(list(enumerate(links))):
                source = source[:match.start()] + (replacement if i == 0 else "") + source[match.end():]

        def script(match):
            url = match.group(3).split("?", 1)[0]
            return match.group(1) + match.group(2) + self.scripts.get(url, match.group(3)) + match.group(2)
        return re.sub(r"(?m)^[ \t]+$", "", _SCRIPT.sub(script, source))
