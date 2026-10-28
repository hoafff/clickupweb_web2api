#!/usr/bin/env python3
"""Verify a LOCAL 9Router -> local ClickUp Brain gateway path.

Unlike check_router_compat.py (port 8787), this client calls 9Router on
127.0.0.1:20128 and exercises the configured custom-provider route.
No 9Router dashboard manipulation, credential export, or retry loops.
"""
from __future__ import annotations

import argparse
import getpass
import hmac
import json
import os
from pathlib import Path
import re
import socket
import sys
from typing import Any
import urllib.error
import urllib.request

if __package__ in (None, ""):
    _root = Path(__file__).resolve().parents[1]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from tools.prompt_limits import MAX_PROMPT_CHARS

ROOT = Path(__file__).resolve().parents[1]
KEY_FILE = ROOT / ".local" / "ninerouter.key"
GATEWAY_KEY_FILE = ROOT / ".local" / "gateway.key"
MODEL = "brain/clickup-ui-current"
ALLOWED_MODEL = re.compile(r"^[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+$")
MAX_BODY = 2_000_000
DEFAULT_TEST_PROMPT = "Reply with exactly OK."


class RouterPathError(Exception):
    """A safe error: never include a response body, key, or prompt."""


def classify_auth_error(status: int, raw: bytes) -> str:
    """Whitelist only known non-sensitive auth codes, never echo raw text."""
    if status != 401:
        return ""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return "Auth response body unrecognized"
    if not isinstance(data, dict):
        return "Auth response body unrecognized"
    nested = data.get("error")
    error = nested if isinstance(nested, dict) else data
    code = error.get("code")
    kind = error.get("type")
    message = error.get("message", error.get("detail"))
    # Fields in response bodies are untrusted! Only return static strings.
    if code == "invalid_api_key" or message == "Invalid API key":
        return (
            "invalid_api_key: likely 9Router client key rejected; "
            "verify local API key and running 9Router process"
        )
    if code in ("authentication_error", "unauthorized") or kind == "authentication_error":
        return (
            "authentication_error: determine whether 9Router or upstream "
            "returned 401 using Gateway HTTP counters"
        )
    if message in ("Unauthorized", "Not authenticated", "Invalid API key provided"):
        return "unauthorized: check 9Router client key and Gateway upstream key"
    return "Auth error shape not recognized; check redacted 9Router logs"


def read_key(key_path: Path) -> str | None:
    if not key_path.is_file():
        return None
    try:
        key = key_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise RouterPathError("Cannot read the locally stored 9Router key.") from exc
    if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise RouterPathError("Invalid 9Router key file.")
    return key


def reject_reused_upstream_key(
    client_key: str | None,
    gateway_key_path: Path = GATEWAY_KEY_FILE,
) -> None:
    """Prevent accidental reuse of the upstream Gateway key as 9Router client auth.

    9Router typically validates inbound keys against its own API Keys database.
    An imported custom-provider upstream key is not an issued client key.
    Never print, transmit or hash/store either credential in diagnostics.
    """
    if client_key is None:
        return
    try:
        upstream_key = gateway_key_path.read_text(encoding="ascii").strip()
    except (FileNotFoundError, OSError, UnicodeError):
        return
    if upstream_key and hmac.compare_digest(client_key, upstream_key):
        raise RouterPathError(
            "9Router client key equals the upstream ClickUp Gateway key. "
            "These are distinct authentication roles. Create a CLIENT key "
            "in the 9Router dashboard's API Keys/Endpoints section, then "
            "replace only .local/ninerouter.key. Keep .local/gateway.key "
            "unchanged. No HTTP chat request was sent."
        )


def save_key(key_path: Path) -> None:
    if key_path.resolve().parent != (ROOT / ".local").resolve():
        raise RouterPathError("For safety, the key can only be saved under .local/.")
    if key_path.exists():
        raise RouterPathError(
            "9Router key file already exists; it was not overwritten."
        )
    key = getpass.getpass("Paste 9Router CLIENT key (hidden): ").strip()
    if len(key) < 8 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise RouterPathError("Invalid 9Router key; nothing was saved.")
    key_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as writer:
            writer.write(key + "\n")
    except OSError as exc:
        raise RouterPathError("Could not save the 9Router key locally.") from exc
    print("9Router client key saved privately under .local/.")


