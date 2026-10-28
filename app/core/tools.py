"""Tool dispatcher. Domain-free.

The voice platform asks us to run a tool by name. This module finds it, runs it,
and guarantees a short plain-language string comes back, whatever happens.
An exception must never reach the voice platform, because that means silence
on the phone.

Tool results are read by the LLM, not spoken verbatim, so they combine a status
word the prompt can rely on (SAVED, NOT_SAVED, ERROR...) with a sentence the
agent can repeat to the caller.
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.calls import CallStatus, record_call_safely
from app.core.errors import AppError, field_errors, speakable
from app.core.logging import log_event


@dataclass
class ToolContext:
    call_id: str | None = None
    caller_number: str | None = None
    domain: str | None = None


@dataclass
class ToolResult:
    message: str
    ok: bool = True
    # Set by save tools: the payload the caller confirmed, and the record it produced.
    payload: dict | None = None
    record_id: str | None = None
    saved: bool = False
    extra: dict = field(default_factory=dict)


ToolFn = Callable[[dict, ToolContext], ToolResult]

_TOOLS: dict[str, tuple[str, ToolFn]] = {}

SYSTEM_ERROR_MESSAGE = (
    "ERROR: The system is temporarily unavailable and nothing was saved. "
    "Apologise to the caller, tell them their registration could not be saved right now, "
    "and ask them to call back a little later. Do not say it was saved."
)


def register_tool(domain: str, name: str, fn: ToolFn) -> None:
    _TOOLS[name] = (domain, fn)


def registered_tools() -> list[str]:
    return sorted(_TOOLS)


def dispatch(name: str, args: dict[str, Any] | None, ctx: ToolContext) -> ToolResult:
    args = args or {}
    entry = _TOOLS.get(name)
    if entry is None:
        log_event("tool_unknown", level=logging.WARNING, tool=name, call_id=ctx.call_id)
        return ToolResult(f"ERROR: unknown tool '{name}'. Continue the conversation without it.", ok=False)

    domain, fn = entry
    ctx.domain = ctx.domain or domain
    log_event("tool_call", tool=name, call_id=ctx.call_id, args=args)

    try:
        result = fn(args, ctx)
    except ValidationError as exc:
        errors = field_errors(exc)
        result = ToolResult(
            "INVALID_FIELDS: " + ", ".join(e["field"] for e in errors) + ". Nothing was saved. "
            f"Tell the caller {speakable(errors)}, and ask again for only that information.",
            ok=False,
            extra={"fields": errors},
        )
    except AppError as exc:
        result = ToolResult(f"NOT_DONE: {exc.message}", ok=False)
    except SQLAlchemyError as exc:
        log_event("tool_db_error", level=logging.ERROR, tool=name, call_id=ctx.call_id, error=repr(exc), payload=args)
        result = ToolResult(SYSTEM_ERROR_MESSAGE, ok=False, payload=args)
        record_call_safely(ctx.call_id, domain=ctx.domain, caller_number=ctx.caller_number,
                           final_payload=args, status=CallStatus.SAVE_FAILED)
    except Exception as exc:  # last line of defence: never let the call go silent
        log_event("tool_crash", level=logging.ERROR, tool=name, call_id=ctx.call_id, error=repr(exc), payload=args)
        result = ToolResult(SYSTEM_ERROR_MESSAGE, ok=False, payload=args)

    if result.saved:
        # The final payload goes to stdout as well as the calls table, so it survives a database outage.
        log_event("final_payload", tool=name, call_id=ctx.call_id, record_id=result.record_id, payload=result.payload)
        record_call_safely(ctx.call_id, domain=ctx.domain, caller_number=ctx.caller_number,
                           final_payload=result.payload, record_id=result.record_id, status=CallStatus.SAVED)

    log_event("tool_result", tool=name, call_id=ctx.call_id, ok=result.ok, message=result.message)
    return result
