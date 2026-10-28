# 15 — Local HTTP Gateway POC over ClickUp Brain Browser Adapter

**Status (2026-10-28):** Local JSON API code and offline mock/integration tests available. **The researcher has confirmed live Playwright auto-send (1/1 `OK`) before this gateway implementation.** The **HTTP gateway has now been tested successfully end-to-end against a live ClickUp session** using an explicit UTF-8 request body; terminal output was `OK`. This is a localhost research prototype and **not cloud-hosted or an official/direct ClickUp API**.

## 1. Objective / evidenced constraints

From the researcher's successful live output:

```text
One message clicked in UI; awaiting WebSocket reply.
SUCCESS: AI reply-created event correlated to the UI message window.
Reply length: 3 characters
WS diagnostics: {"websocket_connections_observed": 1, "json_ws_frames_processed": 15, "matching_reply_comments": 1}
Reply: OK
```

We can now wrap the verified UI send/receive path in a deliberately **narrow local HTTP facade**:

```text
Local HTTP client (Bearer key)
  -> FastAPI 127.0.0.1:8787 (single request at a time)
    -> Playwright visible Chromium / private persistent profile
      -> ClickUp Brain Ask UI (selected model/effort controlled manually)
        -> verified contenteditable div.fill(prompt)
        -> verified Send button.click()
          -> WebSocket aiConversationStarted
          -> WebSocket chatCommentCreated
            -> ConversationEventCorrelator
              -> JSON HTTP response
```

No cookie, auth token or raw WS payload is copied into the source tree. **This does not make a cloud service**; the browser process runs where the gateway is started.

## 2. Install dependencies

