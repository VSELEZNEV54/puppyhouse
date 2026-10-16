"""Where a visit came from: UTM tags first, then ad click ids, then the referrer host, else direct.

Most visits to a kennel site come from Yandex / Google search or are direct, without UTM tags, so the referrer has to
be classified on the server."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from .sanitize import clean as _clean

UTM_KEYS = ("source", "medium", "campaign", "content", "term")

# Search engines by brand label (yandex.ru, yandex.com.tr, google.de …) or by exact domain.
_SEARCH_BRANDS = {"yandex": "yandex", "google": "google", "bing": "bing", "duckduckgo": "duckduckgo",
                  "rambler": "rambler"}
_SEARCH_DOMAINS = {"ya.ru": "yandex", "go.mail.ru": "mail.ru", "search.yahoo.com": "yahoo"}
_SOCIAL_DOMAINS = {"vk.com": "vk", "vk.ru": "vk", "m.vk.com": "vk", "ok.ru": "ok", "t.me": "telegram",
                   "web.telegram.org": "telegram", "instagram.com": "instagram", "l.instagram.com": "instagram",
                   "facebook.com": "facebook", "youtube.com": "youtube", "youtu.be": "youtube", "dzen.ru": "dzen",
                   "pinterest.com": "pinterest", "pinterest.ru": "pinterest", "tiktok.com": "tiktok",
                   "avito.ru": "avito", "wa.me": "whatsapp", "whatsapp.com": "whatsapp", "max.ru": "max"}


def _on(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _brand(host: str) -> str | None:
    """yandex.ru, www.google.com, yandex.com.tr → the brand; petbook.ru → None (no substring matching)."""
    labels = host.split(".")
    for b, name in _SEARCH_BRANDS.items():
        if b in labels[:-1]:
            return name
    return None


def clean_utm(utm: dict | None) -> dict | None:
    """Keep only the five utm_* keys (without the prefix), trimmed; None if nothing is left."""
    if not utm:
        return None
    out = {}
    for k in UTM_KEYS:
        v = _clean(utm.get(k) or utm.get("utm_" + k), 150) if isinstance(utm.get(k) or utm.get("utm_" + k), str) else None
        if v:
            out[k] = v
    for k in ("yclid", "gclid"):
        v = _clean(utm.get(k), 150) if isinstance(utm.get(k), str) else None
        if v:
            out[k] = v
    return out or None


def host_of(url: str | None) -> str:
    try:
        return (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return ""


def classify(utm: dict | None, referrer: str | None, own_hosts: tuple[str, ...] = ()) -> tuple[str, str]:
    """(source, medium) for a visit or a lead, e.g. ('yandex', 'organic'), ('google', 'cpc'), ('(direct)', '(none)')."""
    utm = utm or {}
    if utm.get("source"):
        return utm["source"].lower()[:60], (utm.get("medium") or "(not set)").lower()[:60]
    if utm.get("yclid"):
        return "yandex", "cpc"
    if utm.get("gclid"):
        return "google", "cpc"
    host = host_of(referrer)
    if not host or any(host == h or host.endswith("." + h) for h in own_hosts):
        return "(direct)", "(none)"
    search = _brand(host) or next((n for d, n in _SEARCH_DOMAINS.items() if _on(host, d)), None)
    if search:
        # ad clicks without click ids still carry a marker in the referrer
        q = parse_qs(urlsplit(referrer or "").query)
        return search, "cpc" if host.startswith("yabs.") or "adurl" in q else "organic"
    social = next((n for d, n in _SOCIAL_DOMAINS.items() if _on(host, d)), None)
    if social:
        return social, "social"
    return host[:60], "referral"
