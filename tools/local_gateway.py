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

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
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
from tools.brain_start_url import (
    choose_start_url,
    normalize_brain_start_url,
    remember_start_url,
)
from tools.router_compat import (
    RouterChatRequest, flatten_messages, make_chat_completion, make_buffered_sse,
)
from tools.session_lease import (
    ExclusiveSessionLease, SessionAlreadyClaimedError,
    SessionNotClaimedError, SessionAccessDeniedError,
)

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


def create_app(
    engine: PromptEngine, *, api_key: str, require_session: bool = False,
    router_mode: bool = False,
) -> FastAPI:
    """Build an app with an injectable engine for fully offline tests."""
    if len(api_key) < 24:
        raise ValueError("CLICKUP_GATEWAY_API_KEY must be at least 24 characters")
    if router_mode and require_session:
        raise ValueError(
            "Router mode uses a dedicated isolated worker and cannot require "
            "the custom owner header that router providers may omit."
        )
    app = FastAPI(
        title="ClickUp Brain UI Bridge (local experimental facade)",
        docs_url=None, redoc_url=None, openapi_url=None,
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"]
    )
    lease = ExclusiveSessionLease() if require_session else None

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

    def require_owner(
        x_clickup_session: str | None = Header(default=None, alias="X-ClickUp-Session"),
    ) -> None:
        if lease is None:
            return
        try:
            lease.check(x_clickup_session)
        except SessionNotClaimedError as exc:
            raise HTTPException(
                status_code=409,
                detail="Browser session has no owner; claim it first.",
            ) from exc
        except SessionAccessDeniedError as exc:
            raise HTTPException(
                status_code=403,
                detail="Incorrect or missing browser session capability.",
            ) from exc

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

    @app.post("/v1/session/claim", dependencies=[Depends(require_api_key)])
    def claim_session() -> dict:
        if lease is None:
            raise HTTPException(
                status_code=409, detail="Session leasing is disabled in legacy mode.",
            )
        if not engine.is_ready():
            raise HTTPException(status_code=503, detail="Browser is not ready.")
        try:
            secret = lease.claim()
        except SessionAlreadyClaimedError as exc:
            raise HTTPException(
                status_code=409,
                detail="Browser context already claimed; restart worker after inspection.",
            ) from exc
        return {
            "object": "browser.session",
            "session_token": secret,
            "policy": "single-owner-sticky-context",
            "note": "This is an API lease, not a new ClickUp conversation.",
        }

    @app.get("/v1/session/diagnostics", dependencies=[
        Depends(require_api_key), Depends(require_owner),
    ])
    def session_diagnostics() -> dict:
        # No workspace/conversation/AI result identifiers leave the process.
        return engine.session_diagnostics()

    async def run_one_prompt(text: str) -> str:
        if not engine.is_ready():
            raise HTTPException(
                status_code=503,
                detail="Browser session is not ready; open Brain UI first.",
            )
        if not text.strip():
            raise HTTPException(status_code=422, detail="Message cannot be blank.")
        try:
            return await engine.complete(text)
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

    if router_mode:
        @app.post("/v1/chat/completions", dependencies=[
            Depends(require_api_key),
        ])
        async def router_chat(request: RouterChatRequest):
            # A multi-message Chat Completions request is self-contained. A
            # fresh UI chat per request is MANDATORY to avoid cross-client
            # context pollution; do not weaken this requirement.
            if not getattr(engine, "new_chat_per_request", False):
                raise HTTPException(
                    status_code=503,
                    detail="Isolated new-chat browser worker required.",
                )
            try:
                prompt = flatten_messages(request.messages)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail="Compiled text transcript exceeds allowed size.",
                ) from exc
            answer = await run_one_prompt(prompt)
            if request.stream:
                # Buffered SSE is format-compatibility ONLY: the whole reply
                # arrives before frames are sent, no fabricated token deltas.
                return Response(
                    content=make_buffered_sse(answer),
                    media_type="text/event-stream",
                    headers={
                        "X-Stream-Mode": "buffered",
                        "Cache-Control": "no-store",
                    },
                )
            return make_chat_completion(answer)
    else:
        @app.post("/v1/chat/completions", dependencies=[
            Depends(require_api_key), Depends(require_owner),
        ])
        async def chat(request: ChatRequest) -> dict:
            return {
                **make_chat_completion(
                    await run_one_prompt(request.messages[0].content)
                ),
                "id": "chatcmpl-local-" + uuid4().hex,
            }

    return app


