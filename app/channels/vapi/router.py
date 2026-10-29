"""Vapi webhook adapter. Domain-free.

Translates Vapi server messages into calls to the core tool dispatcher and call log,
and formats the replies Vapi expects. Always answers HTTP 200 to tool calls, even on
failure, because Vapi reads errors from the body; a non-200 can leave the caller in silence.
"""
import hmac
import logging

from fastapi import APIRouter, Body, Request

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


def _matches(candidate: str | None, expected: str) -> bool:
    return bool(candidate) and hmac.compare_digest(candidate.strip().encode(), expected.encode())


def _check_secret(request: Request, message_kind: str) -> None:
    """Accept the request if any supported header carries the shared secret:
    - 'Authorization: Bearer <secret>'  Vapi Bearer credential. Vapi attaches it to tool calls.
    - 'X-Webhook-Token: <secret>'       custom header set in the assistant's server.headers.
      Needed because Vapi sends assistant-level messages (status-update, end-of-call-report)
      without the credential, only an empty X-Vapi-Secret header (seen in production logs).
    - 'X-Vapi-Secret: <secret>'         legacy inline secret."""
    expected = settings.vapi_webhook_secret
    if not expected:
        return  # local development only; README says to always set it in production
    authorization = request.headers.get("authorization") or ""
    bearer = authorization[7:] if authorization.lower().startswith("bearer ") else None
    x_vapi_secret = request.headers.get("x-vapi-secret")
    x_webhook_token = request.headers.get("x-webhook-token")
    if _matches(bearer, expected) or _matches(x_webhook_token, expected) or _matches(x_vapi_secret, expected):
        return
    # Diagnostics without leaking secrets: which headers arrived and how long the tokens were.
    log_event(
        "vapi_auth_failed", level=logging.WARNING,
        message_type=message_kind,
        auth_scheme=authorization.split(" ")[0] if authorization else None,
        bearer_len=len(bearer) if bearer else 0,
        x_vapi_secret_len=len(x_vapi_secret) if x_vapi_secret else 0,
        expected_len=len(expected),
        header_names=sorted(k for k in request.headers.keys() if k.lower() not in ("cookie",)),
    )
    raise Unauthorized("Invalid webhook credentials.")


@router.post("/webhook")
def webhook(request: Request, body: dict = Body(...)):
    # Sync handler on purpose: FastAPI runs it in a thread pool, so blocking database work
    # in tools doesn't stall other concurrent calls.
    message = body.get("message") or {}
    kind = payloads.message_type(message)
    _check_secret(request, kind)
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
