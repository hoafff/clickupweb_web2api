# 20 — 9Router → ClickUp Gateway → Brain²: Live JSON Acceptance

**Date:** 2026-10-28 · **Repository:** `hoafff/clickupweb_web2api`

## Objective / result

Demonstrate a complete authorized text-only request through:

```text
Client Python → local 9Router :20128
             → custom provider "brain/clickup-ui-current"
             → authenticated local Gateway :8787
             → Playwright persistent Chromium (signed-in user)
             → ClickUp Brain² UI submission
             → correlated WS reply-created event
             → HTTP JSON Chat Completions response to client
```

**LIVE JSON E2E: PASS (one short prompt).**

User-supplied Windows terminal proof:

```text
.\.venv\Scripts\python.exe tools\check_9router_path.py
9Router model discovery: PASS
9Router -> Brain Gateway -> ClickUp: PASS
Response: JSON (no true token-stream claim)
Reply characters: 3
Reply preview: OK
```

A previous `401 invalid_api_key` was eliminated when the operator replaced the incorrect `.local/ninerouter.key` (it had contained the Gateway upstream key) with a **client API key created by 9Router**. Two separate authentication roles are required:

- **9Router caller key:** local `.local/ninerouter.key`, issued by 9Router dashboard for access to `:20128`.
- **ClickUp Gateway upstream key:** local `.local/gateway.key`, configured in 9Router custom provider for access to `:8787`.
- **ClickUp browser authorization:** local persistent Chromium profile; never upload this directory to GitHub, CI, 9Router, or chat.

The working route does **not** prove real-time token streaming, end-of-generation signaling, complete OpenAI API compatibility, tool calling, model switching, multi-user isolation, permanent hosting, or the effectiveness of arbitrary model settings.

## Master Plan

| ID | Component | Acceptance condition | Status |
|---|---|---|---|
| R-01 | Custom 9Router model registration | `brain/clickup-ui-current` in 9Router `/v1/models` | **DONE — live** |
| R-02 | Two-stage keys | Client key accepted on :20128; provider key accepted on :8787 | **DONE — live** |
| R-03 | Basic Chat Completions JSON | One request routed through 9Router returns `OK` | **DONE — live** |
| R-04 | Buffered SSE through 9Router :20128 | `--stream` response decodes SSE + `[DONE]` | **DONE — live: OK (3 chars)** |
| R-05 | History through 9Router :20128 | Text transcript accepted, reply correlated in separate chat | **DONE — live: ALPHA (6 chars)** |
| R-06 | Long response integrity | Return sufficient length/inspect visible UI for missing content | **PARTIAL — live 606 chars / 200-min PASS; final stream marker NOT proven** |
| R-07 | Coding agent function calling | Genuine tool-call structure and tool-call results | **UNSUPPORTED** |
| R-08 | Isolated cloud worker | Re-login, lifecycle, rate-limit, authorization and service permission review | **NOT IMPLEMENTED** |

## Verification CLI — same Windows computer

Keep both 9Router (:20128) and ClickUp Gateway (`--router-mode`, :8787) running. After `git pull`, all commands below are run in **PowerShell 2**, do not require a Gateway restart, do not use `.ps1`, and use the separately stored 9Router client key. Each command **except `--models-only`** sends a genuine prompt and may use ClickUp allowance.

```powershell
cd E:\Toolss\clickuptoapi
git pull

# No model invocation
.\.venv\Scripts\python.exe tools\check_9router_path.py --models-only

# LIVE JSON already PASS; optional quick regression:
.\.venv\Scripts\python.exe tools\check_9router_path.py

# Next gate: buffered SSE all the way through 9Router
.\.venv\Scripts\python.exe tools\check_9router_path.py --stream

# Transcript mapping via 9Router
.\.venv\Scripts\python.exe tools\check_9router_path.py --history

# Check a longer reply. The length threshold is a smoke-test heuristic,
# NOT proof the model reached its true completion signal.
.\.venv\Scripts\python.exe tools\check_9router_path.py --prompt "Write five numbered sentences about HTTP and WebSocket, at least 15 words each." --min-reply-chars 200
```

The `--history` test passes a four-message transcript (`system`, `user`, `assistant`, `user`) to 9Router, then the Gateway serializes it as **ordinary text** into one fresh ClickUp Brain chat. It does **not** confer actual privileged system/developer message semantics.

