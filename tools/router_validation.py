"""Privacy-safe FastAPI 422 diagnostics for the text-only Brain Gateway.

FastAPI's default RequestValidationError response can echo raw Pydantic
'input' values -- including very long agent system prompts and tool schemas.
Never return raw validation errors, exception messages, headers or payloads.
This module emits only static, bounded error codes and fixed descriptions.

Limits are enforced on the UI bridge by tools.router_compat, and do not
constitute an empirically measured maximum context length of ClickUp Brain.
"""
from __future__ import annotations

from typing import Any

REASON_OVERSIZE = "message_too_long"
REASON_TOOLS = "unsupported_tool_calling"
REASON_NON_TEXT = "unsupported_non_text_messages"
REASON_FORMAT = "incompatible_request_format"
REASON_OTHER = "invalid_request"

REASON_CODES = (
    REASON_OVERSIZE, REASON_TOOLS, REASON_NON_TEXT, REASON_FORMAT,
    REASON_OTHER,
)
ALLOWED_FEATURE_FIELDS = frozenset({
    "tools", "tool_choice", "parallel_tool_calls", "functions",
    "function_call",
})
ALLOWED_FORMAT_FIELDS = frozenset({
    "response_format", "max_tokens", "max_completion_tokens", "temperature",
    "top_p", "stop", "seed", "n",
})
MAX_SAFE_ERRORS = 64

def _loc_tuple(item: dict[str, Any]) -> tuple[str, ...]:
    raw = item.get("loc")
    if not isinstance(raw, (list, tuple)):
        return ()
    # Never stringify untrusted loc values. Retain only known field names.
    return tuple(x for x in raw if isinstance(x, str) and x in (
        "body", "messages", "content", "role", "tools", "tool_choice",
        "parallel_tool_calls", "functions", "function_call",
        "response_format", "max_tokens", "max_completion_tokens",
        "temperature", "top_p", "stop", "seed", "n",
    ))


def reason_from_errors(errors: list[dict[str, Any]]) -> str:
    """Pick a bounded reason category; no raw user content goes to output."""
    seen: set[str] = set()
    for item in errors[:MAX_SAFE_ERRORS]:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        loc = _loc_tuple(item)
        if kind == "string_too_long" and "content" in loc:
            seen.add(REASON_OVERSIZE)
        if any(x in ALLOWED_FEATURE_FIELDS for x in loc):
            seen.add(REASON_TOOLS)
        if "content" in loc and kind in (
            "string_type", "list_type", "dict_type", "model_type",
        ):
            seen.add(REASON_NON_TEXT)
        if any(x in ALLOWED_FORMAT_FIELDS for x in loc):
            seen.add(REASON_FORMAT)

    for reason in (
        REASON_OVERSIZE, REASON_TOOLS, REASON_NON_TEXT, REASON_FORMAT,
    ):
        if reason in seen:
            return reason
    return REASON_OTHER


def safe_validation_body(reason: str) -> dict:
    """Use FastAPI-compatible detail shape, WITHOUT Pydantic 'input'."""
    if reason == REASON_OVERSIZE:
        return {
            "detail": [{
                "type": "string_too_long",
                "loc": ["body", "messages", "content"],
                "msg": (
                    "Gateway text-chat limit: each message content and "
                    "the compiled transcript must fit 8000 characters. "
                    "Coding-agent system prompts can exceed this limit."
                ),
            }],
            "error": {
                "type": "invalid_request_error", "code": REASON_OVERSIZE,
            },
        }
    messages = {
        REASON_TOOLS: (
            "This ClickUp browser Gateway is text-chat only. "
            "Native tools/tool_calls and coding-agent tool execution "
            "are NOT supported."
        ),
        REASON_NON_TEXT: (
            "This ClickUp browser Gateway accepts only text message content."
        ),
        REASON_FORMAT: (
            "An unsupported Chat Completions option was provided. "
            "Only the documented text-chat subset is available."
        ),
        REASON_OTHER: (
            "Request is incompatible with the local text-chat Gateway. "
            "Check message roles, final user turn, length and model ID."
        ),
    }
    return {
        "detail": [{
            "type": "unsupported_request" if reason != REASON_OTHER
            else "invalid_request",
            "loc": ["body"],
            "msg": messages.get(reason, messages[REASON_OTHER]),
        }],
        "error": {
            "type": "invalid_request_error",
            "code": reason if reason in REASON_CODES else REASON_OTHER,
        },
    }
