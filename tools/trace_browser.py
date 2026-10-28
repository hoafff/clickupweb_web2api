#!/usr/bin/env python3
"""Passive Playwright metadata tracer for an authorized ClickUp Brain research session.

- Opens a persistent, visible Chromium profile for *manual* UI interaction.
- Observes HTTP lifecycle and WebSocket frame *sizes*, never message contents.
- Does NOT read credentials/headers, response bodies, prompt text, or cookies.
- Removes URL query/fragment and masks likely IDs in path segments.
- Browser profile contains session secrets: keep it private and never commit it.

Usage:
    python tools/trace_browser.py --url https://app.clickup.com/
    python tools/trace_browser.py --url https://app.clickup.com/ --hosts clickup.com
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib.parse import urlsplit

try:
    from tools.payload_capture import allows_http_body, parse_content
except ModuleNotFoundError:
    from payload_capture import allows_http_body, parse_content

from playwright.async_api import (
    BrowserContext,
    Error as PlaywrightError,
    Page,
    Request,
    Response,
    WebSocket,
    async_playwright,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TRACE_PATH = PROJECT_ROOT / "artifacts" / "network_events.jsonl"
DEFAULT_PROFILE_PATH = PROJECT_ROOT / ".local" / "browser-profile"

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
NUMERIC_RE = re.compile(r"^[0-9]{5,}$")
LONG_TOKEN_RE = re.compile(r"^[a-zA-Z0-9_~-]{22,}$")
HEX_RE = re.compile(r"^[0-9a-fA-F]{16,}$")
HEX_EMBEDDED_RE = re.compile(r"(?:token|key|session|auth)", re.I)
MIXED_OPAQUE_RE = re.compile(r"^(?=.{10,}$)(?=.*[a-zA-Z])(?=.*[0-9])[a-zA-Z0-9_-]+$")
SAFE_KEY_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_:\-]{0,49}$")


def _mask_segment(segment: str) -> str:
    if not segment:
        return segment
    if "@" in segment or "%" in segment or UUID_RE.fullmatch(segment):
        return "{id}"
    if NUMERIC_RE.fullmatch(segment) or HEX_RE.fullmatch(segment):
        return "{id}"
    if LONG_TOKEN_RE.fullmatch(segment) or MIXED_OPAQUE_RE.fullmatch(segment):
        return "{token}"
    if HEX_EMBEDDED_RE.search(segment) and "=" in segment:
        return "{token}"
    return segment


def sanitize_url(raw_url: str) -> str:
    """Keep origin/path shape; strip query/fragment and mask opaque IDs."""
    try:
        parts = urlsplit(raw_url)
        host = (parts.hostname or "").lower()
        if parts.scheme not in {"http", "https", "ws", "wss"} or not host:
            return "<non-http-url>"
        # Fragment is intentionally omitted. Query is always omitted.
        path = "/".join(_mask_segment(s) for s in parts.path.split("/"))
        if not path:
            path = "/"
        return f"{parts.scheme}://{host}{path}"
    except (ValueError, AttributeError):
        return "<invalid-url>"


def host_in_scope(raw_url: str, allowed_hosts: tuple[str, ...]) -> bool:
    try:
        host = (urlsplit(raw_url).hostname or "").lower()
    except ValueError:
        return False
    return bool(host) and any(
        host == name or host.endswith("." + name) for name in allowed_hosts
    )


def describe_json_keys(data: Any, *, max_depth: int = 3, max_keys: int = 60) -> list[str]:
    """Return schema-like paths of JSON *keys only* without any values."""
    keys: list[str] = []

    def walk(value: Any, prefix: str, depth: int) -> None:
        if depth > max_depth or len(keys) >= max_keys:
            return
        if isinstance(value, dict):
            for key, item in list(value.items())[:max_keys]:
                if len(keys) >= max_keys:
                    break
                safe_key = key if isinstance(key, str) and SAFE_KEY_RE.fullmatch(key) else "{key}"
                full = f"{prefix}.{safe_key}" if prefix else safe_key
                keys.append(full)
                if isinstance(item, (dict, list)):
                    walk(item, full, depth + 1)
        elif isinstance(value, list) and value:
            walk(value[0], f"{prefix}[]", depth + 1)

    walk(data, "", 0)
    return keys


def request_json_keys(request: Request) -> list[str]:
    # post_data_json is parsed in memory; this tool stores keys only.
    try:
        data = request.post_data_json
    except (ValueError, TypeError, PlaywrightError):
        return []
    return describe_json_keys(data)


def ws_json_key_paths(data: str | bytes) -> list[str]:
    """Parse JSON frames and retain schema *only*, no payload values.

    Unknown frame encodings are intentionally not guessed; mark them as
    unrecognized rather than logging raw fragments.
    """
    if not isinstance(data, str):
        return []
    try:
        parsed = json.loads(data)
    except (ValueError, TypeError):
        return []
    return describe_json_keys(parsed, max_depth=3, max_keys=30)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class TraceSink:
    def __init__(self, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        self.output = output
        self._fp = output.open("a", encoding="utf-8")
        self.count = 0

    def write(self, kind: str, **fields: Any) -> None:
        item = {"timestamp_utc": now_utc(), "kind": kind, **fields}
        self._fp.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._fp.flush()
        self.count += 1

    def close(self) -> None:
        self._fp.close()


class NetworkObserver:
    def __init__(
        self,
        sink: TraceSink,
        hosts: tuple[str, ...],
        capture_ws_schema: bool = False,
        *,
        content_sink: TraceSink | None = None,
        max_content_bytes: int = 196_608,
    ) -> None:
        self.sink = sink
        self.hosts = hosts
        self.capture_ws_schema = capture_ws_schema
        self.content_sink = content_sink
        self.max_content_bytes = max_content_bytes
        self.current_phase = "unmarked"
        self._request_starts: dict[int, float] = {}
        self._request_phases: dict[int, str] = {}
        self._pending: set[asyncio.Task] = set()
        self._seen_pages: set[int] = set()

    def mark(self, label: str) -> None:
        self.current_phase = label
        self.sink.write("manual_marker", label=label)
        if self.content_sink is not None:
            self.content_sink.write("manual_marker", label=label)

    async def flush(self) -> None:
        """Wait for response-body reads before closing the browser and sinks."""
        if self._pending:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tuple(self._pending), return_exceptions=True),
                    timeout=15,
                )
            except asyncio.TimeoutError:
                for task in tuple(self._pending):
                    task.cancel()
                await asyncio.gather(*tuple(self._pending), return_exceptions=True)

    async def _capture_response(self, request: Request) -> None:
        if self.content_sink is None:
            return
        phase = self._request_phases.get(id(request), "unmarked")
        if phase == "unmarked":
            return
        try:
            response = await request.response()
            if response is None:
                return
            ct = response.headers.get("content-type", "")
            if not allows_http_body(ct):
                return
            raw_length = response.headers.get("content-length", "")
            if raw_length.isdecimal() and int(raw_length) > self.max_content_bytes:
                return
            raw = await response.body()
            result = parse_content(
                raw, content_type=ct, max_bytes=self.max_content_bytes
            )
            if result.get("format") in {"json", "sse_json"}:
                self.content_sink.write(
                    "http_response_content",
                    request_id=str(id(request)),
                    phase=self._request_phases.get(id(request), "unmarked"),
                    method=request.method,
                    url=sanitize_url(request.url),
                    content_type=ct.split(";")[0].strip().lower(),
                    status=response.status,
                    payload=result,
                )
        except (PlaywrightError, ValueError, TypeError):
            # Body may be unavailable after disconnect/redirect.
            return

    def _schedule_response_capture(self, request: Request) -> None:
        if self.content_sink is None or self._request_phases.get(id(request), "unmarked") == "unmarked":
            return
        task = asyncio.create_task(self._capture_response(request))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)


    def watch_context(self, context: BrowserContext) -> None:
        context.on("request", self.on_request)
        context.on("response", self.on_response)
        context.on("requestfinished", self.on_request_finished)
        context.on("requestfailed", self.on_request_failed)
        context.on("page", self.watch_page)
        for page in context.pages:
            self.watch_page(page)

    def watch_page(self, page: Page) -> None:
        page_id = id(page)
        if page_id in self._seen_pages:
            return
        self._seen_pages.add(page_id)
        page.on("websocket", self.on_websocket)

    def on_request(self, request: Request) -> None:
        if not host_in_scope(request.url, self.hosts):
            return
        self._request_starts[id(request)] = time.monotonic()
        self._request_phases[id(request)] = self.current_phase
        if self.content_sink is not None and self.current_phase != "unmarked":
            try:
                raw = request.post_data_buffer
                if raw:
                    payload = parse_content(raw, max_bytes=self.max_content_bytes)
                    if payload.get("format") == "json":
                        self.content_sink.write(
                            "http_request_content",
                            request_id=str(id(request)),
                            phase=self.current_phase,
                            method=request.method,
                            url=sanitize_url(request.url),
                            payload=payload,
                        )
            except (ValueError, TypeError, PlaywrightError):
                pass
        self.sink.write(
            "http_request",
            request_id=str(id(request)),
            method=request.method,
            url=sanitize_url(request.url),
            resource_type=request.resource_type,
            json_key_paths=request_json_keys(request),
        )

    def on_response(self, response: Response) -> None:
        request = response.request
        if not host_in_scope(request.url, self.hosts):
            return
        # Reading Content-Type only is safe; never serialize response.headers.
        ct = response.headers.get("content-type", "").split(";")[0].strip().lower()
        self.sink.write(
            "http_response",
            request_id=str(id(request)),
            method=request.method,
            url=sanitize_url(response.url),
            status=response.status,
            content_type=ct,
        )

    def _duration_ms(self, request: Request) -> int | None:
        started = self._request_starts.pop(id(request), None)
        if started is None:
            return None
        return round((time.monotonic() - started) * 1000)

    def on_request_finished(self, request: Request) -> None:
        if not host_in_scope(request.url, self.hosts):
            return
        self.sink.write(
            "http_finished",
            request_id=str(id(request)),
            duration_ms=self._duration_ms(request),
        )
        self._schedule_response_capture(request)

    def on_request_failed(self, request: Request) -> None:
        if not host_in_scope(request.url, self.hosts):
            return
        # Do not persist exception strings containing internal network details.
        self.sink.write(
            "http_failed",
            request_id=str(id(request)),
            duration_ms=self._duration_ms(request),
        )
        self._request_phases.pop(id(request), None)

    def on_websocket(self, ws: WebSocket) -> None:
        if not host_in_scope(ws.url, self.hosts):
            return
        ws_id = str(id(ws))
        path = sanitize_url(ws.url)
        self.sink.write("ws_open", websocket_id=ws_id, url=path)

        def frame(direction: str, data: str | bytes) -> None:
            if (
                self.content_sink is not None
                and self.current_phase != "unmarked"
                and isinstance(data, str)
            ):
                payload = parse_content(data, max_bytes=self.max_content_bytes)
                if payload.get("format") == "json":
                    self.content_sink.write(
                        "ws_frame_content",
                        websocket_id=ws_id,
                        direction=direction,
                        phase=self.current_phase,
                        url=path,
                        payload=payload,
                    )
            self.sink.write(
                "ws_frame",
                websocket_id=ws_id,
                direction=direction,
                payload_length=len(data),
                payload_type="binary" if isinstance(data, bytes) else "text",
                json_key_paths=ws_json_key_paths(data) if self.capture_ws_schema else [],
            )

        ws.on("framesent", lambda data: frame("sent", data))
        ws.on("framereceived", lambda data: frame("received", data))
        ws.on("close", lambda *_: self.sink.write("ws_close", websocket_id=ws_id))
        ws.on(
            "socketerror",
            lambda *_: self.sink.write("ws_error", websocket_id=ws_id),
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://app.clickup.com/")
    parser.add_argument(
        "--hosts",
        default="clickup.com",
        help="Comma-separated allowed hostname suffixes; default clickup.com",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_TRACE_PATH)
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE_PATH)
    parser.add_argument("--timeout", type=int, default=45, help="Navigation timeout seconds")
    parser.add_argument("--capture-ws-schema", action="store_true", help="Record JSON key paths from WebSocket frames (never values); opt-in")
    parser.add_argument(
        "--capture-content",
        action="store_true",
        help="OPT-IN: record sanitized JSON request/response and WS payloads to a separate PRIVATE file",
    )
    parser.add_argument(
        "--content-output",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "brain_private_content.jsonl",
    )
    parser.add_argument(
        "--max-content-bytes",
        type=int,
        default=196_608,
        help="Max bytes to retain per JSON/WS response (default 192 KiB)",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    hosts = tuple(
        h.lower().lstrip(".").strip()
        for h in args.hosts.split(",")
        if h.strip()
    )
    if not hosts:
        print("Provide at least one allowed hostname.", file=sys.stderr)
        return 2
    if not host_in_scope(args.url, hosts):
        print("The --url host must match a value in --hosts.", file=sys.stderr)
        return 2

    output = args.output.expanduser().resolve()
    profile = args.profile_dir.expanduser().resolve()
    content_output = args.content_output.expanduser().resolve()
    if args.capture_content and (
        content_output == output or content_output.is_relative_to(profile)
    ):
        print("Content output must differ from metadata output and browser profile.", file=sys.stderr)
        return 2
    if not 1_024 <= args.max_content_bytes <= 1_048_576:
        print("--max-content-bytes must be between 1 KiB and 1 MiB.", file=sys.stderr)
        return 2
    if output.is_relative_to(profile):
        print("Output cannot be located inside the persistent browser profile.", file=sys.stderr)
        return 2
    profile.mkdir(parents=True, exist_ok=True)

    print(f"Trace: {output}")
    print(f"Persistent browser profile (SENSITIVE): {profile}")
    print(f"Allowed hosts: {', '.join(hosts)}")
    if args.capture_content:
        print(f"PRIVATE JSON content file: {content_output}")
        print("Content capture starts ONLY after the first 'mark NAME' command.")
        print("Sensitive contents may remain even after best-effort redaction.")
        print("Never publish this file or raw browser profile without manual review.")
    else:
        print("Recording request metadata / JSON keys / WebSocket frame lengths ONLY.")
    print("Do not share browser profile or raw account data.")

    sink = TraceSink(output)
    content_sink = TraceSink(content_output) if args.capture_content else None
    try:
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=False,
                accept_downloads=False,
            )
            observer = NetworkObserver(
                sink,
                hosts,
                capture_ws_schema=args.capture_ws_schema,
                content_sink=content_sink,
                max_content_bytes=args.max_content_bytes,
            )
            observer.watch_context(context)

            page = context.pages[0] if context.pages else await context.new_page()
            try:
                await page.goto(
                    args.url,
                    wait_until="domcontentloaded",
                    timeout=max(1, args.timeout) * 1000,
                )
            except PlaywrightError as error:
                print(f"Initial navigation did not complete: {type(error).__name__}.")
                print("Use the browser window manually if needed.")

            print("Navigate to Brain, sign in normally, send test prompts and switch models.")
            print("Type 'mark max_first', 'mark opus_reply', etc. to timestamp UI actions.")
            print("Press ENTER, or type 'stop', to end recording.")
            while True:
                try:
                    line = (await asyncio.to_thread(input)).strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not line or line.lower() in {"stop", "quit", "q"}:
                    break
                if line.lower().startswith("mark "):
                    label = line[5:].strip()
                    if re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", label):
                        observer.mark(label)
                        print(f"Marker recorded: {label}")
                    else:
                        print("Marker must be 1-32 letters, digits, '_' or '-'.")
                else:
                    print("Use 'mark NAME' or ENTER to finish.")
            await asyncio.sleep(0.5)
            await observer.flush()
            await context.close()
    finally:
        sink.close()
        if content_sink is not None:
            content_sink.close()
    print(f"Recorded {sink.count} metadata event(s) in {output}.")
    if content_sink is not None:
        print(f"Recorded {content_sink.count} private content event(s) in {content_output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
