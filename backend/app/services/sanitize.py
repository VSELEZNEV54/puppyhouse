"""Input hygiene for text that came from the public: control characters out, length capped, paths normalised."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")
_SPACES = re.compile(r"[ \t ]+")


def clean(value: str | None, limit: int, multiline: bool = False) -> str | None:
    """Strip control and bidi characters, squeeze spaces, cap the length; '' → None."""
    if value is None:
        return None
    s = _CTRL.sub("", str(value))
    if multiline:
        s = "\n".join(_SPACES.sub(" ", line).strip() for line in s.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
        s = re.sub(r"\n{3,}", "\n\n", s).strip()
    else:
        s = _SPACES.sub(" ", s.replace("\n", " ").replace("\r", " ")).strip()
    return s[:limit] or None


def path(value: str | None, base_paths: list[str]) -> str | None:
    """'/puppyhouse/maltipu/?utm_source=x#top' → '/maltipu/'. Query and fragment are dropped (they may carry
    personal data); the GitHub Pages subpath is removed so preview and production paths match."""
    if not value:
        return None
    try:
        p = urlsplit(str(value)).path or "/"
    except ValueError:
        return None
    p = _CTRL.sub("", p)
    if not p.startswith("/"):
        p = "/" + p
    for base in base_paths:
        b = "/" + base.strip("/")
        if b != "/" and (p == b or p.startswith(b + "/")):
            p = p[len(b):] or "/"
            break
    if p.endswith("/index.html"):
        p = p[: -len("index.html")]
    return p[:300]


def host(url: str | None) -> str | None:
    """Only the host of a referrer: the full URL may carry search queries or personal data."""
    if not url:
        return None
    try:
        h = urlsplit(str(url)).hostname
    except ValueError:
        return None
    return h[:200] if h else None


def device(user_agent: str | None) -> str | None:
    ua = (user_agent or "").lower()
    if not ua:
        return None
    if any(b in ua for b in ("bot", "spider", "crawl", "headless", "lighthouse", "preview")):
        return "bot"
    if "ipad" in ua or "tablet" in ua:
        return "tablet"
    if "mobi" in ua or "android" in ua or "iphone" in ua:
        return "mobile"
    return "desktop"
