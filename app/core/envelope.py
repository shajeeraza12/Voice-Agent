"""Consistent JSON envelope: {"data": ..., "error": null} or {"data": null, "error": {...}}.

Exception handlers live here so every route, including FastAPI's own request
validation, answers in the same shape with the right status code.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError, field_errors
from app.core.logging import log_event


def ok(data, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"data": jsonable_encoder(data), "error": None})


def fail(status_code: int, code: str, message: str, fields: list[dict] | None = None) -> JSONResponse:
    error = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    return JSONResponse(status_code=status_code, content={"data": None, "error": error})


def _is_malformed_body(exc: RequestValidationError) -> bool:
    return any(e.get("type") in ("json_invalid", "model_attributes_type", "dict_type") for e in exc.errors())


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return fail(exc.status_code, exc.code, exc.message)

    @app.exception_handler(ValidationError)
    async def _validation_error(_: Request, exc: ValidationError):
        fields = field_errors(exc)
        return fail(422, "validation_error", "One or more fields are invalid.", fields)

    @app.exception_handler(RequestValidationError)
    async def _request_validation_error(_: Request, exc: RequestValidationError):
        # Malformed JSON or a non-object body is a 400 (bad request), not a field problem.
        if _is_malformed_body(exc):
            return fail(400, "bad_request", "Request body must be a valid JSON object.")
        fields = []
        for e in exc.errors():
            loc = [str(p) for p in e.get("loc", ()) if p not in ("body", "query", "path")]
            fields.append({"field": loc[0] if loc else "request", "message": e.get("msg", "is not valid")})
        return fail(422, "validation_error", "One or more fields are invalid.", fields)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized"}.get(exc.status_code, "error")
        return fail(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log_event("unhandled_error", level=logging.ERROR, path=request.url.path, error=repr(exc))
        return fail(500, "internal_error", "Something went wrong on our side. Please try again.")
