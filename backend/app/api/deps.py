"""Shared request dependencies: DB session, client IP, request gating for public POSTs, admin auth."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from urllib.parse import unquote, urlsplit

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..enums import Role
from ..errors import ApiError
from ..models import AdminToken, AdminUser
from ..services import auth
from ..services.leads import RequestCtx
from ..services.sanitize import clean
from ..services.security import client_ip

Db = Annotated[Session, Depends(get_db)]


def ip_of(request: Request) -> str | None:
    s = get_settings()
    return client_ip(request, s.is_trusted_proxy)


def _origin_ok(request: Request) -> tuple[bool, bool]:
    """(allowed, missing). A present Origin must be our own host or listed in allowed_origins / cors_origins."""
    s = get_settings()
    origin = request.headers.get("origin")
    if not origin or origin == "null":
        return True, True
    if urlsplit(origin).netloc.lower() == request.headers.get("host", "").lower():
        return True, False  # same host (behind nginx the scheme seen here is http, so compare hosts only)
    return origin in set(s.allowed_origins) | set(s.cors_origins), False


def public_ctx(request: Request, json_only: bool = True) -> RequestCtx:
    if json_only:
        ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            raise ApiError(415, "unsupported_media_type", "Нужен JSON (Content-Type: application/json)")
    ok, missing = _origin_ok(request)
    if not ok:
        raise ApiError(403, "forbidden_origin", "Запрос с чужого сайта")
    return RequestCtx(ip=ip_of(request), user_agent=request.headers.get("user-agent"), origin_missing=missing)


def public_json(request: Request) -> RequestCtx:
    return public_ctx(request, json_only=True)


def decode_actor(raw: str | None) -> str | None:
    """X-Actor carries the panel user's name as percent-encoded UTF-8 («%D0%9C%D0%B0%D1%80%D0%B8%D1%8F» = Мария),
    because HTTP clients refuse raw non-ASCII header values. Raw UTF-8 bytes (decoded by the server as latin-1) are
    accepted too."""
    if not raw:
        return None
    s = unquote(raw.strip())
    try:
        s = s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return clean(s, 60)


@dataclass
class Actor:
    user: AdminUser
    token: AdminToken
    label: str          # what lead_history shows: the person, or «API-ключ: X (от имени Анна)»
    ip: str | None


def current_actor(request: Request, db: Db, authorization: Annotated[str | None, Header()] = None,
                  x_actor: Annotated[str | None, Header()] = None) -> Actor:
    """Bearer token from a login (manager) or an API key (the admin panel's backend). Never from the query string.
    With an API key, X-Actor names the person working in the panel; it goes to the history as a label."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "unauthorized", "Нужна авторизация", extra={"hint": "Authorization: Bearer <token>"})
    user, token = auth.authenticate(db, authorization[7:].strip())
    label = user.name
    if token.kind == "api_key":
        label = f"{token.label or user.name}"
        name = decode_actor(x_actor)
        if name:
            label = f"{name} ({label})"
    return Actor(user=user, token=token, label=label, ip=ip_of(request))


CurrentActor = Annotated[Actor, Depends(current_actor)]


def admin_only(actor: CurrentActor) -> Actor:
    if actor.user.role != Role.admin.value:
        raise ApiError(403, "forbidden", "Нужна роль администратора")
    return actor


AdminActor = Annotated[Actor, Depends(admin_only)]
