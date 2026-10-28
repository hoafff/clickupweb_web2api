# 18 — 9Router / OpenAI-compatible Basic Text Mode

**Status:** Implemented and synthetic CI tests PASS (Windows + Ubuntu). **Live gateway router-mode validated** for JSON text chat, history-as-text, and 3 separate `conversation_id` responses. **SSE smoke CLI failed once despite a completed upstream reply; the client-side response-header casing issue has been fixed and awaits a repeat live smoke test.** **NOT YET verified through an actual 9Router process.** The user's previous local browser Gateway and `--require-session` live tests PASS. 9Router-specific flow still requires a controlled live smoke test.

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

## 28 October 2026 — Live router-mode result and SSE smoke checker fix

Researcher supplied real PowerShell results:

```text
check_router_compat.py           -> Models PASS; JSON PASS; reply OK
check_router_compat.py --stream  -> Models PASS; generic smoke-test failure
check_router_compat.py --history -> Models PASS; JSON PASS; reply ALPHA
send_gateway_request.py --diagnostics
  completed_replies: 3
  same_conversation_pairs: 0
  different_conversation_pairs: 2
  last_relation: different
```

**Evidence:** Three AI replies were correlated, and three distinct consecutive WS `conversation_id` values occurred. JSON and history both worked live. The SSE command's error was **not** evidence that the ClickUp UI send or reply correlation failed: the diagnostics count included it.

**Root cause found in the code:** The smoke client previously converted HTTP headers to a plain Python `dict(response.headers)`, then used `headers.get("X-Stream-Mode")`. HTTP header names are **case-insensitive**, while plain dictionary keys are case-sensitive. Uvicorn commonly serializes the server response as lowercase `x-stream-mode`. Thus the CLI incorrectly reported failure **after receiving a valid response**.

**Patch:** `tools/check_router_compat.py` now lowercases response header names and checks `x-stream-mode` plus `content-type`. `tests/test_check_router_compat.py` drives the full CLI against a synthetic localhost HTTP server that deliberately sends lowercase headers, covering JSON, history and buffered SSE, on Windows and Linux.

**Minimal retry without restarting a healthy browser gateway:**

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe tools\check_router_compat.py --stream
.\.venv\Scripts\python.exe tools\send_gateway_request.py --diagnostics
```

`git pull` changes the CLI checker for the **next command invocation**, so this specific fix does not require a gateway restart. The `--stream` smoke test sends **one additional real prompt** and may use account credits. It should say `Buffered SSE: PASS (NOT real token-level streaming)`. If it still fails, investigate the actual response status/headers/SSE wire using a privacy-safe, allowlisted diagnostic, rather than assuming ClickUp returned no answer.

**9Router itself is still untested.** The gateway can provide only buffered SSE from the observed reply-created event, and no tool calling/true token-level streaming; verify the installed 9Router build and the selected client before relying on it.


## 2026-10-28 — Router-mode live acceptance passed (gateway only)

The operator's actual local log confirms:

```text
check_router_compat.py --stream
Models endpoint: PASS (clickup-ui-current)
Buffered SSE: PASS (NOT real token-level streaming)
Reply characters: 3
Reply preview: OK

send_gateway_request.py --diagnostics
completed_replies: 4
same_conversation_pairs: 0
different_conversation_pairs: 3
last_relation: different
```

**All four gateway smoke runs (JSON, SSE, history and new-chat separation) have now been confirmed live.** This confirms **port 8787 Gateway** behavior, but there has not yet been a confirmed request routed **through 9Router port 20128**.

### Actual 9Router-through-gateway acceptance

First configure the 9Router custom provider node, its **persistent upstream API-key connection**, and a separate **9Router client API key**. These are separate credentials:

| Flow | Credential |
|---|---|
| 9Router → Brain Gateway `:8787` | Contents of `.local/gateway.key` (upstream key) |
| CLI client → 9Router `:20128` | API key generated by **9Router dashboard**; optionally store in `.local/ninerouter.key` |
| Playwright → ClickUp | Existing authorized browser profile; do **not** export or share it |

On the same Windows host, open `http://127.0.0.1:20128/dashboard/providers` and find **Custom Providers → Add OpenAI Compatible**. Enter:

