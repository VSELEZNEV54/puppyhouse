"""Where a visit came from: UTM tags first, then ad click ids, then the referrer host, else direct.

Most visits to a kennel site come from Yandex / Google search or are direct, without UTM tags, so the referrer has to
be classified on the server."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

UTM_KEYS = ("source", "medium", "campaign", "content", "term")

_SEARCH = {"yandex": "yandex", "ya.ru": "yandex", "google": "google", "bing": "bing", "go.mail.ru": "mail.ru",
           "duckduckgo": "duckduckgo", "rambler": "rambler"}
_SOCIAL = {"vk.com": "vk", "vk.ru": "vk", "ok.ru": "ok", "t.me": "telegram", "telegram": "telegram",
           "instagram": "instagram", "facebook": "facebook", "youtube": "youtube", "youtu.be": "youtube",
           "dzen.ru": "dzen", "pinterest": "pinterest", "tiktok": "tiktok", "avito": "avito", "whatsapp": "whatsapp"}


def clean_utm(utm: dict | None) -> dict | None:
    """Keep only the five utm_* keys (without the prefix), trimmed; None if nothing is left."""
    if not utm:
        return None
    out = {}
    for k in UTM_KEYS:
        v = utm.get(k) or utm.get("utm_" + k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()[:150]
    for k in ("yclid", "gclid"):
        v = utm.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()[:150]
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
    for needle, name in _SEARCH.items():
        if needle in host:
            # ad clicks without click ids still carry a marker in the referrer query
            q = parse_qs(urlsplit(referrer or "").query)
            return name, "cpc" if "yabs" in host or "adurl" in q else "organic"
    for needle, name in _SOCIAL.items():
        if needle in host:
            return name, "social"
    return host[:60], "referral"
