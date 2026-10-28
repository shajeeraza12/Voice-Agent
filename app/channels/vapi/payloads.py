"""Parsing Vapi server messages. Domain-free.

Vapi POSTs {"message": {...}} to our server URL. We read only the fields we need,
defensively, because Vapi has more than one shape for tool calls
(toolCallList and the older toolWithToolCallList) and arguments may arrive as an
object or as a JSON string.
"""
import json
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


def _get(d: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def message_type(message: dict) -> str:
    return str(message.get("type") or "")


def call_id(message: dict) -> str | None:
    return _get(message, "call", "id")


def caller_number(message: dict) -> str | None:
    return _get(message, "call", "customer", "number") or _get(message, "customer", "number")


def _parse_arguments(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def tool_calls(message: dict) -> list[ToolCall]:
    raw_calls = message.get("toolCallList")
    if not raw_calls:
        raw_calls = [item.get("toolCall") for item in message.get("toolWithToolCallList") or [] if item.get("toolCall")]
    calls = []
    for raw in raw_calls or []:
        fn = raw.get("function") or {}
        calls.append(ToolCall(
            id=str(raw.get("id", "")),
            name=str(fn.get("name") or raw.get("name") or ""),
            arguments=_parse_arguments(fn.get("arguments", raw.get("arguments"))),
        ))
    return calls


def end_of_call(message: dict) -> dict:
    return {
        "transcript": _get(message, "artifact", "transcript") or message.get("transcript"),
        "summary": _get(message, "analysis", "summary") or message.get("summary"),
        "ended_reason": message.get("endedReason"),
    }
