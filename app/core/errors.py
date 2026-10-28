"""Application errors and the translation of validation errors into plain words.

Domain validators raise ValueError with messages written to be spoken
("can't be in the future"). This module turns them into field-level errors for
the API and into one sentence the voice agent can say.
"""
from pydantic import ValidationError


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


def field_label(field: str) -> str:
    return field.replace("_", " ")


def _clean_message(msg: str) -> str:
    # Pydantic prefixes custom ValueError messages with "Value error, ".
    for prefix in ("Value error, ", "Assertion failed, "):
        if msg.startswith(prefix):
            msg = msg[len(prefix):]
    return msg


def field_errors(exc: ValidationError) -> list[dict]:
    """[{field, message}] with one entry per failing field."""
    out: list[dict] = []
    seen: set[str] = set()
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ()) if p not in ("body",)]
        field = loc[0] if loc else "request"
        if field in seen:
            continue
        seen.add(field)
        if err.get("type") == "missing":
            message = "is required"
        elif err.get("type") == "extra_forbidden":
            message = "is not a recognised field"
        else:
            message = _clean_message(err.get("msg", "is not valid"))
        out.append({"field": field, "message": message})
    return out


def speakable(errors: list[dict]) -> str:
    """One sentence the agent can read: 'the date of birth can't be in the future'."""
    parts = [f"the {field_label(e['field'])} {e['message']}" for e in errors]
    if len(parts) == 1:
        return parts[0]
    return "; ".join(parts[:-1]) + "; and " + parts[-1]
