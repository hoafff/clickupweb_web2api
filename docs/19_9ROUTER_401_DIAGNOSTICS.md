# 19 — Troubleshoot HTTP 401 between 9Router (:20128) and ClickUp Gateway (:8787)

**State (2026-10-28):** Direct Gateway router-mode is live-verified: JSON, buffered SSE, history-text and four separate Brain conversations. 9Router `GET /v1/models` advertises `brain/clickup-ui-current` among 94 model IDs. However **both** JSON and SSE chat calls **through port 20128** return HTTP 401. Root cause **not yet verified**, because the original checker deliberately hid the error body.

## Objective and evidence

| Layer | Observed | Meaning |
|---|---|---|
| `8787/v1/models` + `8787/v1/chat/completions` | Live pass | Browser adapter and ClickUp auth work |
| `20128/v1/models` | Model advertised | Model discovery works, **not proof chat auth works** |
| `20128/v1/chat/completions` | 401 for JSON and SSE | Both rejected during authentication; identify which layer |
| `.local/ninerouter.key` | Saved via `--save-key` | Locally stored key is readable, **not proof it exists/active in 9Router's key DB** |

Current research: 9Router's public discussion [#4650](https://github.com/decolua/9router/discussions/4650) describes the exact 401 `invalid_api_key` error from the local chat handler with `requireApiKey` enabled, sometimes due to a second 9Router process with a different data folder. GitHub issue [#4399](https://github.com/decolua/9router/issues/4399) records `sk_9router` placeholder keys being rejected. These are **related external examples**, not proof of this user's underlying root cause.

## Task progress

| ID | File / component | Acceptance | Status |
|---|---|---|---|
| A-01 | `tools/check_9router_path.py` | Classify 401 using only static allowlisted error identifiers, never reveal secrets | DONE (CI); live retry TODO |
| A-02 | `tools/local_gateway.py` | Authenticated diagnostics: HTTP chat arrivals and auth rejection/success counts | DONE (CI); requires gateway restart |
| A-03 | HTTP fixture tests | Simulate local router invalid client key and gateway 401 | DONE |
| A-04 | Live error classification | Report `invalid_api_key` or other safe error shape | TODO |
| A-05 | Fix key connection or wrong 9Router process | 9Router forwards a test chat to Gateway | TODO |

## Stage 1 — Use the updated safe 401 classifier (NO gateway restart)

In **PowerShell 2**:

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe tools\check_9router_path.py
```

If 401 is `invalid_api_key`, first check the **9Router client-side API key** in the **9Router local dashboard** → Endpoints / API Keys. Do not confuse it with the **upstream Gateway key** entered on your `brain` provider connection. The key must actually be issued by the **same instance** at `127.0.0.1:20128`, active and permitted.

If the locally stored `.local/ninerouter.key` is incorrect or stale, replace **only that file** after creating/copying a fresh key in the 9Router dashboard:

```powershell
Remove-Item .local\ninerouter.key
.\.venv\Scripts\python.exe tools\check_9router_path.py --save-key
.\.venv\Scripts\python.exe tools\check_9router_path.py
```

`--save-key` prompts with hidden input. **NEVER delete `.local/gateway.key`, `.local/browser-owner.key`, or Chromium `.local/browser-profile` while correcting a 9Router client key.** Never paste keys in chat/screenshots/Git. If the 9Router local key setting is intentionally off, check its documented behavior and prefer creating a valid key rather than disabling authentication.

### Check which process listens at 20128 (if correct key is still rejected)

```powershell
Get-NetTCPConnection -LocalPort 20128 -State Listen |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

Compare the PID with the 9Router process/dashboard you are actually using. Multiple installs (`npm -g`, `npx`, Windows service, Docker) may use distinct data directories and API key databases. Do not indiscriminately kill Node processes or delete 9Router state. Use the dashboard's request logs if available, **redact prompts and credentials** before sharing.

## Stage 2 — Distinguish 9Router-side 401 from Gateway-side 401 with safe counters

A new authenticated `GET /v1/session/diagnostics` now returns these additional numeric counters (no prompt, raw header/key, workspace/conversation ID):

- `http_chat_received`: count of `POST /v1/chat/completions` reaching Gateway **port 8787**.
- `http_chat_401`: those requests rejected **by the Gateway** with HTTP 401.
- `http_chat_2xx`: those requests accepted successfully by Gateway.
- `http_chat_other_errors`: those requests that failed with another 4xx/5xx or unhandled exception.

**You must restart PowerShell 1's Gateway after `git pull`** to load this new instrumentation. Stop the existing Gateway with Ctrl+C and close its Chromium; then:

```powershell
cd E:\Toolss\clickuptoapi
$env:CLICKUP_GATEWAY_API_KEY = (Get-Content -Raw .local\gateway.key).Trim()
.\.venv\Scripts\python.exe tools\local_gateway.py --port 8787 --router-mode
```

After opening/confirming Brain UI, press Enter to start listening. In **PowerShell 2**:

```powershell
# BEFORE — counters start from zero with each gateway process
.\.venv\Scripts\python.exe tools\send_gateway_request.py --diagnostics

# Trigger exactly ONE 9Router request, no retries
.\.venv\Scripts\python.exe tools\check_9router_path.py

# AFTER
.\.venv\Scripts\python.exe tools\send_gateway_request.py --diagnostics
```

Interpretation:

| Change observed in Gateway counters | Conclusion |
|---|---|
| `http_chat_received` stays the same | The 9Router POST did **not reach** Gateway. Check 9Router client API key / local instance / router routing |
| `http_chat_received` increases and `http_chat_401` increases | The request **did reach Gateway**, but Gateway rejected its Bearer key. Recheck 9Router provider's **saved upstream connection** key equals `.local/gateway.key` |
| `http_chat_received` increases and `http_chat_other_errors` increases | Gateway received request but rejected input/worker availability; check status and provider protocol without logging prompts |
| `http_chat_received` and `http_chat_2xx` increase, but 9Router reports 401 | Gateway succeeded and 9Router rewrote/rejected response; check router-side logs |

`completed_replies` alone **cannot** distinguish a router-side 401 from a Gateway-side auth failure because both can occur before an AI reply exists. The new HTTP counters eliminate that ambiguity without storing secrets.

## Stage 3 — Verify success safely

When both boundaries are corrected, first try:

```powershell
.\.venv\Scripts\python.exe tools\check_9router_path.py
```

Only after JSON is successful, optionally run `--stream`. Do not retry a request automatically on a 502/503 because the underlying UI may already have submitted it. Successful 9Router routing remains **LIVE UNVERIFIED** until the user supplies the `9Router -> Brain Gateway -> ClickUp: PASS` output.

The resulting gateway still supports only text, buffered SSE and manually chosen ClickUp UI model; it does not implement native tool calls, real-time tokens or independent cloud hosting.
