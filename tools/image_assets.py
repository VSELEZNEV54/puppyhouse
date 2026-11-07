#!/usr/bin/env python3
"""Generate and apply responsive WebP images without changing the original photos.

    python -m pip install -r requirements-build.txt
    python tools/image_assets.py

Commit assets/img/responsive/ and its manifest with source-image changes. Ordinary
site builds use the committed files and need no image encoder. Content hashes in
variant names make caching safe when a source photo or encoding settings change.
"""
from __future__ import annotations

import hashlib
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
DIRECTORY = Path("assets/img/responsive")
MANIFEST = DIRECTORY / "manifest.json"
WIDTHS = (160, 320, 480, 640, 960, 1280)
# These near-screen photos render at ~665 physical pixels on the mobile audit.
# A middle candidate avoids downloading the much larger 960px version.
EXTRA_WIDTHS = {"hero-four-breeds": (768,), "about-pudel-309": (768,)}
PROFILE = "webp-v1-q78-method6-pillow12"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_widths(stem: str, width: int) -> list[int]:
    return sorted({w for w in WIDTHS + EXTRA_WIDTHS.get(stem, ()) if w < width} | {min(width, WIDTHS[-1])})


def generate(root: Path = ROOT) -> dict:
    """Explicit maintenance step; regenerate changed sources only, never upscale."""
    from PIL import Image, ImageOps

    manifest_path = root / MANIFEST
    old = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    previous = old.get("images", {}) if old.get("profile") == PROFILE else {}
    images = {}
    written = 0
    (root / DIRECTORY).mkdir(parents=True, exist_ok=True)
    for path in sorted((root / "assets/img").glob("*")):
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        src = "/" + path.relative_to(root).as_posix()
        checksum = digest(path)
        cached = previous.get(src)
        if cached and cached["sha256"] != checksum:
            cached = None
        existing = {v["width"]: v for v in cached["variants"]} if cached else {}
        if cached and set(candidate_widths(path.stem, cached["width"])) == set(existing) and all((root / item["src"].lstrip("/")).is_file() for item in cached["variants"]):
            images[src] = cached
            continue
        with Image.open(path) as source:
            photo = ImageOps.exif_transpose(source)
            photo = photo.convert("RGBA" if "A" in photo.getbands() else "RGB")
            width, height = photo.size
            widths = candidate_widths(path.stem, width)
            version = hashlib.sha256((checksum + PROFILE).encode()).hexdigest()[:12]
            variants = []
            for w in widths:
                variant = existing.get(w)
                if variant and (root / variant["src"].lstrip("/")).is_file():
                    variants.append(variant)
                    continue
                h = max(1, round(height * w / width))
                output = DIRECTORY / f"{path.stem}-{version}-{w}.webp"
                resized = photo.resize((w, h), Image.Resampling.LANCZOS)
                resized.save(root / output, "WEBP", quality=78, method=6)
                variants.append({"src": "/" + output.as_posix(), "width": w, "height": h, "bytes": (root / output).stat().st_size})
                written += 1
            images[src] = {"sha256": checksum, "width": width, "height": height, "bytes": path.stat().st_size, "variants": variants}
    manifest = {"profile": PROFILE, "images": images}
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if not manifest_path.exists() or manifest_path.read_text() != text:
        manifest_path.write_text(text)
    # Remove only our generated variants; originals and any unrelated files stay.
    live = {Path(v["src"]).name for entry in images.values() for v in entry["variants"]}
    for path in (root / DIRECTORY).glob("*.webp"):
        if path.name not in live and re.fullmatch(r".+-[0-9a-f]{12}-\d+\.webp", path.name):
            path.unlink()
    print(f"Responsive images: {len(images)} sources, {written} variants written, "
          f"{sum(v['bytes'] for entry in images.values() for v in entry['variants']) / 1024 / 1024:.1f} MiB total")
    return manifest


