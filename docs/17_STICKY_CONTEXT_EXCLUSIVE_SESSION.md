# 17 — G-03: Proven Sticky Chat and Exclusive Browser Session Lease

**Date:** 2026-10-28 · **Basis:** researcher-provided real Windows terminal output + source inspection + synthetic CI tests. This implementation only controls an **authorized localhost browser UI session**. It is **not** direct ClickUp inference API, cloud deployment or multi-tenant account isolation.

## Objective and findings

**Live G-03 verified (two sequential HTTP requests):**

| Observation | Value |
|---|---|
| Request #1 | `Reply with the word ALPHA only.` → `ALPHA` |
| Request #2 | `What word did I ask you to say in my previous message?` → `You asked me to say ALPHA.` |
| `completed_replies` | 2 |
| `same_conversation_pairs` | 1 |
| `different_conversation_pairs` | 0 |
| `last_relation` | `same` |

Interpretation: The observed **two WS reply `conversation_id` values match** and the assistant's second answer references the first request. Both facts support **sticky context** in this browser session. **They do not prove all future model/context behavior**, stateless semantics, the underlying inference backend or a supported upstream API.

**Risk found:** The legacy bearer-authenticated HTTP facade reuses the same UI conversation for ALL clients with access to that one API key, whether or not they intended to share history. That is unacceptable for arbitrary multi-user cloud exposure.

## Master Plan and status

| ID | Component | Action | Acceptance | Status |
|---|---|---|---|---|
| G-03a | Live HTTP diagnostics | Confirm sequential WS reply IDs equal | `same_conversation_pairs=1` | **DONE (live)** |
| G-03b | `tools/session_lease.py` | Exclusive owner token, once per browser-worker lifetime | Race/authorization tests | **DONE (mock)** |
| G-03c | `tools/local_gateway.py` | Optional `--require-session`, strict chat owner and continuity | Unclaimed/wrong-token cannot chat; unexpected changed conversation rejects | **DONE (mock)** |
| G-03d | `tools/send_gateway_request.py` | Claim and use session token from Git-ignored local file without PowerShell `.ps1` | Synthetic HTTP and token test | **DONE (mock)** |
| G-03e | Live strict-mode run | Claim owner, send two messages, verify diagnostics | 2 replies, same relation, no ID leak | **DONE (LIVE)** |
| G-03f | Fresh-chat isolation | Discover and validate New Chat UI workflow | New conversation created deliberately and independently | **BLOCKED: DOM not yet verified** |
| G-04 | Browser/cloud lifecycle | Session login/reconnect/restart and worker packaging | Authorized remote worker smoke test | **TODO** |

## Design and security properties

### Legacy mode — unchanged

```powershell
.\.venv\Scripts\python.exe tools\local_gateway.py --port 8787
```

Existing `/v1/chat/completions` request format continues to work. This legacy mode **shares one UI conversation** and is for a **single trusted local operator only**.

### Exclusive mode — opt-in, still local

```powershell
.\.venv\Scripts\python.exe tools\local_gateway.py --port 8787 --require-session
```

- Requires existing bearer API key for `POST /v1/session/claim`; gateway issues **one** random 32-byte capability (base64 URL-safe).
- `POST /v1/chat/completions` and `GET /v1/session/diagnostics` additionally require HTTP `X-ClickUp-Session` equal to the claimed capability.
- Calls without owner *before claim*: HTTP **409**. Wrong/missing owner *after claim*: HTTP **403**. Any later claim: HTTP **409**; no replacement/release in current worker process.
- The already validated Browser Adapter is reused. Consecutive replies must have the **same nonempty WS `conversation_id`**. If it changes unexpectedly, the gateway **does not return the second reply**, marks the browser worker degraded, and requires operator inspection/restart.
- Lease token and WS IDs stay in memory (except **locally saved owner token** as described below). No raw ID is printed by the client or diagnostics. `X-ClickUp-Session` is distinct from the actual ClickUp session/access token.
- Single owner lease **does not create a new ClickUp chat** and does not establish multi-tenant isolation. It simply prevents a second caller lacking the lease token from posting into the same UI conversation.
- A caller who knows the gateway bearer key can try to claim the unclaimed worker first, causing a denial of service. Hence the key must remain private, and a public cloud deployment requires real identity/authorization and network protections.

## Windows PowerShell 1 — restart current gateway and enable strict owner mode

After the prior gateway has completed all work, press `Ctrl+C` in PowerShell 1 and close that Chromium. Then:

```powershell
cd E:\Toolss\clickuptoapi
git pull
$env:CLICKUP_GATEWAY_API_KEY = (Get-Content -Raw .local\gateway.key).Trim()
.\.venv\Scripts\python.exe tools\local_gateway.py --port 8787 --require-session
```

Open authorized ClickUp Brain² Ask, choose the model/effort, ensure no background generation, press Enter at the gateway terminal. **Do not manually change chats while running this strict test.**

