# 18 — 9Router / OpenAI-compatible Basic Text Mode

**Status:** Implemented and synthetic CI tests PASS (Windows + Ubuntu). **NOT YET verified through an actual user's 9Router process.** The user's previous local browser Gateway and `--require-session` live tests PASS. 9Router-specific flow still requires a controlled live smoke test.

## Objective, findings and design decision

9Router supports OpenAI-compatible **custom provider nodes** and chat-completions routing. A typical 9Router client may send multiple chat messages and `stream=true`, while the previously implemented Brain bridge required one `role=user` message and `stream=false`. Also, 9Router provider nodes normally use `Authorization: Bearer` but cannot be assumed to forward proprietary `X-ClickUp-Session` headers.

We implemented a **separate opt-in mode** for **one locally trusted 9Router process**. The legacy/strict-owner paths remain unchanged.

```text
OpenAI-compatible text-only client
             |
     9Router localhost :20128/v1
             |
     Custom OpenAI Compatible provider
     Prefix: brain; API type: Chat Completions
             |
  Brain Gateway localhost :8787/v1
             |
  API key / one worker / one request at a time
             |
  Open Brain landing in existing authorized Chromium
             |
  Create one new Brain chat via UI by sending one prompt
             |
  WS aiConversationStarted + chatCommentCreated
             |
  HTTP ChatCompletion JSON or buffered SSE
```

**Security boundary:** The API is still bound to `127.0.0.1`; no public tunnel, anonymous use, credential sharing or per-tenant browser isolation. Respect ClickUp's account limits and permitted use. A new UI chat for each request does not bypass upstream quotas or authenticate another user.

## Task progress

| ID | File/component | Definition of done | Status |
|---|---|---|---|
| R-01 | `tools/router_compat.py` | Text-only OpenAI schema; explicit conversation transcript mapping | DONE (CI) |
| R-02 | `tools/local_gateway.py --router-mode` | Fresh Brain landing navigation **before each request** | DONE (CI), live unverified |
| R-03 | `tools/router_compat.py` | JSON and `stream=true` buffered SSE frames | DONE (CI), live unverified |
| R-04 | `tests/test_router_compat.py` | Auth, role history, invalid tools/images, SSE, isolation, redirect fail-closed | DONE |
| R-05 | `tools/check_router_compat.py` | Direct local HTTP smoke test without 9Router | IMPLEMENTED, live TODO |
| R-06 | 9Router custom node | One request from 9Router dashboard through Brain Gateway | TODO |
| R-07 | Live model switching, true streaming and tool calls | Verified upstream protocol and IDE integration | NOT SUPPORTED |
| R-08 | Cloud worker/re-auth | Permitted remote Playwright session, worker lifecycle, TLS | NOT IMPLEMENTED |

## What is supported

| Request feature | Behavior |
|---|---|
| `GET /v1/models` | One alias `clickup-ui-current` |
| `POST /v1/chat/completions` | Text-only request |
| `messages` | Final message must be `role=user`; earlier text messages can be system/developer/user/assistant |
| Multiple messages | Serialized into one **plain-text transcript** inside a NEW Brain chat; this is NOT native system/developer instruction hierarchy |
| `stream=false` | OpenAI-shaped JSON reply |
| `stream=true` | **Buffered SSE**: waits for full `chatCommentCreated` reply then returns 3 chunks and `[DONE]`, header `X-Stream-Mode: buffered`; NOT live token streaming |
| Tools/function-calling, tool results, images, audio, JSON mode, sampling parameters, embeddings | **422** (unsupported), not silently ignored |
| Requests in parallel | One browser at a time; additional requests receive 429 |
| Request context | Browser navigates to canonical Brain landing for **each** request, never attaches to previous conversation via `conversationId` |
| Model selection | The model/effort manually chosen in ClickUp UI; alias does not enforce a specific server model |
| Token usage/finish reason | No fabricated token counts; `finish_reason=null` because only `chatCommentCreated` is known |
| Browser failure/timeout | 502/503; worker degrades; do not retry blindly because message may already have been sent |

**Compatibility is intentionally basic.** Most coding agents require tool calls and sometimes real streaming, so **even if 9Router routes a basic text prompt successfully, this is not a drop-in replacement for Claude Code/Codex agent workflows.**

