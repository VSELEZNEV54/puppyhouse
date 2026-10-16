#!/usr/bin/env python3
"""Files the production server needs next to the pages, written into a deploy folder (never into the repo, so the
GitHub Pages preview stays as it is):

  404.html     — «Такой страницы нет» in the site design, with ROOT-ABSOLUTE links (nginx shows it at any address)
  robots.txt   — closes /admin/ and /api/, drops utm/yclid duplicates for Yandex, points to the sitemap
  sitemap.xml  — every built page (.build-manifest.json → routes), absolute https URLs of the production domain

  python3 tools/site_extras.py OUT_DIR        (run after tools/build.py; tools/release.sh calls it for every
                                               release)
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent


def _build_module():
    spec = importlib.util.spec_from_file_location("dsh_build", ROOT / "tools" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    b = _build_module()

    manifest = json.loads((ROOT / ".build-manifest.json").read_text(encoding="utf-8"))
    routes = sorted(u for u in manifest.get("routes", {}) if u != b.KIT_URL)
    if not routes:
        print("site_extras: .build-manifest.json lists no pages — run tools/build.py first", file=sys.stderr)
        return 1

    rep = b.Report()
    b.load_tones(rep)
    data = b.load_data(rep)
    b.enrich(data, rep)
    if rep.errors:
        print("site_extras: the site data has errors — run tools/build.py and fix them first", file=sys.stderr)
        return 1
    site = data["site"]
    origin = "https://" + site["domain_ascii"]

    # 404: the same Rewriter as the pages (cache-busting ?v= on css/js, missing-file checks), but links stay absolute
    class Absolute(b.Rewriter):
        def rel(self, target, page_url, is_dir):
            return (target.rstrip("/") + "/" if target != "/" else "/") if is_dir else target

    env = b.make_env(data)
    ctx = {"title": "Страница не найдена — домщенков.рф", "description": "Такой страницы на сайте нет.",
           "breadcrumbs": [["Главная", "/"], ["Страница не найдена", None]],
           "page": {"url": "/404/", "depth": 1, "module": "(404)"}}
    rw = Absolute(set(routes))
    html = rw.page(env.get_template("pages/404.html.j2").render(**ctx), "/404/")
    if rw.missing:
        print(f"site_extras: 404.html refers to missing files: {sorted(rw.missing)}", file=sys.stderr)
        return 1
    (out / "404.html").write_text(html, encoding="utf-8")

    params = "utm_source&utm_medium&utm_campaign&utm_content&utm_term&yclid&gclid&ysclid"
    (out / "robots.txt").write_text(
        "User-agent: *\n"
        "Disallow: /admin/\n"
        "Disallow: /api/\n"
        f"Clean-param: {params}\n"
        "\n"
        f"Sitemap: {origin}/sitemap.xml\n", encoding="utf-8")

    urls = "".join(f"  <url><loc>{escape(origin + u)}</loc></url>\n" for u in routes)
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "</urlset>\n", encoding="utf-8")
    print(f"site extras → {out}: 404.html, robots.txt, sitemap.xml ({len(routes)} pages)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
