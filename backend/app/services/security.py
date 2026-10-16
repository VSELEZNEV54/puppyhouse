"""Passwords (scrypt, stdlib), opaque bearer tokens (only SHA-256 stored), HMAC for webhooks, client IP."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import secrets

from starlette.requests import Request

_N, _R, _P = 2**15, 8, 1
_MAXMEM = 64 * 1024 * 1024


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32, maxmem=_MAXMEM)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(base64.b64decode(dk)), maxmem=_MAXMEM)
        return hmac.compare_digest(got, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


# A real hash to compare against when the login does not exist: same timing as a wrong password.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def new_token(prefix: str = "dsh") -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def client_ip(request: Request, is_trusted) -> str | None:
    """The browser's IP. X-Real-IP is believed only when the direct peer is a trusted proxy (nginx sets it to
    $remote_addr, overwriting whatever the browser sent); otherwise anyone could pick an IP."""
    peer = request.client.host if request.client else None
    if peer and is_trusted(peer):
        real = (request.headers.get("x-real-ip") or "").strip()
        if real:
            peer = real
    try:
        if not peer:
            return None
        addr = ipaddress.ip_address(peer)
        if addr.version == 6 and addr.ipv4_mapped:  # ::ffff:1.2.3.4 on a dual-stack listener
            addr = addr.ipv4_mapped
        return str(addr)
    except ValueError:
        return None


def rate_key(ip: str | None) -> str | None:
    """IPv6 addresses are grouped by /64 (one home or phone gets a whole /64)."""
    if not ip:
        return None
    addr = ipaddress.ip_address(ip)
    if addr.version == 6 and addr.ipv4_mapped:
        return str(addr.ipv4_mapped)
    if addr.version == 6:
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


def same_client(column, ip: str | None):
    """SQL condition «this row came from the same client»: the exact IPv4, or the same IPv6 /64."""
    from sqlalchemy import cast
    from sqlalchemy.dialects.postgresql import CIDR
    key = rate_key(ip)
    if key and "/" in key:
        return column.op("<<=")(cast(key, CIDR))
    return column == key