def request_router(
    *, port: int, path: str, key: str | None,
    body: dict[str, Any] | None = None,
    timeout: float = 150,
) -> tuple[int, dict[str, str], str]:
    if not 1024 <= port <= 65535:
        raise RouterPathError("Port must be 1024..65535.")
    if path not in {"/v1/models", "/v1/chat/completions"}:
        raise RouterPathError("Unsupported local 9Router path.")
    if body is None and path != "/v1/models":
        raise RouterPathError("Missing chat request body.")
    if body is not None and path != "/v1/chat/completions":
        raise RouterPathError("Unexpected model-list request body.")
    headers = {
        "Accept": "text/event-stream" if body and body.get("stream") else "application/json",
    }
    if key is not None:
        headers["Authorization"] = "Bearer " + key
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
        payload = json.dumps(
            body, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=payload, headers=headers,
        method="POST" if body is not None else "GET",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as res:
            wire = res.read(MAX_BODY + 1)
            code = res.status
            response_headers = {
                name.lower(): value for name, value in res.headers.items()
            }
    except urllib.error.HTTPError as exc:
        # Read only a small bounded error body and discard raw content.
        # Print allowlisted, static classifications only; no API keys or
        # potentially sensitive messages can be echoed to the terminal.
        try:
            auth_class = classify_auth_error(exc.code, exc.read(8192))
        except (OSError, ValueError):
            auth_class = ""
        qualifier = (" " + auth_class) if auth_class else ""
        raise RouterPathError(
            f"9Router HTTP {exc.code}.{qualifier} "
            "Inspect router-side request logs and Gateway diagnostics."
        ) from exc
    except urllib.error.URLError as exc:
        # The request may have reached the UI before a client read timeout.
        # Do not retry an ambiguous send; classify without echoing exception
        # reason (which may contain a private URL or upstream details).
        if isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout)):
            raise RouterPathError(
                "9Router response timed out after request; the UI may already "
                "have submitted it. Inspect browser before any retry."
            ) from exc
        raise RouterPathError(
            "Cannot reach local 9Router. Check 127.0.0.1:20128 and its process."
        ) from exc
    except (OSError, TimeoutError) as exc:
        if isinstance(exc, (TimeoutError, socket.timeout)):
            raise RouterPathError(
                "9Router response timed out after request; the UI may already "
                "have submitted it. Inspect browser before any retry."
            ) from exc
        raise RouterPathError(
            "Cannot reach local 9Router. Check 127.0.0.1:20128 and its process."
        ) from exc
    if len(wire) > MAX_BODY:
        raise RouterPathError("9Router response exceeded safe size limit.")
    try:
        text = wire.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RouterPathError("9Router response is not UTF-8.") from exc
    return code, response_headers, text


def parse_stream(text: str) -> str:
    parts: list[str] = []
    done = False
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if raw == "[DONE]":
            done = True
            break
        try:
            event = json.loads(raw)
        except ValueError as exc:
            raise RouterPathError("Invalid 9Router SSE event JSON.") from exc
        if not isinstance(event, dict):
            raise RouterPathError("Invalid 9Router SSE event type.")
        for choice in event.get("choices", []):
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") or {}
            if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                parts.append(delta["content"])
    if not done:
        raise RouterPathError("9Router SSE ended without [DONE].")
    return "".join(parts)


def parse_models(text: str) -> list[str]:
    try:
        data = json.loads(text)
        models = data["data"]
        if not isinstance(models, list):
            raise TypeError()
        return [x["id"] for x in models if isinstance(x, dict)
                and isinstance(x.get("id"), str)]
    except (ValueError, TypeError, KeyError) as exc:
        raise RouterPathError("Invalid 9Router models response.") from exc


