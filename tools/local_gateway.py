#!/usr/bin/env python3
"""LOCAL-only, single-session JSON API facade for authorized ClickUp Brain UI.

This is a tightly scoped compatibility experiment, NOT a direct ClickUp API.
Only accepts a single user message, model='clickup-ui-current', stream=false.
It sends via verified visible Playwright UI controls and waits for the
observed WebSocket reply-created event. Model selection stays in the browser.
It cannot certify generation completion, token usage or stateless semantics.

Security: bind ONLY to 127.0.0.1, require a random local Bearer API key, do
not log prompt/response/auth, and never serialize the browser profile.
"""
from __future__ import annotations

import argparse
import asyncio
import hmac
import os
from pathlib import Path
import sys
import time
from typing import Literal, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

if __package__ in (None, ""):
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field
from playwright.async_api import Error as PlaywrightError, async_playwright

from tools.browser_adapter import (
    BrainBrowserBridge,
    BrowserAdapterError,
    DEFAULT_PROFILE,
    _send_via_ui,
)
from tools.inspect_brain_ui import select_brain_page

MODEL_ID = "clickup-ui-current"
COMPOSER_CSS = 'div[contenteditable="true"]'
SEND_CSS = 'button[data-test="refinement-prompt-submit-button"]'
MAX_PROMPT_CHARS = 8_000


class GatewayBusyError(Exception):
    """Concurrent request rejected to prevent UI session mixing."""


class GatewayUnavailableError(Exception):
    """The browser is not prepared for further requests."""


class GatewaySendError(Exception):
    """UI submission or observed WS correlation failed."""


class PromptEngine(Protocol):
    def is_ready(self) -> bool: ...
    async def complete(self, prompt: str) -> str: ...
    def session_diagnostics(self) -> dict: ...


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user"]
    content: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: Literal["clickup-ui-current"]
    messages: list[ChatMessage] = Field(min_length=1, max_length=1)
    stream: Literal[False] = False
    n: Literal[1] = 1


def create_app(engine: PromptEngine, *, api_key: str) -> FastAPI:
    """Build an app with an injectable engine for fully offline tests."""
    if len(api_key) < 24:
        raise ValueError("CLICKUP_GATEWAY_API_KEY must be at least 24 characters")
    app = FastAPI(
        title="ClickUp Brain UI Bridge (local experimental facade)",
        docs_url=None, redoc_url=None, openapi_url=None,
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"]
    )

    def require_api_key(authorization: str | None = Header(default=None)) -> None:
        prefix = "Bearer "
        provided = (
            authorization[len(prefix):]
            if authorization and authorization.startswith(prefix) else ""
        )
        if not provided or not hmac.compare_digest(provided, api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "browser_ready": engine.is_ready()}

    @app.get("/v1/models", dependencies=[Depends(require_api_key)])
    def models() -> dict:
        return {
            "object": "list",
            "data": [{
                "id": MODEL_ID, "object": "model",
                "owned_by": "local-browser-session",
            }],
        }

    @app.get("/v1/session/diagnostics", dependencies=[Depends(require_api_key)])
    def session_diagnostics() -> dict:
        # No workspace/conversation/AI result identifiers leave the process.
        return engine.session_diagnostics()

    @app.post("/v1/chat/completions", dependencies=[Depends(require_api_key)])
    async def chat(request: ChatRequest) -> dict:
        # Explicitly do not claim support for system prompts, prior messages,
        # model switching, tools, images, token streaming or token usage.
        if not engine.is_ready():
            raise HTTPException(
                status_code=503,
                detail="Browser session is not ready; open Brain UI first.",
            )
        text = request.messages[0].content
        if not text.strip():
            raise HTTPException(status_code=422, detail="Message cannot be blank.")
        try:
            answer = await engine.complete(text)
        except GatewayBusyError as exc:
            raise HTTPException(status_code=429, detail="UI session is busy.") from exc
        except GatewayUnavailableError as exc:
            raise HTTPException(
                status_code=503,
                detail="Browser session unavailable; restart after inspection.",
            ) from exc
        except GatewaySendError as exc:
            raise HTTPException(
                status_code=502,
                detail="UI request did not yield an unambiguous reply-created event; "
                       "inspect browser and restart.",
            ) from exc

        return {
            "id": "chatcmpl-local-" + uuid4().hex,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL_ID,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                # A reply-created WS event is not a verified end-of-stream marker.
                "finish_reason": None,
            }],
            # Deliberately no fabricated token usage.
        }

    return app