## Setup, PowerShell 1 — run dedicated Brain gateway

Stop current gateway with `Ctrl+C`, close its Chromium; use the same existing, authorized local browser profile. **Do not remove** `.local/gateway.key` or `.local/browser-profile/`.

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe -m pip install -r requirements-gateway.txt
$env:CLICKUP_GATEWAY_API_KEY = (Get-Content -Raw .local\gateway.key).Trim()
.\.venv\Scripts\python.exe tools\local_gateway.py --port 8787 --router-mode
```

Chromium opens the remembered Brain landing; ensure you are signed in, choose desired model/effort, no earlier generation is running. Press Enter in PowerShell 1. The gateway listens at `http://127.0.0.1:8787`.

`--router-mode` CANNOT be combined with `--require-session`. This is intentional, because the provider may not forward `X-ClickUp-Session`. The HTTP Bearer API key remains mandatory.

## Verify the gateway BEFORE adding it to 9Router (PowerShell 2)

```powershell
cd E:\Toolss\clickuptoapi
.\.venv\Scripts\python.exe tools\check_router_compat.py
.\.venv\Scripts\python.exe tools\check_router_compat.py --stream
.\.venv\Scripts\python.exe tools\check_router_compat.py --history
.\.venv\Scripts\python.exe tools\send_gateway_request.py --diagnostics
```

Each smoke command except `--diagnostics` sends **one real ClickUp Brain request** and may consume account allowance. Do not run rapidly or in loops. Browser should show separate new chats after the three requests. Diagnostics should observe different `conversation_id` values if ClickUp actually creates independent chats. **That precise live behavior still requires verification**.

## 9Router custom provider node (same Windows machine)

Open your **local** 9Router dashboard, often `http://127.0.0.1:20128/dashboard/providers`. Depending on installed version the control may be **Custom Providers / Provider Nodes → Add OpenAI Compatible**.

| Setting | Enter |
|---|---|
| Name | `ClickUp Brain Local` |
| Prefix | `brain` (9Router model prefix, not a ClickUp model name) |
| API type | **Chat Completions** (NOT Responses API) |
| Base URL | `http://127.0.0.1:8787/v1` |
| API key | Same local key stored in `.local/gateway.key`; enter in 9Router **UI**, do not post it in chat |
| Model ID | `clickup-ui-current` |
| Exposed model (likely) | `brain/clickup-ui-current`; verify using 9Router's own `GET /v1/models` |

**Important:** Some 9Router builds separate the *provider node* (host/base URL) from the *API-key connection*. After creating the custom node, add/save the associated key connection too. The provider's **Check** button may validate `/v1/models` or perform a billable/sensitive chat request; verify what it does before repeatedly clicking.

### Common setup pitfalls

- If the provider is added to **cloud 9Router**, `127.0.0.1:8787` refers to the *cloud server itself*, not your Windows PC. This procedure requires both processes on **the same host**; do not expose the browser gateway through a public tunnel.
- Do not enter `/v1/chat/completions` as Base URL; the 9Router provider appends `/chat/completions`.
- Do not provide a fake Claude Opus model ID. The route exposes only `clickup-ui-current` (whatever model ClickUp UI currently selected).
- If a 9Router request uses tool calls, images or unsupported parameters, the gateway returns **422** by design. This is not a license or authentication failure.
- If it reports 429, the browser worker is busy: **avoid blind retry** because ClickUp messages are not idempotent.
- If it reports 502/503, inspect browser status; the worker is deliberately degraded after an ambiguous UI operation.
- If the first 9Router request returns valid basic text, that verifies only the text-only path. Check whether streaming and CLI agent tool-calling demands additional unsupported features separately.

## Security and compliance

Keep credentials under Git-ignored `.local/`, and treat provider data stored in 9Router as sensitive. The browser's persistent profile belongs only to the authorized user; do not sync, upload, share or reproduce it in CI. No rate-limit evasion, account sharing, multi-tenant server hosting or production tool-calling is claimed.

## Sources for 9Router configuration

9Router public docs and repository describe custom OpenAI-compatible provider nodes and local `/v1` integrations. The exact dashboard labels and model-prefix behavior may vary by version; source-code confirmation and live testing are needed before claiming complete 9Router integration.