- Name: `ClickUp Brain Local`.
- Prefix: `brain`.
- API type: `chat` / **Chat Completions**, **not** Responses API.
- Base URL: `http://127.0.0.1:8787/v1`.
- Model ID (if requested): `clickup-ui-current`.
- Upstream API key: the existing Gateway key (never paste into chat or source code).

**Important:** The **Check/Test** action can validate the key but does not necessarily persist the upstream connection. Save the provider node, then add/save its **API key connection** separately in 9Router and enable the model. Also confirm 9Router runs as a local Windows process. If 9Router runs in Docker/cloud, `127.0.0.1:8787` inside that process/container is **not** your Windows host's Gateway; do not open the Gateway publicly as a workaround.

Next, open the local 9Router API Keys page. On **PowerShell 2**, choose one of these credential methods:

```powershell
cd E:\Toolss\clickuptoapi
git pull

# If 9Router requires a key to call /v1, save the DOWNSTREAM
# 9Router client key, *NOT* the ClickUp Gateway key:
.\.venv\Scripts\python.exe tools\check_9router_path.py --save-key
```

The terminal prompts for the secret with hidden input and stores it in Git-ignored `.local/ninerouter.key`. If local 9Router does not require a key, skip `--save-key` and try `--models-only`. The key is never printed or committed.

Then test:

```powershell
# Discovery only: no prompt sent
.\.venv\Scripts\python.exe tools\check_9router_path.py --models-only

# ONE genuine routed chat through 20128 → 8787 → ClickUp
.\.venv\Scripts\python.exe tools\check_9router_path.py

# Optional: routed SSE test (also sends a real ClickUp prompt)
.\.venv\Scripts\python.exe tools\check_9router_path.py --stream
```

Expected if successfully configured: `brain/clickup-ui-current` advertised in 9Router model list, followed by `9Router -> Brain Gateway -> ClickUp: PASS` and a reply preview such as `OK`. **These expected messages are not yet live-verified through 9Router.** Use the 9Router dashboard request log and Gateway/browser diagnostics if 9Router rejects model routing or adds unsupported options.

### Compatibility notes from current 9Router documentation

Current 9Router public documentation uses local `/v1` on port `20128`, and 9Router custom OpenAI-compatible providers generally use prefixed model IDs, such as `brain/clickup-ui-current`. Some releases or configurations default missing `stream` to true, so `check_9router_path.py` always supplies **explicit `stream: false`** for JSON and `stream: true` for SSE, with a matching `Accept` header. This addresses a known interoperability issue but does not establish 9Router tool-calling support.

Reference: https://docs.9router.com/ and https://github.com/decolua/9router ; see issues #1260 and #4122 for stream default behavior. Actual provider UI field labels and authentication vary by installed version.


### Security preflight for local 9Router

Check the 9Router version before wiring in a Browser worker:

```powershell
npm list -g 9router --depth=0
```

Historically some 9Router versions had localhost-authentication bypass issues (GHSA-86m2-fcxq-5q7c / CVE-2026-55641 and GHSA-5mj8-gf6m-fhw8 / CVE-2026-56681). Public advisories report fixes in recent releases; **do not assume the installed copy is patched without checking**. Restrict both processes to loopback, do not expose 20128 or 8787 on the LAN/public Internet, and maintain separate secrets for 9Router and the Brain Gateway. Relevant public advisories: https://github.com/advisories/GHSA-86m2-fcxq-5q7c and https://github.com/advisories/GHSA-5mj8-gf6m-fhw8.

If running the CLI version of 9Router with an appropriate flag, prefer `9router --host 127.0.0.1` after checking the installed version's help. Do **not** change a functioning service's bind setting or upgrade npm mid-test without first securing its local dashboard configuration and reviewing the runtime.