class LiveBrowserEngine:
    """One visible Chromium session. Requires manual login/readiness step."""

    def __init__(self, *, profile: Path, url: str, timeout: float = 120) -> None:
        self.profile = profile
        self.url = url
        self.timeout = timeout
        self.bridge = BrainBrowserBridge()
        self._lock = asyncio.Lock()
        self._ready = False
        self._degraded = False
        self._playwright = None
        self._context = None
        self._last_conversation_id: str | None = None
        self._completed_replies = 0
        self._same_conversation = 0
        self._different_conversation = 0
        self._last_relation: str = "unobserved"

    def is_ready(self) -> bool:
        return self._ready and not self._degraded and self._context is not None

    def session_diagnostics(self) -> dict:
        """Safe local diagnostics: report only conversation equality, never IDs."""
        return {
            "completed_replies": self._completed_replies,
            "same_conversation_pairs": self._same_conversation,
            "different_conversation_pairs": self._different_conversation,
            "last_relation": self._last_relation,
        }

    def _observe_reply_conversation(self, conversation_id: str | None) -> None:
        previous_id = self._last_conversation_id
        if conversation_id is None or not isinstance(conversation_id, str):
            relation = "unknown"
            self._last_conversation_id = None
        elif self._completed_replies == 0:
            relation = "first"
            self._last_conversation_id = conversation_id
        elif previous_id is None:
            relation = "unknown"
            self._last_conversation_id = conversation_id
        else:
            relation = "same" if previous_id == conversation_id else "different"
            if relation == "same":
                self._same_conversation += 1
            else:
                self._different_conversation += 1
            self._last_conversation_id = conversation_id
        self._last_relation = relation
        self._completed_replies += 1

    async def __aenter__(self) -> "LiveBrowserEngine":
        self.profile.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        try:
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile),
                headless=False,
                accept_downloads=False,
            )
            self._context.on("page", self.bridge.attach_page)
            for page in self._context.pages:
                self.bridge.attach_page(page)
            page = (
                self._context.pages[0]
                if self._context.pages else await self._context.new_page()
            )
            try:
                await page.goto(self.url, wait_until="domcontentloaded", timeout=45_000)
            except PlaywrightError:
                # Researcher can navigate to Brain manually in visible Chromium.
                print("Initial navigation incomplete; open Brain manually.")
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    def mark_ready(self) -> None:
        if self._context is None:
            raise GatewayUnavailableError("Browser not running.")
        self._ready = True

    async def complete(self, prompt: str) -> str:
        if not self.is_ready():
            raise GatewayUnavailableError()
        # Fail fast if another request is active; do not queue cross-chat sends.
        if self._lock.locked():
            raise GatewayBusyError()
        async with self._lock:
            try:
                page = select_brain_page(self._context.pages)
                parts = urlsplit(page.url)
                if parts.hostname != "app.clickup.com" or "/ai/brain" not in parts.path:
                    raise GatewayUnavailableError()

                # The current UI model/effort is selected manually before serving.
                # History may persist between calls: NOT a stateless API guarantee.
                self.bridge.arm()
                await _send_via_ui(page, prompt, COMPOSER_CSS, SEND_CSS)
                reply = await self.bridge.await_reply_created(timeout=self.timeout)
                self._observe_reply_conversation(reply.conversation_id)
                return reply.text
            except asyncio.CancelledError:
                # A disconnected HTTP client may cancel an in-flight UI send.
                # Never accept another request until the operator has inspected
                # the browser, because the original AI reply may arrive later.
                self._degraded = True
                raise
            except Exception as exc:
                # An unknown Playwright/DOM/WS failure may have occurred after
                # click. Fail closed and never auto-retry a possibly sent prompt.
                self._degraded = True
                raise GatewaySendError() from exc

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        self._ready = False
        self.bridge.close()
        if self._context is not None:
            try:
                await self._context.close()
            finally:
                self._context = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None


def validate_clickup_app_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "app.clickup.com"
            and parsed.username is None
            and parsed.password is None
        )
    except (TypeError, ValueError):
        return False


async def serve(args: argparse.Namespace, api_key: str) -> None:
    import uvicorn

    profile = args.profile_dir.expanduser().resolve()
    async with LiveBrowserEngine(
        profile=profile, url=args.url, timeout=args.timeout
    ) as engine:
        print("Visible Chromium launched. Log in to your authorized Workspace.")
        print("Open ClickUp Brain Ask; select model and effort in the browser.")
        print("Finish any pending AI reply and close extra ClickUp tabs.")
        await asyncio.to_thread(
            input, "When ready, press ENTER to enable LOCAL API server: "
        )
        # Validate page before accepting an API request; no raw IDs are printed.
        page = select_brain_page(engine._context.pages)
        if "/ai/brain" not in urlsplit(page.url).path:
            raise GatewayUnavailableError("Navigate to Brain Ask first.")
        engine.mark_ready()
        app = create_app(engine, api_key=api_key)
        config = uvicorn.Config(
            app, host="127.0.0.1", port=args.port,
            access_log=False, log_level="warning",
        )
        print(f"LOCAL API ready at http://127.0.0.1:{args.port}")
        print("Only model=clickup-ui-current and one user message are supported.")
        print("No streaming, no token usage accounting; Ctrl+C to close.")
        server = uvicorn.Server(config)
        await server.serve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://app.clickup.com/")
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    api_key = os.environ.get("CLICKUP_GATEWAY_API_KEY", "")
    if len(api_key) < 24:
        parser.error(
            "Set CLICKUP_GATEWAY_API_KEY to a unique random value >=24 chars "
            "before starting; it will not be printed."
        )
    if not validate_clickup_app_url(args.url):
        parser.error("--url must be HTTPS app.clickup.com")
    if not 1024 <= args.port <= 65535 or not 5 <= args.timeout <= 600:
        parser.error("--port must be 1024..65535 and --timeout 5..600 seconds")
    try:
        asyncio.run(serve(args, api_key))
    except (PlaywrightError, GatewayUnavailableError, ValueError) as exc:
        print(f"Gateway startup failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
