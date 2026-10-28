#!/usr/bin/env python3
"""Test the LOCAL --router-mode facade before wiring it into 9Router.

Tests actual HTTP request/response with a harmless prompt, not a mock.
Does not start 9Router, modify its settings, read ClickUp cookies or export
browser profile data. Returns concise results and does not print API secrets.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEYFILE = REPO_ROOT / ".local" / "gateway.key"


def request_local(path: str, key: str, body: dict | None, port: int):
    if path not in ("/v1/models", "/v1/chat/completions"):
        raise ValueError("Unsupported path")
    if not 1024 <= port <= 65535:
        raise ValueError("Invalid port")
    headers = {"Authorization": "Bearer " + key}
    payload = None
    if body is not None:
        payload = json.dumps(
            body, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(
        "http://127.0.0.1:" + str(port) + path,
        headers=headers,
        data=payload,
        method="POST" if payload else "GET",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=150) as response:
        text = response.read(2_000_000).decode("utf-8")
        return response.status, dict(response.headers), text


def parse_sse_result(text: str) -> str:
    events = [
        line[6:] for line in text.splitlines()
        if line.startswith("data: ")
    ]
    if not events or events[-1] != "[DONE]":
        raise ValueError("No final [DONE] SSE marker")
    chunks = [json.loads(e) for e in events[:-1]]
    if any(c.get("object") != "chat.completion.chunk" for c in chunks):
        raise ValueError("Invalid SSE chat.completion.chunk")
    return "".join(
        delta.get("content", "") for c in chunks
        for choice in c.get("choices", [])
        for delta in [choice.get("delta", {})]
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--key-file", type=Path, default=DEFAULT_KEYFILE)
    p.add_argument("--stream", action="store_true")
    p.add_argument("--history", action="store_true")
    args = p.parse_args()
    try:
        key = args.key_file.read_text(encoding="ascii").strip()
        if len(key) < 24:
            raise ValueError("Missing/invalid gateway Bearer key.")
        _, _, models_text = request_local("/v1/models", key, None, args.port)
        model_list = json.loads(models_text)["data"]
        if not any(x.get("id") == "clickup-ui-current" for x in model_list):
            raise ValueError("Model clickup-ui-current was not listed.")
        print("Models endpoint: PASS (clickup-ui-current)")

        msgs = [{"role": "user", "content": "Reply with exactly OK."}]
        if args.history:
            msgs = [
                {"role": "system", "content": "This is a simple text-only test."},
                {"role": "user", "content": "Please say ALPHA."},
                {"role": "assistant", "content": "ALPHA"},
                {"role": "user", "content": "What was that word? Reply only the word."},
            ]
        status, headers, body = request_local(
            "/v1/chat/completions", key,
            {"model": "clickup-ui-current", "messages": msgs, "stream": args.stream},
            args.port,
        )
        if status != 200:
            raise ValueError("Unexpected HTTP response status")
        if args.stream:
            if headers.get("X-Stream-Mode") != "buffered":
                raise ValueError("Missing buffered SSE disclosure header.")
            answer = parse_sse_result(body)
            print("Buffered SSE: PASS (NOT real token-level streaming)")
        else:
            answer = json.loads(body)["choices"][0]["message"]["content"]
            print("JSON Chat Completions: PASS")
        print("Reply characters:", len(answer))
        print("Reply preview:", answer[:120].replace("\r", " ").replace("\n", " "))
        return 0
    except (OSError, urllib.error.URLError, ValueError, KeyError, TypeError,
            UnicodeError, json.JSONDecodeError) as exc:
        # Do not print returned server HTTP body or credentials/URLs.
        if isinstance(exc, urllib.error.HTTPError):
            print(f"Upstream HTTP status: {exc.code}", file=sys.stderr)
        else:
            print(
                "Router smoke test failed. Check --router-mode gateway, "
                "login state, and model field.",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
