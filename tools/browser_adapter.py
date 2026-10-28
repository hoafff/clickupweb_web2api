#!/usr/bin/env python3
"""Authorized ClickUp Brain browser-session adapter (research proof of concept).

Runs an interactive, VISIBLE Playwright browser with its own local profile.
- manual: the researcher sends ONE UI message; adapter receives its WS reply.
- auto: fills/sends ONE message through explicit, researcher-verified CSS
  selectors. No guessed selectors, login automation, hidden API replay, or
  credential export.

The observed events are aiConversationStarted + chatCommentCreated, which
mean a reply comment was created, NOT that model generation has conclusively
ended. This is NOT an OpenAI-compatible API or a hosted/proxy service.

Run from repository root (Windows):
  python tools/browser_adapter.py --mode manual
  python -m tools.browser_adapter --mode manual
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any
from urllib.parse import urlsplit

# Same direct-script / module compatibility as replay_brain_events.py.
if __package__ in (None, ""):
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from tools.conversation_correlator import (
    ConversationEventCorrelator,
    CorrelatedComment,
)
from playwright.async_api import Error as PlaywrightError, Page, WebSocket, async_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = PROJECT_ROOT / ".local" / "browser-profile"


class BrowserAdapterError(RuntimeError):
    """Safe message; never include WS frames, prompts, or credentials."""


def _ws_in_scope(url: str) -> bool:
    """Only the ClickUp realtime frontdoor path seen in V3."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        return (
            parsed.scheme in {"ws", "wss"}
            and (host == "clickup.com" or host.endswith(".clickup.com"))
            and parsed.path == "/ws"
        )
    except (ValueError, TypeError):
        return False


def _parse_ws_payload(frame: str | bytes) -> dict[str, Any] | None:
    """Only parse in-memory JSON object events, never persist raw WS content."""
    if not isinstance(frame, str) or len(frame) > 262_144:
        return None
    try:
        data = json.loads(frame)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("event"), dict):
        return None
    return data