class LiveBrowserEngine:
    """One visible Chromium session. Requires manual login/readiness step."""

    def __init__(
        self, *, profile: Path, url: str, timeout: float = 120,
        strict_conversation: bool = False,
        new_chat_per_request: bool = False,
    ) -> None:
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
        self.strict_conversation = strict_conversation
        self.new_chat_per_request = new_chat_per_request

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

                # Router mode receives independent, self-contained HTTP
                # transcripts. A new UI conversation is required on EVERY call.
                # This uses a previously verified Brain landing route, not an
                # invented ClickUp backend endpoint or guessed New Chat button.
                if self.new_chat_per_request:
                    landing = normalize_brain_start_url(page.url)
                    await page.goto(
                        landing, wait_until="domcontentloaded", timeout=45_000
                    )
                    # Abort if ClickUp unexpectedly redirected to an existing
                    # conversation, instead of claiming context isolation.
                    location = urlsplit(page.url)
                    if (
                        location.query
                        or normalize_brain_start_url(page.url) != landing
                    ):
                        raise GatewayUnavailableError(
                            "Brain landing redirected to an existing conversation."
                        )
                    await page.locator(COMPOSER_CSS).wait_for(
                        state="visible", timeout=20_000
                    )
                    # Keep previous reply ID only for diagnostic equality.
                    # Router mode never uses strict_conversation; UI isolation
                    # is enforced by fresh landing navigation, not ID reset.

                # The current UI model/effort is selected manually before serving.
                # In legacy mode the browser retains chat context.
                self.bridge.arm()
                await _send_via_ui(page, prompt, COMPOSER_CSS, SEND_CSS)
                reply = await self.bridge.await_reply_created(timeout=self.timeout)
                if self.strict_conversation:
                    # In single-owner mode an unexpected switch to a new ClickUp
                    # conversation must not return as the same logical context.
                    # The UI send has already occurred: mark degraded, never retry.
                    if not reply.conversation_id:
                        raise GatewaySendError("WS reply lacks conversation ID.")
                    if (
                        self._last_conversation_id is not None
                        and reply.conversation_id != self._last_conversation_id
                    ):
                        raise GatewaySendError("UI conversation unexpectedly changed.")
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
    launch_url = choose_start_url(args.url)
    async with LiveBrowserEngine(
        profile=profile, url=launch_url, timeout=args.timeout,
        strict_conversation=args.require_session,
        new_chat_per_request=args.router_mode,
    ) as engine:
        print("Visible Chromium launched. Log in to your authorized Workspace.")
        print("Open ClickUp Brain Ask; select model and effort in the browser.")
        print("Finish any pending AI reply and close extra ClickUp tabs.")
        await asyncio.to_thread(
            input, "When ready, press ENTER to enable LOCAL API server: "
        )
        # Validate page before accepting an API request; no raw IDs are printed.
        page = select_brain_page(engine._context.pages)
        try:
            normalize_brain_start_url(page.url)
        except ValueError as exc:
            raise GatewayUnavailableError(
                "Navigate to the workspace Brain Ask page first."
            ) from exc
        # Persist only workspace Brain landing; NEVER save ?conversationId=...
        # This fixes Chromium reopening at Workspace Overview after a restart.
        remember_start_url(page.url)
        print("Brain landing page remembered locally for next gateway start.")
        engine.mark_ready()
        app = create_app(
            engine, api_key=api_key, require_session=args.require_session,
            router_mode=args.router_mode,
        )
        config = uvicorn.Config(
            app, host="127.0.0.1", port=args.port,
            access_log=False, log_level="warning",
        )
        print(f"LOCAL API ready at http://127.0.0.1:{args.port}")
        print("Only model=clickup-ui-current and one user message are supported.")
        if args.router_mode:
            print("9ROUTER BASIC MODE: isolated fresh Brain chat per request.")
            print("SSE is buffered after the reply-created event; no real token stream.")
            print("Only text, no native role hierarchy or tool calls.")
        if args.require_session:
            print("EXCLUSIVE MODE: POST /v1/session/claim first; "
                  "send X-ClickUp-Session on chat/diagnostics.")
            print("No session release: close and inspect/restart the browser "
                  "before assigning it to another owner.")
        else:
            print("LEGACY MODE: all authorized HTTP calls share browser history. "
                  "Do not expose this to other users.")
        print("No streaming, no token usage accounting; Ctrl+C to close.")
        server = uvicorn.Server(config)
        await server.serve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", default=None,
        help="Optional ClickUp URL; otherwise restore last verified Brain route",
    )
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument(
        "--router-mode", action="store_true",
        help="Basic OpenAI-compatible text/SSE facade for one local 9Router provider",
    )
    parser.add_argument(
        "--require-session", action="store_true",
        help="Require a one-time API lease for the sticky browser conversation",
    )
    args = parser.parse_args()
    api_key = os.environ.get("CLICKUP_GATEWAY_API_KEY", "")
    if len(api_key) < 24:
        parser.error(
            "Set CLICKUP_GATEWAY_API_KEY to a unique random value >=24 chars "
            "before starting; it will not be printed."
        )
    if args.url is not None and not validate_clickup_app_url(args.url):
        parser.error("--url must be HTTPS app.clickup.com")
    if args.router_mode and args.require_session:
        parser.error(
            "--router-mode and --require-session are mutually exclusive. "
            "Router providers may not send X-ClickUp-Session."
        )
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
