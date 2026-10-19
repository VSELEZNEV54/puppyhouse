"""FastAPI application: `uvicorn app.main:app --no-access-log` (see Dockerfile / docker-compose.yml)."""
from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from . import errors
from .api import admin, public
from .config import BACKEND_DIR, get_settings

log = logging.getLogger("dsh.http")
API = "/api/v1"
ADMIN_UI = "/admin"  # the panel (backend/admin_ui): static files on the same origin, data from API + "/admin"
# Only own files: no inline scripts or styles, no third-party hosts; the favicon is a data: URI.
ADMIN_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; "
             "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


class Guard(BaseHTTPMiddleware):
    """Body size limit, CORS per area (public / admin), security headers, an access log without query strings
    (searches carry phone numbers) and without client IPs."""

    async def dispatch(self, request: Request, call_next):
        s = get_settings()
        t0 = time.perf_counter()
        path = request.url.path
        origin = request.headers.get("origin")
        allowed = s.admin_cors_origins if path.startswith(API + "/admin") else s.cors_origins
        cors = origin if origin and origin in allowed else None

        if request.method == "OPTIONS" and request.headers.get("access-control-request-method"):
            if not cors:
                return Response(status_code=403)
            resp = Response(status_code=204)
            resp.headers.update({
                "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, If-Match, X-Actor",
                "Access-Control-Max-Age": "600",
            })
        else:
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > max(s.max_body_bytes, 4096) * 4:
                resp = JSONResponse(errors.body("too_large", "Слишком большой запрос"), status_code=413)
            else:
                resp = await call_next(request)
        if cors:
            resp.headers["Access-Control-Allow-Origin"] = cors
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Expose-Headers"] = "Content-Disposition"
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Cache-Control", "no-store")
        if path == ADMIN_UI or path.startswith(ADMIN_UI + "/"):
            resp.headers["Content-Security-Policy"] = ADMIN_CSP
            resp.headers["X-Robots-Tag"] = "noindex, nofollow"
            resp.headers["X-Frame-Options"] = "DENY"
        elif not path.startswith(API + "/docs"):
            resp.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        log.info("%s %s %s %.0fms", request.method, path, resp.status_code, (time.perf_counter() - t0) * 1000)
        return resp


def create_app() -> FastAPI:
    s = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    docs = s.docs_enabled
    app = FastAPI(
        title="домщенков.рф API",
        version="1.0.0",
        description=(
            "Заявки, контакты и события сайта домщенков.рф. Публичная часть — для форм сайта; "
            "/admin — для внутренней админ-панели (Bearer-токен). Ошибки: "
            '{"error": {"code", "message", "fields": {<поле>: <текст>}}}.'),
        docs_url=f"{API}/docs" if docs else None,
        redoc_url=None,
        openapi_url=f"{API}/openapi.json" if docs else None,
    )
    errors.install(app)
    app.add_middleware(Guard)
    app.include_router(public.router, prefix=API)
    app.include_router(admin.router, prefix=API)
    app.mount(ADMIN_UI, StaticFiles(directory=BACKEND_DIR / "admin_ui", html=True), name="admin-ui")
    _document_public_bodies(app)
    return app


def _document_public_bodies(app: FastAPI) -> None:
    """The public endpoints read their body by hand (Content-Type and Origin are checked first), so FastAPI cannot
    see the models: add them to the OpenAPI schema explicitly."""
    from fastapi.openapi.utils import get_openapi

    from .schemas_public import EventsIn, LeadIn, ReviewIn
    bodies = {f"{API}/leads": (LeadIn, "application/json"), f"{API}/reviews": (ReviewIn, "application/json"),
              f"{API}/events": (EventsIn, "text/plain")}

    def openapi():
        if app.openapi_schema:
            return app.openapi_schema
        spec = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
        comps = spec.setdefault("components", {}).setdefault("schemas", {})
        for path, (model, ctype) in bodies.items():
            schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
            comps.update(schema.pop("$defs", {}))
            comps[model.__name__] = schema
            ref = {"$ref": f"#/components/schemas/{model.__name__}"}
            content = {ctype: {"schema": ref}}
            if ctype == "text/plain":  # sendBeacon sends JSON as text/plain; application/json works too
                content["application/json"] = {"schema": ref}
            spec["paths"][path]["post"]["requestBody"] = {"required": True, "content": content}
        app.openapi_schema = spec
        return spec

    app.openapi = openapi


app = create_app()