class BrainBrowserBridge:
    """Single-active-request bridge; no cross-conversation guessing.

    A new arm() establishes an observable WS-start window. If multiple
    distinct AI start events appear before the reply is obtained, we abort
    rather than silently return an answer from another conversation.
    """

    def __init__(self) -> None:
        self.correlator = ConversationEventCorrelator(
            scope_id="one-authorized-browser-tab",
            ttl_seconds=600,
            max_records=256,
        )
        self._starts: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue(maxsize=32)
        self._armed = False
        self._observed_ids: set[str] = set()
        self._subscribed_pages: set[int] = set()
        self._frame_count = 0
        self._ws_connections = 0

    def attach_page(self, page: Page) -> None:
        if id(page) in self._subscribed_pages:
            return
        self._subscribed_pages.add(id(page))
        page.on("websocket", self.attach_socket)

    def attach_socket(self, socket: WebSocket) -> None:
        if not _ws_in_scope(socket.url):
            return
        self._ws_connections += 1
        socket.on("framereceived", self.on_frame)

    def arm(self) -> None:
        """Call only once the UI is ready and prior generation is finished."""
        self._armed = True
        self._observed_ids.clear()
        while not self._starts.empty():
            self._starts.get_nowait()

    def on_frame(self, frame: str | bytes) -> None:
        """Synchronous Playwright event callback; no network and no file I/O."""
        data = _parse_ws_payload(frame)
        if data is None:
            return
        self._frame_count += 1
        event = data["event"]
        record = {
            "kind": "ws_frame_content",
            "direction": "received",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "payload": {"data": data},
        }
        self.correlator.ingest(record)
        if not self._armed or event.get("name") != "aiConversationStarted":
            return
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return
        rid = payload.get("ai_result_id")
        cid = payload.get("conversation_id")
        if not isinstance(rid, str) or not rid or rid in self._observed_ids:
            return
        self._observed_ids.add(rid)
        if self._starts.full():
            # Fail closed, never guess among more than 32 concurrent results.
            self._armed = False
            return
        self._starts.put_nowait((rid, cid if isinstance(cid, str) else None))

    async def await_reply_created(self, *, timeout: float = 120) -> CorrelatedComment:
        """Await ONE observed start + matching comment; reject ambiguity.

        The caller must arm immediately before the one UI send operation.
        The result text stays in memory and is printed only if explicitly asked.
        """
        if not self._armed:
            raise BrowserAdapterError("Adapter is not armed.")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        deadline = time.monotonic() + timeout
        try:
            try:
                rid, cid = await asyncio.wait_for(self._starts.get(), timeout)
            except asyncio.TimeoutError as exc:
                raise BrowserAdapterError(
                    "No aiConversationStarted event captured in time; "
                    "check Brain page, session, and websocket connection."
                ) from exc

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BrowserAdapterError("Reply creation timed out.")
            reply_task = asyncio.create_task(
                self.correlator.wait_for_created(
                    rid, conversation_id=cid, timeout=remaining
                )
            )
            more_starts = asyncio.create_task(self._starts.get())
            try:
                done, _ = await asyncio.wait(
                    {reply_task, more_starts},
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # Check FIRST, even when reply and extra start are simultaneous.
                if more_starts in done and more_starts.result()[0] != rid:
                    raise BrowserAdapterError(
                        "More than one AI conversation started; cannot safely "
                        "attribute reply to the single UI send."
                    )
                if reply_task in done:
                    return reply_task.result()
                if not done:
                    raise BrowserAdapterError(
                        "Timed out waiting for matched AI reply comment."
                    )
                # Duplicate start was ignored by on_frame, so this is unlikely.
                return await asyncio.wait_for(
                    reply_task, max(0.001, deadline - time.monotonic())
                )
            except asyncio.TimeoutError as exc:
                raise BrowserAdapterError(
                    "Timed out waiting for matched AI reply comment."
                ) from exc
            finally:
                for task in (reply_task, more_starts):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(reply_task, more_starts, return_exceptions=True)
        finally:
            self._armed = False

    def statistics(self) -> dict[str, int]:
        """Numerical counters only, no user data or private identifiers."""
        return {
            "websocket_connections_observed": self._ws_connections,
            "json_ws_frames_processed": self._frame_count,
            "matching_reply_comments": self.correlator.statistics().get("matched", 0),
        }

    def close(self) -> None:
        self._armed = False
        self.correlator.close()


async def _input(prompt: str) -> str:
    return await asyncio.to_thread(input, prompt)


async def _send_via_ui(
    page: Page, prompt: str, composer_css: str, send_css: str
) -> None:
    """Never send unless BOTH explicit CSS selectors are unique and visible."""
    if not prompt.strip():
        raise BrowserAdapterError("Empty prompt; refusing to submit.")
    if not composer_css or not send_css:
        raise BrowserAdapterError("Both composer and send CSS selectors are required.")
    try:
        composer = page.locator(composer_css)
        sender = page.locator(send_css)
        if await composer.count() != 1 or await sender.count() != 1:
            raise BrowserAdapterError(
                "Composer/send selector did not match exactly one element each; "
                "no message was sent."
            )
        if not await composer.is_visible() or not await sender.is_visible():
            raise BrowserAdapterError(
                "Composer or send button is not visible; no message was sent."
            )
        await composer.fill(prompt, timeout=5_000)
        await sender.click(timeout=5_000)
    except PlaywrightError as exc:
        raise BrowserAdapterError(
            "UI input or click failed. Check CSS selectors and Brain page state."
        ) from exc


async def run(args: argparse.Namespace) -> int:
    profile = args.profile_dir.expanduser().resolve()
    if args.timeout <= 0:
        print("--timeout must be positive.", file=sys.stderr)
        return 2
    if args.mode == "auto" and not (args.composer_selector and args.send_selector):
        print(
            "Auto mode requires --composer-selector AND --send-selector, "
            "verified by the researcher in this Workspace.",
            file=sys.stderr,
        )
        return 2
    if args.mode == "auto" and not args.confirm_send:
        print(
            "Auto mode requires --confirm-send to explicitly authorize a UI message.",
            file=sys.stderr,
        )
        return 2
    if not (
        args.url.startswith("https://app.clickup.com/")
        or args.url == "https://app.clickup.com"
    ):
        print("Only HTTPS app.clickup.com URLs are supported.", file=sys.stderr)
        return 2

    profile.mkdir(parents=True, exist_ok=True)
    bridge = BrainBrowserBridge()
    try:
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=False,
                accept_downloads=False,
            )
            context.on("page", bridge.attach_page)
            for known in context.pages:
                bridge.attach_page(known)
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                await page.goto(args.url, wait_until="domcontentloaded", timeout=45_000)
            except PlaywrightError:
                print("Navigation incomplete; continue from the browser manually.")

            print("Browser profile stays PRIVATE; log in and open ClickUp Brain.")
            print("Use only ONE Brain tab and finish prior AI generations first.")
            await _input("When the target chat is ready, press ENTER here to arm: ")
            if page.is_closed():
                raise BrowserAdapterError("Selected browser tab was closed.")

            prompt = ""
            if args.mode == "auto":
                prompt = await _input("One test prompt to send via verified selectors: ")
                if not prompt.strip():
                    raise BrowserAdapterError("Empty prompt; no message sent.")

            bridge.arm()
            if args.mode == "manual":
                print("Armed. SEND EXACTLY ONE test message in the visible Brain tab.")
            else:
                await _send_via_ui(
                    page, prompt, args.composer_selector, args.send_selector
                )
                print("One message clicked in UI; awaiting WebSocket reply.")

            reply = await bridge.await_reply_created(timeout=args.timeout)
            print("SUCCESS: AI reply-created event correlated to the UI message window.")
            print(f"Reply length: {len(reply.text)} characters")
            print(f"WS diagnostics: {json.dumps(bridge.statistics())}")
            if args.show_reply:
                print("---- PRIVATE REPLY TEXT (local console) ----")
                print(reply.text)
                print("-------------------------------------------")
            await context.close()
            return 0
    except (PlaywrightError, BrowserAdapterError) as exc:
        # Never include HTTP auth, WS raw frame content, opaque IDs or prompt.
        print(f"Browser adapter failed: {exc}", file=sys.stderr)
        return 1
    finally:
        bridge.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default="https://app.clickup.com/")
    p.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE)
    p.add_argument("--mode", choices=("manual", "auto"), default="manual")
    p.add_argument("--timeout", type=float, default=120)
    p.add_argument("--composer-selector", help="Explicit researcher-verified CSS selector")
    p.add_argument("--send-selector", help="Explicit researcher-verified CSS selector")
    p.add_argument("--confirm-send", action="store_true", help="Opt in to one UI submission")
    p.add_argument("--show-reply", action="store_true", help="Print private reply text locally")
    args = p.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
