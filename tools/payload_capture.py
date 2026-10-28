"""Opt-in content capture for authorized local browser research.

This module parses *text JSON* from HTTP request/response and WebSocket frames.
It does not serialize cookies, HTTP headers, binary media or HAR archives.

All content is LOCAL and potentially sensitive even after key-based redaction.
Keep private traces in ignored artifacts/. Never publish without manual review.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

MAX_TEXT_FIELD = 16_384
REDACTED = "<redacted>"
TOKEN_KEY = re.compile(
    r"(?:^|[_\-])(?:"
    r"authorization|cookie|set_cookie|access_token|refresh_token|id_token|"
    r"token|csrf|xsrf|session_token|session_key|secret|password|passwd|"
    r"credential|private_key|api_key|jwt|bearer|auth_header|headers"
    r")(?:$|[_\-])",
    re.IGNORECASE,
)
BEARER = re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9+/._~=-]{8,}", re.IGNORECASE)
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
API_KEY = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{16,})\b")
SECRETS_IN_TEXT = re.compile(
    r"(?i)(\b(?:access_token|refresh_token|id_token|api_key|csrf|xsrf|password|"
    r"authorization)\s*[:=]\s*)([^\s&,;\"']{6,})"
)
URL_KEY = re.compile(r"^(?:url|uri|href|link|redirect_uri|asset_url|image_url)$", re.IGNORECASE)


def safe_url(value: str) -> str:
    """Remove URL query/fragment/userinfo, mask long/opaque path IDs."""
    try:
        p = urlsplit(value)
        if p.scheme not in {"https", "http", "wss", "ws"} or not p.hostname:
            return REDACTED
        path = "/".join(
            ("{id}" if (len(part) >= 10 and any(c.isdigit() for c in part)
                        and any(c.isalpha() for c in part))
             else "{id}" if len(part) >= 6 and part.isdigit()
             else "{token}" if len(part) >= 24
             else part)
            for part in p.path.split("/")
        )
        return urlunsplit((p.scheme, p.hostname, path, "", ""))
    except (ValueError, TypeError):
        return REDACTED


def redact_string(value: str) -> str:
    if len(value) > MAX_TEXT_FIELD:
        value = value[:MAX_TEXT_FIELD] + "...<truncated>"
    value = BEARER.sub("<redacted-authorization>", value)
    value = JWT.sub("<redacted-jwt>", value)
    value = API_KEY.sub("<redacted-api-key>", value)
    value = SECRETS_IN_TEXT.sub(lambda match: match.group(1) + REDACTED, value)
    return value


def redact_payload(value: Any, *, depth: int = 0) -> Any:
    """Preserve model/effort/prompt fields while masking conventional secrets.

    This is best-effort, not a security boundary. Users must review traces.
    """
    if depth > 24:
        return "<max-depth-exceeded>"
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in list(value.items())[:2_000]:
            name = str(key)
            if TOKEN_KEY.search(name):
                output[name] = REDACTED
            elif URL_KEY.fullmatch(name) and isinstance(item, str):
                output[name] = safe_url(item)
            else:
                output[name] = redact_payload(item, depth=depth + 1)
        return output
    if isinstance(value, list):
        return [redact_payload(x, depth=depth + 1) for x in value[:2_000]]
    if isinstance(value, str):
        return redact_string(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return "<unsupported-type>"


def _json_or_socketio(text: str) -> Any:
    """Parse JSON, including common Socket.IO numeric-prefixed JSON messages."""
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        # Socket.IO application packet, e.g. 42["event",{...}]
        match = re.match(r"^[0-9]{1,4}([\[{].*)$", text, flags=re.DOTALL)
        if match is not None:
            try:
                return json.loads(match.group(1))
            except (ValueError, TypeError):
                pass
    raise ValueError("not a recognized JSON frame")


def parse_content(
    content: str | bytes | None, *,
    content_type: str = "",
    max_bytes: int = 196_608,
) -> dict[str, Any]:
    """Return structured, sanitized capture or a reason it was skipped."""
    if content is None:
        return {"format": "empty"}
    if isinstance(content, bytes):
        length = len(content)
        if length > max_bytes:
            return {"format": "skipped", "reason": "too_large", "bytes": length}
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            return {"format": "skipped", "reason": "non_utf8", "bytes": length}
    else:
        text = content
        length = len(text.encode("utf-8", errors="replace"))
        if length > max_bytes:
            return {"format": "skipped", "reason": "too_large", "bytes": length}

    if not text:
        return {"format": "empty"}

    kind = (content_type or "").split(";")[0].strip().lower()
    if kind == "text/event-stream":
        events = []
        for block in re.split(r"\r?\n\r?\n", text):
            data = "\n".join(
                line[5:].lstrip(" ") for line in block.splitlines()
                if line.startswith("data:")
            )
            if not data:
                continue
            if data == "[DONE]":
                events.append({"done": True})
            else:
                try:
                    events.append(redact_payload(_json_or_socketio(data)))
                except ValueError:
                    events.append({"unparsed_data_length": len(data)})
        return {"format": "sse_json", "events": events[:400], "bytes": length}

    try:
        parsed = _json_or_socketio(text)
    except ValueError:
        return {"format": "skipped", "reason": "not_json", "bytes": length}
    return {"format": "json", "data": redact_payload(parsed), "bytes": length}


def allows_http_body(content_type: str) -> bool:
    """Skip binary/static assets and HTML, collect JSON/SSE only."""
    kind = (content_type or "").split(";")[0].strip().lower()
    return (
        kind == "application/json"
        or kind.endswith("+json")
        or kind == "text/event-stream"
        or kind in {"text/plain", "application/graphql-response+json"}
    )
