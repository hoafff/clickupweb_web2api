#!/usr/bin/env python3
"""Send one UTF-8 JSON request to the authorized LOCAL ClickUp Brain gateway.

Cross-platform alternative to the PowerShell .ps1 script: does not depend on
Windows PowerShell execution policies or string body encodings.

Only connects to 127.0.0.1. Reads an app-issued gateway key from the ignored
.local/gateway.key; never prints the key, prompt, raw HTTP body or identifiers.

Run while local_gateway.py is listening in another terminal:
  python tools/send_gateway_request.py --prompt "Reply with ALPHA only."
  python tools/send_gateway_request.py --diagnostics
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sys
import urllib.error
import urllib.request
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEY_FILE = PROJECT_ROOT / ".local" / "gateway.key"
DEFAULT_SESSION_FILE = PROJECT_ROOT / ".local" / "browser-owner.key"
DEFAULT_PROMPT = "Reply with exactly one word: OK"
MODEL_ID = "clickup-ui-current"
MAX_PROMPT_CHARS = 8_000
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

DIAGNOSTIC_FIELDS = (
    "completed_replies",
    "same_conversation_pairs",
    "different_conversation_pairs",
    "last_relation",
)
RELATION_VALUES = {"first", "same", "different", "unknown", "unobserved"}
# Only safe aggregate integer counters from the Gateway. Optional for
# backwards compatibility with pre-HTTP-counter Gateway processes.
HTTP_DIAGNOSTIC_FIELDS = (
    "http_chat_received",
    "http_chat_2xx",
    "http_chat_401",
    "http_chat_other_errors",
    "http_chat_422",
    "http_chat_429",
    "http_chat_502",
    "http_chat_503",
)


class LocalClientError(Exception):
    """Safe message: never include credentials, user prompts or response body."""


def load_key(path: Path) -> str:
    try:
        key = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise LocalClientError(
            "Gateway key file missing/unreadable. Check .local/gateway.key."
        ) from exc
    if len(key) < 24 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise LocalClientError("Gateway key file does not contain a valid local API key.")
    return key


def load_session_token(path: Path) -> str:
    token = load_key(path)
    if len(token) < 32:
        raise LocalClientError("Browser owner session token has invalid length.")
    return token


def write_session_token_once(path: Path, token: str) -> None:
    if len(token) < 32 or not token.isascii():
        raise LocalClientError("Gateway returned an invalid owner token.")
    if path.resolve().parent != (PROJECT_ROOT / ".local").resolve():
        raise LocalClientError("Owner session token must stay in repository .local directory.")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise LocalClientError(
            "Owner token file exists. Do not replace it without restarting the gateway."
        ) from exc
    except OSError as exc:
        raise LocalClientError("Unable to create local owner token file.") from exc
    try:
        with os.fdopen(fd, "w", encoding="ascii") as file:
            file.write(token + "\n")
    except OSError as exc:
        raise LocalClientError("Unable to write local owner token file.") from exc


def encode_request(prompt: str) -> bytes:
    if not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        raise LocalClientError("Prompt must contain 1..8000 non-blank characters.")
    body = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    return json.dumps(
        body, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def request_json(
    *,
    port: int,
    key: str,
    path: str,
    body: bytes | None = None,
    timeout: float = 180.0,
    session_token: str | None = None,
) -> dict[str, Any]:
    if not 1024 <= port <= 65535:
        raise LocalClientError("Port must be 1024..65535.")
    if not 1 <= timeout <= 600:
        raise LocalClientError("Timeout must be between 1 and 600 seconds.")
    if path not in {
        "/v1/chat/completions", "/v1/session/diagnostics", "/v1/session/claim",
    }:
        raise LocalClientError("Unsupported gateway path.")
    if body is not None and path != "/v1/chat/completions":
        raise LocalClientError("Unexpected body for a session operation.")
    if body is None and path == "/v1/chat/completions":
        raise LocalClientError("A JSON request body is required.")

    url = f"http://127.0.0.1:{port}{path}"
    headers = {"Authorization": f"Bearer {key}"}
    if body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if session_token is not None:
        if path == "/v1/session/claim":
            raise LocalClientError("Cannot pass owner token when claiming a session.")
        headers["X-ClickUp-Session"] = session_token

    request = urllib.request.Request(
        url, data=body, headers=headers,
        method="POST" if body is not None or path == "/v1/session/claim" else "GET",
    )
    # Never allow HTTP_PROXY/HTTPS_PROXY to redirect loopback traffic.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        # Server validation errors can echo private input. Never dump body.
        raise LocalClientError(f"Gateway returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
        raise LocalClientError(
            "Unable to reach the local gateway. Check PowerShell 1 and its browser."
        ) from exc

    if len(data) > MAX_RESPONSE_BYTES:
        raise LocalClientError("Gateway returned an unexpectedly large response.")
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalClientError("Gateway returned invalid UTF-8 JSON.") from exc
    if not isinstance(parsed, dict):
        raise LocalClientError("Gateway response must be a JSON object.")
    return parsed


def get_answer(data: dict[str, Any]) -> str:
    try:
        answer = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LocalClientError("Gateway response did not include an assistant message.") from exc
    if not isinstance(answer, str):
        raise LocalClientError("Gateway response contained an invalid assistant message.")
    return answer


def safe_diagnostics(data: dict[str, Any]) -> dict[str, int | str]:
    """Whitelist fields so accidental server additions cannot leak IDs."""
    out: dict[str, int | str] = {}
    for field in DIAGNOSTIC_FIELDS[:-1]:
        value = data.get(field)
        if type(value) is not int or value < 0:
            raise LocalClientError("Gateway returned invalid session diagnostics.")
        out[field] = value
    relation = data.get("last_relation")
    if relation not in RELATION_VALUES:
        raise LocalClientError("Gateway returned invalid conversation relation.")
    out["last_relation"] = relation
    # Previously dropped by the CLI despite being exposed by the Gateway.
    # Keep strict numeric validation so no user data/opaque identifiers pass
    # through even if the server sends extra unexpected fields.
    for field in HTTP_DIAGNOSTIC_FIELDS:
        if field in data:
            number = data[field]
            if type(number) is not int or number < 0:
                raise LocalClientError("Gateway returned invalid HTTP counters.")
            out[field] = number
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--prompt", help="One user message; never logged by client")
    group.add_argument("--diagnostics", action="store_true", help="Print safe session comparison")
    group.add_argument(
        "--claim-session", action="store_true",
        help="Claim one exclusive browser owner token (strict gateway only)",
    )
    parser.add_argument("--key-file", type=Path, default=DEFAULT_KEY_FILE)
    parser.add_argument(
        "--session-file", type=Path, default=None,
        help="Secret owner token file (recommended: .local/browser-owner.key)",
    )
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args(argv)
    try:
        key = load_key(args.key_file)
        if args.claim_session:
            target = args.session_file or DEFAULT_SESSION_FILE
            if target.exists():
                raise LocalClientError(
                    "Owner token file already exists; don't reclaim until gateway restart."
                )
            response = request_json(
                port=args.port, key=key, path="/v1/session/claim",
                timeout=args.timeout,
            )
            token = response.get("session_token")
            if not isinstance(token, str):
                raise LocalClientError("Gateway did not return a valid owner token.")
            write_session_token_once(target, token)
            print("Claimed one exclusive browser API session (token stored privately).")
            return 0
        session_token = None
        if args.session_file is not None:
            session_token = load_session_token(args.session_file)
        elif DEFAULT_SESSION_FILE.exists():
            session_token = load_session_token(DEFAULT_SESSION_FILE)
        if args.diagnostics:
            result = request_json(
                port=args.port, key=key, path="/v1/session/diagnostics",
                timeout=args.timeout, session_token=session_token,
            )
            print(json.dumps(safe_diagnostics(result), indent=2))
        else:
            prompt = args.prompt if args.prompt is not None else DEFAULT_PROMPT
            result = request_json(
                port=args.port, key=key, path="/v1/chat/completions",
                body=encode_request(prompt), timeout=args.timeout,
                session_token=session_token,
            )
            print(get_answer(result))
    except LocalClientError as exc:
        print(f"Local gateway client: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