The `--min-reply-chars` option rejects unexpectedly short output, without exposing private account keys. However, length alone cannot prove completeness. Compare the returned text to the visible ClickUp Brain reply for a known benign prompt. For non-ASCII tests, the script encodes JSON explicitly as UTF-8.

## Remaining issues and scope

1. An SSE **buffered** result is returned only after a reply-created WS event. Even if it passes via 9Router, it is not true token-by-token streaming. `finish_reason=null` reflects unverified completion.
2. The current HTTP facade supports text-only basic chat. **Do not assume it can substitute for coding agents requiring OpenAI/Anthropic tool calls**, system-role enforcement or true token streaming.
3. Gateway binds to `127.0.0.1` and requires the user's logged-in Chromium profile. 9Router and Gateway must be on the **same host** for loopback configuration; there is no production cloud deployment or unattended session refresh yet.
4. Keep 9Router client API key, Gateway key and ClickUp browser profile private; never paste them into issue reports or chat. Check the installed 9Router version, avoid public port exposure and respect upstream service policies.

## Next Action

Run the `--stream` and `--history` commands in sequence, then (optionally) the long-response integrity check. Report only safe terminal output, including any HTTP status and reply length. These are the next evidence gates before work on session recovery/packaging.


## 2026-10-28 — Live 9Router SSE, transcript and long reply acceptance

The researcher ran three real `check_9router_path.py` requests through **9Router :20128** (NOT only through the direct Gateway):

```text
--stream
9Router model discovery: PASS
9Router -> Brain Gateway -> ClickUp: PASS
Response: SSE (no true token-stream claim)
Reply characters: 3
Reply preview: OK

--history
9Router model discovery: PASS
9Router -> Brain Gateway -> ClickUp: PASS
Response: JSON (no true token-stream claim)
Reply characters: 6
Reply preview: ALPHA

--prompt "Write five numbered sentences about HTTP and WebSocket, at least 15 words each." --min-reply-chars 200
9Router model discovery: PASS
9Router -> Brain Gateway -> ClickUp: PASS
Response: JSON (no true token-stream claim)
Reply characters: 606
Reply preview: HTTP follows request-response model: client sends request, server returns response, then connection may close or idle. W
```

**Verified:** JSON + buffered SSE through 9Router, four-message text transcript mapping through 9Router, and one 606-character response returned over the complete HTTP/Browser/WS path. Long-response acceptance was **threshold-only**; the supplied log contains only the first 120 characters of the 606-character response. It does not prove the response ends at a natural generation boundary or that each requested sentence was present.

**Critical protocol finding from source audit:** `BrainBrowserBridge.await_reply_created` resolves on `chatCommentCreated` correlated to `aiConversationStarted`. Neither event proves the assistant finished generation. `make_buffered_sse` emits `[DONE]` because the HTTP wrapper's buffered response ends; that **is not a verified upstream inference-completion event**. The code intentionally leaves `finish_reason=null` and does not invent token usage. Native function/tool calling and true streaming remain unsupported.

### Optional reproducible reply-end marker check (new)

`tools/check_9router_path.py` now accepts `--expect-suffix`, an independent transport/content smoke check. It must match the response's trailing characters; the marker is not a secret and should be a simple printable ASCII test string.

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe tools\check_9router_path.py --prompt "Write five numbered sentences explaining HTTP and WebSocket, at least 15 words each. The final text of your response must be exactly END_BRAIN_TEST (without punctuation or any text after it)." --min-reply-chars 200 --expect-suffix END_BRAIN_TEST
```

This performs **one more real request**, may consume ClickUp allowance, and does **not** require restarting the healthy Gateway or 9Router processes (the new feature is entirely client-side). A match provides stronger evidence the terminal bytes of the requested content passed through the bridge. A mismatch could mean early capture **or** that the model simply ignored the requested marker. In either case it is **not sufficient** evidence of a true server-side end-of-generation signal.

### Remaining priorities

1. Research actual ClickUp generation-complete signaling from an authorized trace or reproducible browser read-only UI-state observation; avoid guessing undocumented backend endpoints. Require an independently observed terminal condition before advertising `finish_reason="stop"` or real token streaming.
2. Test controlled restart, browser/profile recovery and session expiry. This is required for unattended operation on a Windows service or Linux browser worker; **not yet verified**.
3. Evaluate actual coding-agent request shapes, especially `tools/tool_choice`, as supported inputs only after native tool results can be represented faithfully. Current `422` reject behavior remains correct.
4. Remain local-only for now; do not expose `127.0.0.1:8787` publicly or copy the authenticated Chromium profile to GitHub/CI.