After closing existing Chromium/tracer/inspector processes to release the `.local/browser-profile` profile:

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe -m pip install -r requirements-gateway.txt
```

Requires Python 3.11+ and Playwright Chromium already installed during V3 testing. If necessary: `.\.venv\Scripts\python.exe -m playwright install chromium`.

## 3. Start the gateway

Create a **unique, random local key** (at least 24 characters) in a **Git-ignored local file**. This allows two PowerShell terminals to use the same key without printing it. The file contains a **plaintext credential**: only use a trusted machine, protect your user profile, and **never share or upload it**.

```powershell
New-Item -ItemType Directory -Force .local | Out-Null
if (-not (Test-Path .local\gateway.key)) {
  .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))" |
    Set-Content -Encoding Ascii .local\gateway.key
}
$env:CLICKUP_GATEWAY_API_KEY = (Get-Content -Raw .local\gateway.key).Trim()
.\.venv\Scripts\python.exe tools\local_gateway.py --port 8787 --timeout 120
```

Chromium starts visible. Log in as usual, open Brain² Ask, manually select the model and Thinking Effort you want. Ensure the editor is empty and **no prior AI generation is in progress**. Press Enter **in the gateway terminal** when ready. The gateway then starts listening on **127.0.0.1 only**.

**Local API authentication:** Use the **same** `CLICKUP_GATEWAY_API_KEY` in the calling process. The gateway never prints it. In the **second PowerShell terminal**, run the following **before** the HTTP request:

```powershell
cd E:\Toolss\clickuptoapi
$env:CLICKUP_GATEWAY_API_KEY = (Get-Content -Raw .local\gateway.key).Trim()
```

`.local/gateway.key` is ignored by Git but is **not encrypted**. Avoid screenshots that display the file or its contents. If compromised, delete the file and create a new key while gateway is stopped.

## 4. First HTTP request

Second PowerShell terminal:

```powershell
$headers = @{ Authorization = "Bearer $env:CLICKUP_GATEWAY_API_KEY" }
$body = @{
  model = "clickup-ui-current"
  messages = @(@{ role = "user"; content = "Trả lời đúng một từ: OK" })
  stream = $false
} | ConvertTo-Json -Depth 5
# Windows PowerShell 5.1: explicitly encode JSON as UTF-8 bytes.
$utf8Body = [System.Text.Encoding]::UTF8.GetBytes($body)
Invoke-RestMethod -Uri "http://127.0.0.1:8787/v1/chat/completions" -Method Post -ContentType "application/json; charset=utf-8" -Headers $headers -Body $utf8Body
```

Success should include:

```json
{
  "object": "chat.completion",
  "model": "clickup-ui-current",
  "choices": [
    {"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": null}
  ]
}
```

(The actual response also has a freshly-generated local `id` and `created` timestamp; `OK` is an expected outcome of the test prompt, not guaranteed.)

Readiness and models:

```powershell
Invoke-RestMethod http://127.0.0.1:8787/healthz
Invoke-RestMethod http://127.0.0.1:8787/v1/models -Headers $headers
```

No public port, domain, tunnel or container exposure should be configured at this stage.

### Windows PowerShell 5.1 — error: `There was an error parsing the body`

One real Windows PowerShell request reached the local gateway but returned an HTTP error **before** the UI-send path: `{"detail":"There was an error parsing the body"}`. In this session the JSON body contains Vietnamese text. **Likely cause:** Windows PowerShell's string `-Body` encoding can differ from the UTF-8 JSON expected by FastAPI. The precise wire bytes from that failure were not captured, so the root cause is **not yet proven**.

**Fix without restarting Chromium or the gateway:** encode the already-built `$body` string as UTF-8 bytes and explicitly declare the charset:

```powershell
$utf8Body = [System.Text.Encoding]::UTF8.GetBytes($body)
$response = Invoke-RestMethod -Uri 'http://127.0.0.1:8787/v1/chat/completions' -Method Post -Headers $headers -ContentType 'application/json; charset=utf-8' -Body $utf8Body
$response.choices[0].message.content
```

Or update the repo and run the safer helper (defaults to an ASCII-only test prompt, avoiding Windows PowerShell 5.1 source-file encoding ambiguity):

```powershell
git pull
.\tools\send_gateway_request.ps1
# To send Vietnamese text, specify -Prompt explicitly:
.\tools\send_gateway_request.ps1 -Prompt 'Trả lời đúng một từ: OK'
```

The helper reads the **Git-ignored local API key** from `.local/gateway.key`, constructs compact JSON, explicitly sends UTF-8 bytes, and prints only the response text. It never outputs the key or the request body. If your execution policy blocks scripts, use the first two-line `$utf8Body` command instead; do not change your machine-wide policy just to run this helper.

If `400` persists, check JSON syntax without sending it:

```powershell
$null = $body | ConvertFrom-Json -ErrorAction Stop
[System.Text.Encoding]::UTF8.GetByteCount($body)
```

The body parse error occurs before the `chat` handler calls Playwright; it should not have submitted the failed prompt to ClickUp. Confirm the browser is still on Brain² Ask before retrying.

## 5. API contract: intentionally limited

| Feature | Current behavior |
|---|---|
| `POST /v1/chat/completions` JSON | **Live E2E PASS** for one request with one Vietnamese prompt; durability/scale unverified |
| `GET /v1/models` | Returns only `clickup-ui-current` |
| `GET /v1/session/diagnostics` | Authenticated; returns safe counts and whether previous two WS reply conversation IDs match; **no raw IDs** |
| Auth | Local Bearer key, minimum 24 chars, constant-time compare |
| Model/effort | **Current selection in ClickUp UI**; no automatic switching |
| Messages | Exactly **one** nonempty `role=user` text message, max 8,000 chars |
| Streaming | `stream=true` returns 422; **no fake token SSE** |
| `system`, conversation history, tools/images, `temperature`, `n>1` | Return 422 instead of silently dropping |
| Parallel requests | Second request returns 429 while browser busy |
| Reply completion | Correlates `chatCommentCreated`; **not validated final stream marker**; `finish_reason=null` |
| Token usage | Unknown, **omitted** rather than fabricated |
| Browser/session failure | 502 and gateway becomes unavailable until restart; avoid accidental duplicate submits |
| Deployment | **127.0.0.1 only**; requires running visible, authenticated Chromium |

**Caveat:** The UI may retain prior conversation context after a request. A single-message HTTP payload does NOT imply a stateless chat. Do not use this for sensitive/multi-user production data; it currently represents a single account/session under direct operator control. Responses may depend on existing UI context.

## 6. Verification and safety

Offline tests:
- Mock FastAPI TestClient: Bearer auth, model list, JSON response, invalid fields, stream/history rejected, 429/502/503, trusted Host.
- Fake browser engine integration: HTTP request → UI send stub → WS start/comment → decoded answer; sequential calls; fail-closed on error and concurrency.
- CLI `--help` for direct script and `python -m` mode, Windows and Ubuntu CI.

Run:
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

**Security boundaries:** Loopback-only, local key, no Swagger/OpenAPI endpoints, no raw profile/token export, Uvicorn access logging disabled. This is still an experimental app and not a security-reviewed cloud gateway. The browser profile remains sensitive; keep it in the ignored `.local/` directory. Avoid sending prompts across accounts or publishing an authenticated endpoint.

## 7. Next priority after live HTTP test

- **DONE**: One live `Invoke-RestMethod` request with UTF-8 bytes returned `OK` through the browser and WebSocket.
- Confirm second request behavior (same conversation vs new) before advertising OpenAI multi-turn semantics.
- Validate model selection and reasoning effort via UI controls; do **not** invent a `model_id` contract from telemetry alone.
- Build session lifecycle/re-auth and secure worker isolation **before** considering a cloud/VPS deployment. Any public deployment would need additional security review and confirmation of the service's permitted use.


## 8. Live localhost HTTP acceptance result — PASS

**Observation reported by researcher on 28 October 2026** (no raw HTTP body, browser profile, credentials or workspace IDs shared):

```text
LOCAL API ready at http://127.0.0.1:8787
Invoke-RestMethod (original string -Body) -> JSON parsing error
Invoke-RestMethod (UTF-8 byte[] -Body) -> no HTTP error
$response.choices[0].message.content -> OK
```

Verified local path: bearer-authenticated `POST /v1/chat/completions` → FastAPI → browser UI input/send → WebSocket reply correlation → JSON completion `choices[0].message.content="OK"`.

**Evidence limits:** The prompt was a short single user message and model/effort selection was done manually in the UI. We did not observe the full HTTP JSON response in the supplied terminal excerpt, nor an end-of-generation signal, token accounting, multi-turn isolation, restart/re-auth, headless Chrome, cloud deployment or any remote client. Treat all those as **TODO / UNVERIFIED**. The original request bytes causing JSON parsing failure were not captured, so the exact encoding root cause remains an informed hypothesis; explicit UTF-8 is a confirmed workaround.

Next gates: [16 — acceptance and cloud-readiness](16_LIVE_HTTP_ACCEPTANCE_AND_DEPLOYMENT_GATES.md).

## 9. Private session diagnostics (follow-up test, live unverified)

After the first confirmed live HTTP E2E, a **new** endpoint was added to observe whether successive requests reuse a ClickUp conversation without disclosing opaque IDs:

```powershell
# Restart gateway after git pull because server does not hot-reload.
$env:CLICKUP_GATEWAY_API_KEY = (Get-Content -Raw .local\gateway.key).Trim()
$headers = @{ Authorization = "Bearer $env:CLICKUP_GATEWAY_API_KEY" }

Invoke-RestMethod http://127.0.0.1:8787/v1/session/diagnostics -Headers $headers
```

For this newly started gateway, `completed_replies` begins at 0, and `last_relation=unobserved`. Each successful HTTP completion increments the counter. After at least 2 successful sequential requests with available `conversation_id` values, `last_relation` is `same` or `different`; the response never contains the actual ClickUp IDs.

This endpoint is protected by the same local Bearer key. It currently records **conversations shared by replies**, not verified new-chat boundaries or token-level streaming. It is a diagnostic step towards G-03, **not multi-user context isolation**.
