# 21 — Opt-in read-only UI state research for ClickUp Brain²

**Date:** 2026-10-28

## Objective

Improve evidence about when ClickUp Brain completes visible generation, **without** guessing an undocumented backend protocol or changing the proven JSON/SSE bridge behavior. The repository now contains a **separate opt-in UI metadata probe**. It is research instrumentation, not a final-generation detector.

## Findings — actual private trace v3

The operator ran `audit_brain_event_timeline.py` on an authorized private local WS trace and provided only numeric counters:

| Observed metric | Value |
|---|---:|
| Inbound event frames | 176 |
| AI starts / AI comments created | 8 / 8 |
| `chatCommentEdited` | 13 |
| Edited events containing `version_event_data.changes` | 13 |
| Edited events with nonempty `changes` | **0** |
| Edits with payload dictionary or top-level/payload status key | **0** |
| Edits while some AI start had no created reply yet | 3 |
| Edits after a previous reply-created event | 13 |
| Edits 0–2 seconds after prior AI comment-created event | **10** |
| Edits 2–10 seconds after prior AI comment | 0 |
| Edits 10–30 seconds after prior AI comment | 1 |
| Edits more than 30 seconds after prior AI comment | 2 |
| Other chat-family events | 49, no recognizable typing/status/conversation/comment substring |
| Start→created reply latency | 1 under 1s, 5 between 1–5s, 1 between 5–30s, 1 over 30s |

**Interpretation:** There is a temporal association of edits with reply creation, but **no explicit reply ID, content change, or completion status** in the edited events. Even a control that disappears after the reply might be UI-specific, not proof the upstream inference stopped. No production change to `finish_reason=null` or buffered SSE is justified.

## Implementation and task plan

| ID | Component | Action and acceptance | Status |
|---|---|---|---|
| U-01 | `tools/brain_ui_state_probe.py` | Read-only JS; no message values, text, cookies, IDs or raw labels; return fixed metadata fields | DONE — CI |
| U-02 | `tools/local_gateway.py` | **Opt-in** authenticated `GET /v1/research/ui-state`, off by default; existing Chat Completions unchanged | DONE — CI |
| U-03 | `tools/check_brain_ui_state.py` | `--snapshot`, `--watch`, `--drive-router` CLI with bounded polling and local loopback only | DONE — CI |
| U-04 | `tests/test_brain_ui_state_probe.py` | Strict metadata validation, auth fail-closed, no prompt leakage, synthetic local HTTP checks | DONE — CI |
| U-05 | Live browser UI controls | Operator-generated sample counts during one benign ClickUp request | TODO |
| U-06 | Upstream end-of-generation evidence | Identify verified UI transition or endpoint event, correlated with a reply | **NOT VERIFIED** |
| U-07 | Reliable completion handling | Implement only after U-06 is verified, test cancellation/late replies | BLOCKED on U-06 |

### Security properties

The UI JS reads **only** visible control and accessibility **attributes for local classification**, discarding their values. It does not read or return message text, input values, cookies, headers, URLs, workspace IDs, conversation IDs, storage or HTML. All returned fields are server-validated booleans or bounded nonnegative integers; a malformed result yields 503. The endpoint requires the existing Gateway Bearer key and the owner-session capability when applicable. Gateway remains loopback-only and does not expose this endpoint unless explicitly started with `--ui-research`.

**Candidate control heuristics** include short accessible labels/attributes with words like `Stop`, `Cancel`, `Interrupt`, `Generating`, `Thinking`, and role=`progressbar`/aria-busy. These are hypotheses; negative counts can reflect unrecognized UI selectors, language differences or a hidden control, **not** proof of completion. The tool does not click controls or invoke Playwright send.

## How to run once on Windows (uses one real request only if requested)

**PowerShell 1:** Stop the currently running Gateway with Ctrl+C and close its Chromium window so the persistent profile is released. **Do not close/stop 9Router**, and do not delete `.local/gateway.key`, `.local/ninerouter.key` or the Chromium profile. Then:

```powershell
cd E:\Toolss\clickuptoapi
git pull

$env:CLICKUP_GATEWAY_API_KEY = (Get-Content -Raw .local\gateway.key).Trim()
.\.venv\Scripts\python.exe tools\local_gateway.py --port 8787 --router-mode --ui-research
```

Confirm the visible ClickUp Browser is signed in, open Brain, select the desired model/effort, then press ENTER in PowerShell 1. The Gateway remains an authenticated local service, now with the opt-in diagnostic GET endpoint.

**PowerShell 2:** First get a read-only baseline:

```powershell
.\.venv\Scripts\python.exe tools\check_brain_ui_state.py --snapshot
```

No AI prompt is sent. The result should contain `page_is_brain`, `composer_visible`, `send_visible` and aggregate visible button/control counts. It is not an assertion about the model being complete.

Next, with informed consent to send **one** harmless prompt (which may consume ClickUp allowance), run:

```powershell
.\.venv\Scripts\python.exe tools\check_brain_ui_state.py --drive-router --samples 70 --interval 0.35
```

This command submits a single fixed six-paragraph research prompt through **9Router :20128** while a parallel loop polls the Gateway UI metadata endpoint on **:8787**. It prints only a bounded aggregate of boolean/control counts and the length of the response. It does NOT print prompt, response body, raw label strings or keys and does not change the Gateway reply semantics. The observable page may navigate at the beginning of `--router-mode`, producing a few failed metadata samples; they are counted, never treated as completed generations.

Alternatively use `--watch --samples 50 --interval 0.35` to observe without sending any prompt, and independently send a harmless text request from another PowerShell window during the sampling window.

Only share the **fixed-key JSON summary**. Never upload screenshots exposing chat content, private trace files, Chromium profile, Gateway/9Router client keys or private browser logs.

## Verification and next engineering decision

CI exercises pure Python validation, endpoint opt-in/auth, response schema rejection, read-only script metadata constraints and mock loopback HTTP. It **does not claim** a live UI Stop/Generating control exists until the operator reports the new sample. If no control hint changes, research must identify verified UI controls by read-only visual/DOM inspection before implementing a detector. No synthetic test result should be substituted for live ClickUp observation.

The current router text path (JSON, buffered SSE, transcript-as-text and 668-character suffix validation) remains operational independently of this optional research mode. Tool calling, true token streaming, real final-generation signalling, session recovery and cloud hosting are still unimplemented.
