# 23 — Large text prompts in ClickUp Brain UI (observed ~40k characters)

**Date:** 2026-10-28. **Status:** Synthetic API validation implemented. No live 40k-character send or complete reply through 9Router confirmed.

## Objective / Findings

The operator **pasted approximately 40,000 characters** into the visible ClickUp Brain² editor and shared a screenshot showing the draft displayed and the send control available. This is evidence that the **browser editor accepts a large draft**. It is **NOT** proof that the upstream model will accept, process, remember, or finish responding to all characters. It is also not a known ClickUp token-context or product API limit.

A previous real Hermes→9Router→Gateway request returned `422 string_too_long`. Source audit showed that rejection originated in **our own** `RouterMessage.content=8_000` Pydantic guard, not a measured ClickUp server limit. The same hardcoded 8,000-character cap existed on the compiled transcript and on direct Gateway chat; the local 9Router test client stopped at 7,600.

## Master plan / tasks

| ID | Component | Action | Acceptance | Status |
|---|---|---|---|---|
| L-01 | Existing code | Identify local 8k/7.6k artificial caps | Source-confirm every relevant gate | DONE |
| L-02 | `tools/prompt_limits.py` | Define one bounded experimental limit | 50,000 Python Unicode characters | DONE |
| L-03 | `router_compat.py`, `local_gateway.py` | Replace old 8k validation; retain text-only, isolated chat, no silent truncation | 40k text accepted in mock engine, >50k rejected before UI | DONE, synthetic |
| L-04 | `send_gateway_request.py`, `check_9router_path.py` | Align local clients and direct-script entrypoints | 40k messages encode/forward without clipping | DONE, synthetic |
| L-05 | `router_validation.py` | Keep sanitized 422 body and diagnostics | No raw private prompt/input echoed, 50k bound in explanation | DONE, synthetic |
| L-06 | Regression tests | Normal text, UTF-8, transcript overhead and overflow cases | Windows/Ubuntu CI | DONE |
| L-07 | Real long UI send | Verify actual submission and returned answer, without private content | One authorized operator-controlled 40k test and UI confirmation | NOT RUN |
| L-08 | Real coding-agent tool calling | Native tool schemas, role semantics, tool results, token window | Real tool execution and cancellation checks | OUT OF SCOPE / BLOCKED |

## Implementation decision

For now the project enforces **50,000 characters** as an experimental, bounded application-side maximum. This allows the reported ~40k UI draft while leaving headroom for a small chat transcript. The rule applies to:
- Each `content` string in API messages; **and**
- The **entire flattened serialized transcript**, including role labels, JSON escapes and explanatory prefix.

A 49,900-character system message plus a final user turn may be rejected because the compiled text crosses 50,000; that is intended. It is never truncated to fit. The limit counts **characters, not tokens**, and client models may add history/system messages not visible in the user chat input.

Nothing changes native role/tool semantics, `finish_reason=null`, buffered-only SSE, browser login, or the local-only security model. If Hermes sends `tools`, `tool_choice`, `max_tokens`, non-text content or other unsupported OpenAI fields it should **still receive sanitized HTTP 422**. Accepting 40k text does **not** make Hermes a functioning coding agent or grant filesystem/terminal tool calls to ClickUp.

## Verification / Remaining issues

Mock-engine and loopback tests verify validation, request encoding, and that a 40k UTF-8 user message reaches the *mock* Gateway/9Router path unchanged, without ClickUp browser traffic or credit usage. The user's screenshot independently supports only editor paste readiness.

Potential remaining limits: actual UI send-button behavior on long drafts; Playwright fill/DOM performance; 9Router upstream request/proxy restrictions; ClickUp service validation/token context; reply-created event vs end-of-generation; unknown model completion limits. Do not assume a particular size is guaranteed to succeed because it passed a local validator.

### No-credit smoke check after update

```powershell
cd E:\Toolss\clickuptoapi
git pull
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_router_validation.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_router_compat.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_check_9router_path.py" -v
```

**Important:** The currently running Gateway process continues using the old 8k validation until restarted; upgrading files via `git pull` alone does not reload its Python modules. After confirming no AI generation is pending, restart **only** Gateway (keep 9Router running), with the existing authorized private browser profile and key.

A future real 40k request should be initiated **only by the operator** and can consume ClickUp allowance. First verify no existing prompt is pending and never blindly resend an ambiguous failed request. A safe first test can use a synthetic non-sensitive known-length prompt whose ending contains a unique marker, but this only establishes transport of requested trailing content if the model echoes it; it cannot prove it processed all 40k characters or that model generation genuinely ended.
