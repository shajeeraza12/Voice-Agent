"""Optional API key for the REST API. Off unless API_KEY is set, so reviewers can query freely."""
from fastapi import Header

from app.core.errors import AppError
from app.settings import settings


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise Unauthorized("Missing or invalid X-API-Key header.")