def image_sizes(classes: set[str], lazy: bool) -> str:
    """Native lazy-image auto sizing uses the actual layout; older engines get a fallback.

    Faces are scaled inside their circles, so reserve 2.1× their CSS width rather
    than using auto. Eager hero images need an explicit size before layout exists.
    """
    if "face" in classes:
        return "128px"
    if "bsub-cface" in classes or "pp-thumb" in classes:
        return "160px"
    if "hero__photo" in classes:
        return "(max-width: 1000px) 100vw, (min-width: 1600px) 1120px, 70vw"
    if "phero__photo" in classes:
        fallback = "(max-width: 760px) 100vw, (min-width: 1600px) 900px, 65vw"
    elif "hm-about__photo" in classes:
        fallback = "(max-width: 1000px) calc(100vw - 32px), (min-width: 1600px) 650px, 42vw"
    elif "pp-slide__btn" in classes:
        fallback = "(max-width: 760px) calc(100vw - 32px), (min-width: 1600px) 800px, 50vw"
    elif "pup__media" in classes or "pups" in classes:
        fallback = "(max-width: 560px) calc(100vw - 48px), (max-width: 900px) 45vw, (max-width: 1199px) 30vw, (min-width: 1600px) 400px, 25vw"
    elif "mcard" in classes:
        fallback = "(max-width: 760px) 72vw, (min-width: 1600px) 380px, 30vw"
    elif "rvw__media" in classes or "vrev__media" in classes:
        fallback = "(max-width: 760px) calc(100vw - 48px), 360px"
    else:
        fallback = "(max-width: 760px) calc(100vw - 32px), (min-width: 1600px) 800px, 50vw"
    return ("auto, " if lazy else "") + fallback


class ResponsiveImages:
    """Apply to rendered HTML before its root-absolute URLs are relativized."""

    def __init__(self, root: Path = ROOT):
        self.root = root
        path = root / MANIFEST
        manifest = json.loads(path.read_text()) if path.is_file() else {}
        if manifest.get("profile") != PROFILE:
            raise ValueError("Responsive image manifest missing/outdated; run python tools/image_assets.py")
        self.images = manifest["images"]
        self.checked: set[str] = set()

    def entry(self, src: str):
        if not src.startswith("/assets/img/") or Path(src).suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            return None
        if src not in self.checked:
            entry = self.images.get(src)
            source = self.root / src.lstrip("/")
            if not entry or not source.is_file() or entry["sha256"] != digest(source):
                raise ValueError(f"Responsive image missing/outdated for {src}; run python tools/image_assets.py")
            if not all((self.root / v["src"].lstrip("/")).is_file() for v in entry["variants"]):
                raise ValueError(f"Responsive variants missing for {src}; run python tools/image_assets.py")
            self.checked.add(src)
        return self.images[src]

    def process(self, html: str) -> str:
        parser = _ImageHTML(self, html)
        parser.feed(html)
        for start, end, replacement in reversed(parser.edits):
            html = html[:start] + replacement + html[end:]
        return html


class _ImageHTML(HTMLParser):
    def __init__(self, images: ResponsiveImages, html: str):
        super().__init__(convert_charrefs=False)
        self.images = images
        self.stack: list[tuple[str, set[str], dict]] = []
        self.edits = []
        self.lines = [0]
        self.lines.extend(m.end() for m in re.finditer("\n", html))

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = set(values.get("class", "").split())
        if tag == "img":
            ancestors = classes.union(*(item[1] for item in self.stack))
            # JS replaces these sources at runtime. A fixed srcset would override
            # its new src and keep showing the first puppy in every modal.
            dynamic = "data-lb-img" in values or any("data-pm-thumb" in item[2] for item in self.stack)
            if not dynamic and "srcset" not in values and not any(item[0] == "picture" for item in self.stack):
                entry = self.images.entry(values.get("src", ""))
                if entry:
                    raw = self.get_starttag_text()
                    source_set = ", ".join(f"{v['src']} {v['width']}w" for v in entry["variants"])
                    sizes = values.get("sizes") or image_sizes(ancestors, values.get("loading") == "lazy")
                    additions = f' srcset="{escape(source_set, quote=True)}"'
                    if "sizes" not in values:
                        additions += f' sizes="{escape(sizes, quote=True)}"'
                    ending = "/>" if raw.endswith("/>") else ">"
                    replacement = raw[:-len(ending)] + additions + ending
                    line, column = self.getpos()
                    start = self.lines[line - 1] + column
                    self.edits.append((start, start + len(raw), replacement))
        if tag not in VOID:
            self.stack.append((tag, classes, values))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


if __name__ == "__main__":
    generate()
