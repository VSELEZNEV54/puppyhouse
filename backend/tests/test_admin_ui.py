"""The admin panel (backend/admin_ui) is served by the API itself at /admin/ with a strict CSP of its own."""
from __future__ import annotations

import re

from app.config import BACKEND_DIR

UI = BACKEND_DIR / "admin_ui"


def test_the_panel_is_served_with_its_own_csp(client):
    r = client.get("/admin/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert 'id="app"' in r.text and "admin.js" in r.text
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert r.headers["x-robots-tag"] == "noindex, nofollow"
    assert r.headers["cache-control"] == "no-store"


def test_the_panel_without_a_slash_redirects(client):
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code in (301, 307, 308) and r.headers["location"].endswith("/admin/")


def test_scripts_styles_and_fonts_are_served(client):
    for name, ctype in (("admin.js", "javascript"), ("admin.css", "text/css"), ("fonts/geist-cyrillic.woff2", "font")):
        r = client.get(f"/admin/{name}")
        assert r.status_code == 200 and ctype in r.headers["content-type"], name
    assert client.get("/admin/nope.js").status_code == 404
    assert client.get("/admin/../app/config.py").status_code == 404


def test_the_api_keeps_the_locked_down_csp(client):
    assert client.get("/api/v1/health").headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_the_panel_never_renders_data_as_html():
    """Request fields come from site visitors: the panel builds the DOM with textContent only."""
    js = (UI / "admin.js").read_text(encoding="utf-8")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert bad not in js, bad
    assert not re.search(r"setAttribute\(\s*['\"](style|on\w+)", js)
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in html and "style=" not in html  # nothing inline: the CSP would block it
