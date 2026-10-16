"""One error shape for every endpoint, public and admin:

    {"error": {"code": "validation", "message": "…", "fields": {"phone": "…", "consent": "…"}}}

`fields` keys are the HTML `name`s of the form inputs, so main.js shows each message under its field."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# Russian messages for the public form fields (same wording as main.js ERR)
FIELD_MESSAGES = {
    "name": "Напишите, как к вам обращаться",
    "phone": "Проверьте номер: после +7 нужно 10 цифр",
    "contact": "Выберите, куда вам написать",
    "consent": "Без согласия на обработку данных мы не сможем отправить заявку",
    "text": "Расскажите хотя бы пару предложений",
    "rating": "Поставьте оценку от 1 до 5",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, fields: dict[str, str] | None = None,
                 extra: dict | None = None):
        self.status, self.code, self.message, self.fields, self.extra = status, code, message, fields or {}, extra


def body(code: str, message: str, fields: dict | None = None, extra: dict | None = None) -> dict:
    err = {"code": code, "message": message, "fields": fields or {}}
    if extra:
        err.update(extra)
    return {"error": err}


def _field_of(loc: tuple) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
    return parts[0] if parts else "_"


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, e: ApiError):
        return JSONResponse(body(e.code, e.message, e.fields, e.extra), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        fields: dict[str, str] = {}
        for err in e.errors():
            f = _field_of(tuple(err.get("loc", ())))
            fields.setdefault(f, FIELD_MESSAGES.get(f) or err.get("msg", "Неверное значение"))
        return JSONResponse(body("validation", "Проверьте поля формы", fields), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
                409: "conflict", 413: "too_large", 429: "rate_limited"}.get(e.status_code, "error")
        msg = e.detail if isinstance(e.detail, str) else "Ошибка"
        return JSONResponse(body(code, msg), status_code=e.status_code, headers=getattr(e, "headers", None))
