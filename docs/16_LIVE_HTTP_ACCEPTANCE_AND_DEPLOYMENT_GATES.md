# 16 — Live HTTP E2E Acceptance & Cloud Readiness Gates

**Date:** 2026-10-28 · **Scope:** Authorized ClickUp Brain² browser UI research · **Verified milestone:** one localhost HTTP request returned `OK` via the logged-in browser adapter. This note **does not** claim an independent ClickUp API or cloud operation.

## 1. Objective

Turn the validated **single-process, single-account, visible-browser localhost proof of concept** into a reliable gateway in stages, without misrepresenting the capabilities of the underlying UI. Ultimate deployment goal: run on a permitted always-on host without requiring the researcher's Windows desktop to stay online.

## 2. Verified findings

| ID | Evidence from actual run | Status |
|---|---|---|
| E-01 | V3 WS offline replay: 8 AI starts ↔ 8 matched reply-created comments | VERIFIED (user terminal) |
| E-02 | Manual live UI send: one AI response `OK`, 12 WS JSON frames | VERIFIED (user terminal) |
| E-03 | Live auto UI send: Playwright input and Send click → one AI response `OK`, 15 WS JSON frames | VERIFIED (user terminal) |
| E-04 | `local_gateway.py` starts listening on `127.0.0.1:8787` | VERIFIED (user terminal) |
| E-05 | HTTP request with PowerShell `-Body` string failed JSON parsing | OBSERVED, exact bytes unknown |
| E-06 | Sending `[Text.Encoding]::UTF8.GetBytes($body)` with explicit UTF-8 header returned `choices[0].message.content=OK` | **VERIFIED LIVE HTTP E2E** |
| E-07 | `tools/send_gateway_request.ps1` works with mocked HTTP in Windows PowerShell 5.1 CI | VERIFIED (CI); not yet user-run live |
| E-08 | Model routing, token streaming, multi-message context, cloud session restore | NOT VERIFIED |

## 3. Master Plan

| Task ID | Component | Action | Acceptance criterion | Status |
|---|---|---|---|---|
| G-01 | `tools/local_gateway.py` | Authenticated localhost JSON request → UI → WS reply | Live request returns `OK` | **DONE** |
| G-02 | Windows HTTP client | Explicit UTF-8 bytes, no secret on console | Live non-ASCII payload accepted; Windows PowerShell mock CI passes | **DONE** |
| G-03 | Browser session state | Authenticated diagnostics compare consecutive replies' conversation IDs in memory without printing IDs | Mock tests + 2 live requests and observed `same/different` classification | **IN PROGRESS — diagnostics implemented, live unverified** |
| G-04 | Browser worker resilience | Observe browser/tab disappearance, login expiry and WS reconnect without silently treating session as ready | Controlled offline tests + authorized live recovery drill | **TODO** |
| G-05 | API error contract | Explicit timeout, 401, 429, 502, 503, cancellation, no duplicate UI submissions | Regression tests for all cases; safe log output | **IN PROGRESS** |
| G-06 | Model/effort UI selection | Verified DOM selectors and explicit confirmation for each supported model/effort | Two controlled model/effort live sends + HTTP request verification | **TODO** |
| G-07 | Deployment packaging | Prepare Linux Chromium + virtual display or verified headless mode (only after testing), health checks, restart/shutdown | Integration test on a non-desktop authorized host | **BLOCKED on G-03/G-04** |
| G-08 | Credential/session isolation | Keep ClickUp profile secret outside Git, encrypted host storage, per-identity worker, access controls | Isolation, revocation/re-auth, backup/restore tests | **BLOCKED on design and permission review** |
| G-09 | Cloud API access | TLS reverse proxy, bounded ingress, rate limits, allowlist and monitoring | Remote authorized test with no exposed profile or raw session tokens | **BLOCKED on G-07/G-08** |
| G-10 | Genuine streaming | Identify any actual text-delta and completion events before offering SSE | Reproducible live events and protocol tests | **UNVERIFIED** |

## 4. Proposed deployment architecture (design only)

```text
Authorized client
      |
      | HTTPS + app-issued key + rate limit
      v
API gateway (stateless request validation + request IDs)
      |
      v
Bounded single-tenant job queue / worker manager
      |
      v
Dedicated Playwright Browser Worker (one ClickUp login/profile per worker)
      |
      +-- ClickUp Brain UI: send via verified DOM
      +-- WebSocket listener + ConversationEventCorrelator
      |
      v
HTTP response (single JSON completion, no fabricated usage)
```

**Design principle:** Keep `ClickUp session / browser profile` inside the worker's protected state; **never** store in public GitHub, CI artifacts, raw trace repositories, or send to another user's session. Each account must have its own worker and request queue. Queue/cancel semantics must prevent an expired HTTP request from being replayed as a duplicate ClickUp message.

**Hosting is not yet verified:** A headless browser, hosted filesystem, renewal of login sessions, service permitted use, model selection and any cost/rate limits all need actual validation. GitHub Actions CI success alone is **not evidence of production hosting**. The service currently binds **only** to localhost and requires a visible, manually logged-in browser.

## 5. Next most valuable live acceptance test

Without restarting the healthy gateway or exposing secrets, use the UTF-8 PowerShell client for two **controlled, non-sensitive** prompts in sequence, waiting for the first to finish before sending the second. Example sequence:

- Request A: `Reply with exactly the word ALPHA.`
- Request B: `What exact word did I ask you to say in my immediately previous message? Answer with that word only.`

Observe whether the second answer contains context from the previous request; also observe whether the visible UI remains in the same chat. If A returns `ALPHA` and B returns a context-dependent value, the browser may be reusing chat state. **This is only a diagnostic; model behavior is probabilistic and cannot prove context isolation by itself.** A stronger future test should observe actual conversation IDs from safe in-memory events.

After updating the repo and restarting the local gateway (needed for this NEW endpoint), use:

```powershell
$env:CLICKUP_GATEWAY_API_KEY = (Get-Content -Raw .local\gateway.key).Trim()
$headers = @{ Authorization = "Bearer $env:CLICKUP_GATEWAY_API_KEY" }
Invoke-RestMethod -Uri "http://127.0.0.1:8787/v1/session/diagnostics" -Headers $headers
```

The response has only `completed_replies`, `same_conversation_pairs`, `different_conversation_pairs`, and `last_relation` (`first`, `same`, `different`, `unknown`, `unobserved`). **No IDs leave the process.** The first reply is `first`; after a second successful reply the relation to the previous one becomes `same` or `different` when both IDs are available. **This classifies WS conversation IDs, not whether the model actually remembered prior content.**

Before enabling multi-user or cloud deployment, convert conversation state into an explicit API contract: either new chat per request or a validated `conversation_id` bound to a single identity. Do not market the present one-user-message facade as a stateless OpenAI API.

## 6. Security and limitations

The first HTTP E2E pass used `model=clickup-ui-current`, which means **whatever model/effort the operator chose in the UI**. No HTTP model routing, `stream=true`, file attachments, system/developer roles, token usage or guaranteed final completion are supported. The output event `chatCommentCreated` indicates comment creation, not necessarily completed long-running generation. Never expose `127.0.0.1:8787` through a public tunnel until TLS, auth, worker separation, quota and browser-session security are implemented and independently reviewed.

## 7. Next Action

**Prioritize G-03 (explicit chat lifecycle and context isolation)**. It is a correctness prerequisite for a service that could later handle multiple remote clients. Then G-04/G-05 (recoverable session and error semantics); only afterwards attempt G-07/G-08 cloud worker packaging.
