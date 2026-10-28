"""Vapi webhook adapter. Domain-free.

Translates Vapi server messages into calls to the core tool dispatcher and call log,
and formats the replies Vapi expects. Always answers HTTP 200 to tool calls, even on
failure, because Vapi reads errors from the body; a non-200 can leave the caller in silence.
"""
import hmac
import logging

from fastapi import APIRouter, Body, Header

from app.channels.vapi import payloads
from app.core.calls import CallStatus, finish_call, record_call_safely
from app.core.errors import AppError
from app.core.logging import log_event
from app.core.tools import ToolContext, dispatch
from app.settings import settings

router = APIRouter(prefix="/channels/vapi", tags=["vapi"])


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


def _check_secret(authorization: str | None, x_vapi_secret: str | None) -> None:
    expected = settings.vapi_webhook_secret
    if not expected:
        return  # local development only; README says to always set it in production
    supplied = x_vapi_secret or ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:]
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        log_event("vapi_auth_failed", level=logging.WARNING)
        raise Unauthorized("Invalid webhook credentials.")


@router.post("/webhook")
def webhook(
    body: dict = Body(...),
    authorization: str | None = Header(default=None),
    x_vapi_secret: str | None = Header(default=None),
):
    # Sync handler on purpose: FastAPI runs it in a thread pool, so blocking database work
    # in tools doesn't stall other concurrent calls.
    _check_secret(authorization, x_vapi_secret)
    message = body.get("message") or {}
    kind = payloads.message_type(message)
    cid = payloads.call_id(message)
    caller = payloads.caller_number(message)

    if kind == "tool-calls":
        ctx = ToolContext(call_id=cid, caller_number=caller)
        results = []
        for call in payloads.tool_calls(message):
            outcome = dispatch(call.name, call.arguments, ctx)
            results.append({"name": call.name, "toolCallId": call.id, "result": outcome.message})
        return {"results": results}

    if kind == "status-update" and message.get("status") == "in-progress" and cid:
        record_call_safely(cid, caller_number=caller, status=CallStatus.IN_PROGRESS)
        log_event("call_started", call_id=cid, caller=caller)
        return {}

    if kind == "end-of-call-report" and cid:
        info = payloads.end_of_call(message)
        finish_call(cid, caller_number=caller, **info)
        log_event("call_ended", call_id=cid, ended_reason=info["ended_reason"], summary=info["summary"])
        return {}

    # Other message types (transcript, speech-update, conversation-update, hang...) need no reply.
    return {}