def chat_once(*, model: str, port: int, key: str | None,
              stream: bool = False, prompt: str = DEFAULT_TEST_PROMPT,
              history: bool = False) -> tuple[str, str]:
    """Test a single text prompt or a complete small history through 9Router."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        raise RouterPathError(f"Prompt must be 1..{MAX_PROMPT_CHARS} non-blank characters.")
    if history:
        messages = [
            {"role": "system", "content": "Respond concisely to the final user turn."},
            {"role": "user", "content": "Remember the word ALPHA."},
            {"role": "assistant", "content": "ALPHA"},
            {"role": "user", "content": prompt},
        ]
    else:
        messages = [{"role": "user", "content": prompt}]
    body = {
        "model": model,
        "messages": messages,
        "stream": bool(stream),  # explicit for 9Router versions with stream-default bug
    }
    status, headers, text = request_router(
        port=port, path="/v1/chat/completions", key=key, body=body
    )
    if status != 200:
        raise RouterPathError("9Router returned unexpected HTTP status.")
    kind = headers.get("content-type", "").lower()
    if stream:
        if not kind.startswith("text/event-stream"):
            raise RouterPathError("Expected SSE, received a different content type.")
        return parse_stream(text), kind
    if not kind.startswith("application/json"):
        raise RouterPathError(
            "Expected JSON. Verify 9Router forwards explicit stream=false."
        )
    try:
        data = json.loads(text)
        answer = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RouterPathError("9Router returned an invalid Chat Completion.") from exc
    if not isinstance(answer, str):
        raise RouterPathError("9Router returned non-text content.")
    return answer, kind


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", type=int, default=20128)
    p.add_argument("--model", default=MODEL, help="Prefixed 9Router model name")
    p.add_argument("--stream", action="store_true", help="Test buffered SSE via 9Router")
    p.add_argument(
        "--prompt", default=None,
        help="Harmless test text; visible in local shell history, avoid secrets",
    )
    p.add_argument(
        "--history", action="store_true",
        help="Send a four-message JSON transcript to test role/history mapping",
    )
    p.add_argument(
        "--min-reply-chars", type=int, default=0,
        help="Fail if response is shorter than N characters (long-answer smoke test)",
    )
    p.add_argument(
        "--expect-suffix", default=None,
        help="Require reply to end with a specific test marker; not proof "
             "of upstream generation completion",
    )
    p.add_argument("--models-only", action="store_true", help="List model IDs without sending a prompt")
    p.add_argument("--save-key", action="store_true", help="Prompt for and store 9Router client key privately")
    p.add_argument("--key-file", type=Path, default=KEY_FILE)
    args = p.parse_args(argv)
    try:
        if args.save_key:
            save_key(args.key_file)
            return 0
        if not ALLOWED_MODEL.fullmatch(args.model) or len(args.model) > 128:
            raise RouterPathError("Invalid prefixed 9Router model name.")
        if not 0 <= args.min_reply_chars <= 100_000:
            raise RouterPathError("--min-reply-chars must be 0..100000.")
        if args.expect_suffix is not None and (
            not args.expect_suffix
            or len(args.expect_suffix) > 100
            or any(ord(ch) < 32 or ord(ch) > 126 for ch in args.expect_suffix)
        ):
            raise RouterPathError(
                "--expect-suffix must be 1..100 printable ASCII characters."
            )
        key = read_key(args.key_file)
        # Model discovery may be public. Enforce auth-role safety specifically
        # before CHAT dispatch so --models-only still helps diagnosis.
        if not args.models_only:
            reject_reused_upstream_key(key)
        _, _, models_json = request_router(
            port=args.port, path="/v1/models", key=key
        )
        ids = parse_models(models_json)
        if args.models_only:
            print("9Router advertised models:")
            for model in ids:
                # Model names are not credentials. Avoid huge model catalogs.
                if model.startswith(args.model.split("/")[0] + "/"):
                    print(" ", model[:128])
            print(f"Total model IDs: {len(ids)}")
            return 0
        if args.model not in ids:
            raise RouterPathError(
                "Requested model not present in 9Router /v1/models. "
                "Create provider node + key connection, verify prefix, "
                "then rerun --models-only."
            )
        print("9Router model discovery: PASS")
        answer, kind = chat_once(
            model=args.model, port=args.port, key=key, stream=args.stream,
            prompt=(
                args.prompt if args.prompt is not None
                else ("What word did I tell you to remember? Answer only that word."
                      if args.history else DEFAULT_TEST_PROMPT)
            ),
            history=args.history,
        )
        if len(answer) < args.min_reply_chars:
            raise RouterPathError(
                "9Router delivered a response shorter than the requested "
                "minimum; do not treat this long-answer test as PASS."
            )
        if args.expect_suffix is not None:
            # A marker is only an integration smoke check. It cannot prove
            # that the upstream UI emitted a final generation signal.
            if not answer.rstrip().endswith(args.expect_suffix):
                raise RouterPathError(
                    "Expected response suffix was not observed; investigate "
                    "possible incomplete reply or model noncompliance."
                )
        print("9Router -> Brain Gateway -> ClickUp: PASS")
        if args.expect_suffix is not None:
            print("Expected response suffix observed (NOT a final generation signal).")
        print("Response:", "SSE" if args.stream else "JSON", "(no true token-stream claim)")
        print("Reply characters:", len(answer))
        print("Reply preview:", answer[:120].replace("\r", " ").replace("\n", " "))
        return 0
    except RouterPathError as exc:
        print(f"9Router path test: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
