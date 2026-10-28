#!/usr/bin/env python3
"""Verify a LOCAL 9Router -> local ClickUp Brain gateway path.

Unlike check_router_compat.py (port 8787), this client calls 9Router on
127.0.0.1:20128 and exercises the configured custom-provider route.
No 9Router dashboard manipulation, credential export, or retry loops.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
KEY_FILE = ROOT / ".local" / "ninerouter.key"
MODEL = "brain/clickup-ui-current"
ALLOWED_MODEL = re.compile(r"^[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+$")
MAX_BODY = 2_000_000


class RouterPathError(Exception):
    """A safe error: never include a response body, key, or prompt."""


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
        raise RouterPathError(f"9Router HTTP {exc.code}; inspect its dashboard.") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
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
              stream: bool = False) -> tuple[str, str]:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly OK."}],
        "stream": bool(stream),  # critical for 9Router versions with stream default bug
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
    p.add_argument("--stream", action="store_true", help="Test SSE path")
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
        key = read_key(args.key_file)
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
            model=args.model, port=args.port, key=key, stream=args.stream
        )
        print("9Router -> Brain Gateway -> ClickUp: PASS")
        print("Response:", "SSE" if args.stream else "JSON", "(no true token-stream claim)")
        print("Reply characters:", len(answer))
        print("Reply preview:", answer[:120].replace("\r", " ").replace("\n", " "))
        return 0
    except RouterPathError as exc:
        print(f"9Router path test: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