## Windows PowerShell 2 — claim once and send two controlled requests

Uses Python (not `.ps1`, so no PowerShell ExecutionPolicy issue). After pulling the same code:

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe tools\send_gateway_request.py --claim-session
.\.venv\Scripts\python.exe tools\send_gateway_request.py --prompt "Reply with the word ALPHA only."
.\.venv\Scripts\python.exe tools\send_gateway_request.py --prompt "What word did I ask you to say in my previous message?"
.\.venv\Scripts\python.exe tools\send_gateway_request.py --diagnostics
```

First command calls `POST /v1/session/claim` and saves the owner token under **`.local/browser-owner.key`** (Git-ignored; plaintext sensitive; Windows inherits local directory ACL, Linux uses `0600` file mode). It prints confirmation **without revealing the token**. Subsequent commands read this file and add `X-ClickUp-Session` automatically. Do not upload or screenshot the token file. If the file already exists from a prior test, **do not overwrite it while any worker may be active**. Stop/restart the old gateway first and remove stale `.local/browser-owner.key` before claiming a different new worker.

**Actual strict live result verified from the researcher:** `--claim-session` succeeded, request #1 returned `ALPHA`, request #2 returned `You asked me to say ALPHA.`, and diagnostics returned `completed_replies=2`, `same_conversation_pairs=1`, `different_conversation_pairs=0`, `last_relation=same`. This confirms correct one-owner sticky HTTP/WS operation for two consecutive prompts. The strict mode has **not** been tested under malicious/unauthorized remote traffic or cloud workloads.

## Remaining blockers for real cloud hosting

1. **No new-chat mechanism verified.** To isolate unrelated client histories, every tenant needs its own authenticated browser worker/profile, and new chat needs a verified UI navigation/creation procedure, not an unvalidated URL guess.
2. **No unattended login/recovery.** Current Chromium must be visible and manually logged in. Linux headless/virtual-display and persisted session use are not validated. Never commit/copy an authenticated profile into a public repo or CI artifact.
3. **No remote exposure security.** Current server binds `127.0.0.1` only. A public tunnel would bypass the intended network boundary. Need TLS, per-user authentication, worker isolation, abuse/rate limits, quota controls and policies/permission review first.
4. **No full model or stream semantics.** This API accepts one `user` message per HTTP call, uses whatever model/effort is selected in the UI, and returns `chatCommentCreated` text, not a confirmed end-of-generation SSE event.

## Verification

Run `python -m unittest discover -s tests -v`. CI on `ubuntu-latest` and `windows-latest` exercises lease races, wrong/absent tokens, strict conversation switching, and a synthetic local HTTP client. These do **not** send a real prompt. The next live gate is the strict-mode PowerShell sequence above.


## 2026-10-28 — Why Chromium opened Workspace Overview, and root fix

The user observed two screenshots: Chromium initially displayed Workspace Overview, then manually clicked through to a Brain² conversation. The gateway used `--url` default `https://app.clickup.com/`, and each startup explicitly called `page.goto(self.url)`. The root path redirects to Workspace Overview. Playwright's persistent browser login **does not** imply restoring the last visited URL; our own `page.goto('/')` overwrote that route.

Added `tools/brain_start_url.py`: after the operator navigates to a verified `https://app.clickup.com/{numeric-workspace-id}/ai/brain` page and confirms readiness, `local_gateway.py` stores **only** that landing URL in `.local/brain-start-url.txt` (Git-ignored). It explicitly drops any `?conversationId=...`, fragments, auth tokens and other query parameters. When `--url` is omitted next startup, it prefers the stored route instead of root.

**Limitations:** On the first launch after installing this update, there is no saved file yet, so the browser **may still open Overview once**. Navigate manually to Brain and press Enter; the following launch will start directly at Brain. A landing route intentionally **does not reopen a specific old conversation**. If the operator must select an existing chat, choose it manually after navigating to Brain. The URL file contains workspace routing metadata; do not upload it.

The user can also launch Brain directly on the first updated startup with explicit `--url` using the Brain path copied from their own authorized browser, omitting `?conversationId=...`:

```powershell
.\.venv\Scripts\python.exe tools\local_gateway.py --port 8787 --require-session --url 'https://app.clickup.com/<WORKSPACE_ID>/ai/brain'
```

Replace the placeholder with the numeric workspace ID from **their own** address bar. No workspace IDs or live credentials are hardcoded in the repository. The verified landing will then be remembered for later startups.

**Exclusive owner token restart caveat:** `.local/browser-owner.key` from a stopped previous worker is no longer valid after a new worker is started. Never send it to a different worker or share it. Stop the old worker first, remove only that **stale token file** on the local computer and claim a fresh one. The main `.local/gateway.key` remains unchanged. Do not delete the browser profile.
