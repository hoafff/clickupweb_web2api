# 13 — Browser Session Adapter: live E2E smoke test

**Status updated 2026-10-28:** User-confirmed **manual AND auto-send live E2E PASS** in logged-in ClickUp Brain session. Latest auto-send returned `OK` (15 received JSON WS frames, 1 matching AI reply). GitHub CI still tests with synthetic WS frames and fake UI locators; it cannot authenticate to the researcher's Workspace. **Local HTTP gateway code exists but HTTP→ClickUp live verification remains pending.**

## Objective and scope

First **live** probe without replaying private HTTP endpoints or extracting/reusing cookies: launch visible Chromium using the **same persistent profile** as the research tracer, let the researcher sign in normally, then observe `aiConversationStarted` + `chatCommentCreated` for exactly one UI submission. Reply correlation uses `ai_result_id` and validates `conversation_id`.

The adapter is **not** a complete API, hosted service, permission bypass, direct HTTP proxy or reliable end-of-stream detector. Successful `reply_created` is **not proof of model completion** and does not imply token streaming.

## Phase 1: manual UI E2E (recommended; no CSS selectors needed)

1. **Close the previous tracer/browser process** to release the persistent Chromium profile. The trace JSONL files remain on disk.
2. In PowerShell from the repo root:

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe tools\browser_adapter.py --mode manual --timeout 120
```

3. The visible Chromium window opens with `.local/browser-profile`. If needed, sign in manually, go to **Brain² / Ask**, select model/effort and make sure **no older AI generation is still running**.
4. Back in PowerShell, press **Enter once** when the correct Brain tab is open.
5. Terminal prints `Armed. SEND EXACTLY ONE test message ...`; return to the browser and **send a single short test message**.
6. Terminal should report `SUCCESS: AI reply-created event correlated ...`, reply text length and numeric WS diagnostics. By default **no prompt, reply text, cookie, session token or opaque ID is printed**.

**Optional:** add `--show-reply` to show the received reply text in local terminal. Do not share it if it contains Workspace/private information.

If the command returns `No aiConversationStarted event captured`, it means **this browser session** did not receive the expected event while armed (page, login, socket or scope issue). This is a live test outcome, not evidence the V3 offline findings were wrong. Report the terminal error **without** browser profile/cookie/authorization/HAR.

## Phase 2: explicit UI auto-send (after CSS selectors are VERIFIED)

```powershell
.\.venv\Scripts\python.exe tools\browser_adapter.py --mode auto --confirm-send --composer-selector '<verified composer CSS>' --send-selector '<verified send button CSS>' --timeout 120
```

The terminal will prompt for **one test message**, then fill the editor and click the send control once. The adapter **requires exactly one visible element for each CSS selector**, and refuses action on ambiguity. It does not guess model menu selectors; choose the target model and Thinking Effort on the web UI before pressing Enter in the terminal. Do **not** copy the placeholder selectors above literally. They must be checked against the actual DOM via browser DevTools.

For safety, no unattended loop, scheduler, multi-user server, hidden browser, cookie export or direct API replay is included at this stage.

## Design and data flow

```text
Playwright visible Chromium (persistent local browser profile)
   |
   +-- UI: researcher sends one prompt
   |       --or--
   |   UI: opt-in CSS composer.fill + send.click
   |
   +-- on(websocket, /ws, clickup.com host)
            |
            +-- on(framereceived): parse JSON in memory only
                    |
                    +-- aiConversationStarted.ai_result_id
                    |           |
                    |           v
                    |   wait_for_created(ai_result_id)
                    |           |
                    +-- chatCommentCreated
                              |
                              v
                     ConversationEventCorrelator
                     verifies conversation_id
                              |
                              v
                     CorrelatedComment text (private memory)
```

### Fail-closed behavior

- Auth/session login via UI, no session/cookie logging.
- One active UI test at a time; multiple distinct AI starts while armed cause **ambiguous result error**.
- Ignores WS frames not on HTTPS-domain-derived `clickup.com` realtime `/ws`, binary frames, malformed JSON, oversized text frames.
- Duplicate AI start is not counted as a second request; comments can arrive before the corresponding start event.
- Enforces timeout for absence of AI start/reply. Protects against mismatched conversation ID through the correlator.
- `--mode auto` requires **two verified CSS selectors** and explicit `--confirm-send`; refuses to send when selectors missing, ambiguous or invisible.
- Does not write raw payloads to any file. Outputs only safe counters and text length unless `--show-reply` is requested.

### Known limitations

- A login browser window must run on the researcher's device or a permitted desktop environment. The GitHub Actions environment cannot conduct real auth tests.
- An ongoing generation that started before arming might cause misleading events; wait for prior generation to finish.
- A second unrelated AI-start event during the probe is rejected instead of guessed. One-tab, one-prompt controlled setup is required.
- No validated end-of-generation marker; one `chatCommentCreated` per reply was seen in V3, but this may differ with long prompts, tools or attachments.
- CSS selectors are not known from network-only V3 traces. **Do not claim auto-send verified** until the researcher identifies the live DOM elements.
- Browser Adapter will be followed by explicit mock FastAPI interface + HTTP JSON compatibility tests once live manual E2E passes. Do not expose this browser profile or its session credentials to a public gateway.

## Acceptance checklist

| Task | Status | Verification |
|---|---|---|
| B-01 WS in-memory reader & correlator | DONE | Unit tests synthetic WS |
| B-02 Browser launch/manual interaction | IMPLEMENTED, LIVE UNVERIFIED | Must run on researcher's logged-in PC |
| B-03 CSS-selector-based single auto-send | DONE (live) | User verified DOM, automatic UI submit, received `OK` |
| B-04 Import via script and `-m` | DONE | CLI smoke tests on Windows/Linux CI |
| B-05 Real live UI send → WS reply | DONE (live) | User-confirmed manual + automatic E2E |
| B-06 Multi-model+effort live regression | TODO | After B-05 and verified UI controls |
| B-07 OpenAI-like localhost JSON gateway | IMPLEMENTED, LIVE HTTP UNVERIFIED | `tools/local_gateway.py`, mock tests; see doc 15 |

## Security

Persistent profile `.local/browser-profile/` contains sensitive authentication state and is Git-ignored. Do not commit or upload it. `--show-reply` prints actual message content; only enable on a trusted local terminal.


## Gateway follow-up

After live auto-send PASS, a local experimental JSON facade is documented in [doc 15](15_LOCAL_HTTP_GATEWAY.md). It is **not** hosted or a direct unofficial upstream API. Use the documented localhost Bearer flow for the next live HTTP E2E acceptance test.
