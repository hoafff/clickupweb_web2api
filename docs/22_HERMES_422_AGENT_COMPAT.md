# 22 — Hermes Agent HTTP 422 `string_too_long` against local Brain Gateway

**Date:** 2026-10-28. **Scope:** local ClickUp Browser UI text-chat bridge behind 9Router, NOT a general coding-agent backend.

## Objective

Explain and handle the actual **HTTP 422** visible in 9Router while a coding-agent UI displays "waiting on provider — retrying ...". Distinguish the already-proven text-chat path from native coding-agent requirements. Avoid storing or echoing private system prompts, tool schemas or browser credentials.

## Verified findings

From the researcher's supplied screenshots:

- The coding-agent UI displays a short user prompt (Vietnamese greeting), while the agent waits on the provider and retries.
- 9Router's **ClickUp Brain Local** upstream connection shows **[422]** and a JSON error beginning with **`"type":"string_too_long"`**.
- The prompt visible in the UI is **not** proof the full request body was short. A coding agent may attach a long system prompt, instructions, tools and history.
- The upstream provider URL displayed under Chat Completions points to `http://127.0.0.1:8787/v1/chat/completions`. That is consistent with 9Router's upstream route, not in itself a misconfigured URL.

The actual repository code in `tools/router_compat.py` imposes **8,000 Python characters per message content**, **8,000 characters on the flattened transcript**, and at most **32 messages**. The first limit uses Pydantic `Field(max_length=8000)`; `string_too_long` is its standard validation error. This is a **local Gateway imposed limit**, not a claim about ClickUp's documented context window.

The gateway additionally rejects native tool calls and other unsupported OpenAI request parameters (including non-null `tools`, `tool_choice`, `temperature`, `max_tokens` and multimodal `content`). System/developer roles are rendered as **plain transcript labels**, NOT privileged model roles. The generated SSE is buffered rather than true token-level streaming. The 9Router → Gateway → ClickUp simple text path previously passed real JSON, buffered SSE, history-as-text and a 1,611-character reply, but this never established coding-agent compatibility.

The Hermes Agent documentation describes a custom OpenAI-compatible endpoint and separately documents tool management and safe-mode CLI operation; it does **not** turn a text-only backend into a tool-calling model. Source: https://hermes-agent.nousresearch.com/docs/integrations/providers and https://hermes-agent.nousresearch.com/docs/reference/cli-commands.

## Master Plan / progress

| ID | Component | Action | Acceptance | State |
|---|---|---|---|---|
| H-01 | `router_compat.py` | Audit actual request validation limits / role/tool compatibility | Source-confirm 8k char limit and no tool calls | DONE |
| H-02 | `router_validation.py` | Return safe 422 reason without Pydantic raw input | Private prompt and tool description never appear in HTTP response | DONE, synthetic CI |
| H-03 | `local_gateway.py` | Count fixed 422 reason categories | Reason counters only; existing 422/HTTP counters remain | DONE, synthetic CI |
| H-04 | `send_gateway_request.py` | Read optional new safe diagnostic integer counters | Never emit raw headers/tokens/IDs | DONE, synthetic CI |
| H-05 | `tests/test_router_validation.py` | Test oversized agent system prompt, tool schemas, nontext, sampling defaults, normal chat | Regression tests on Windows/Ubuntu | DONE, CI |
| H-06 | Hermes live model request | Retest non-agent chat only when operator explicitly wishes | No more 422 for a short supported plain-text request | NOT RUN |
| H-07 | Full Hermes coding agent interoperability | Design context management, native tool loop, typed tool-call responses, cancellation, completion and session isolation | Real code-editing tool execution test | BLOCKED — separate major project |

## Implementation

By default FastAPI's `RequestValidationError` includes the raw Pydantic `input` in error details, potentially echoing full coding-agent prompts/tool schemas to the router/logs. The new error handler allows only a fixed error type/code/message. For oversize text it returns a concise **422** with `detail[0].type="string_too_long"` and `error.code="message_too_long"`, indicating that the local Gateway cap is 8,000 characters. Other fixed error categories include `unsupported_tool_calling`, `unsupported_non_text_messages`, `incompatible_request_format` and `invalid_request`. No automatic truncation or hidden compression, which could silently discard critical agent instructions, is performed.

Only numeric aggregate counters are stored in memory and returned by authenticated `--diagnostics`. New counters: `http_chat_rejected_message_too_long`, `http_chat_rejected_unsupported_tool_calling`, `http_chat_rejected_unsupported_non_text_messages`, `http_chat_rejected_incompatible_request_format`, and `http_chat_rejected_invalid_request`. These counters are **not retroactive** and reset on Gateway restart. This change does not expose request bodies, user content, browser profile, cookies or tokens.

## No-credit verification procedure

1. **Stop Hermes agent retries**, since a structurally incompatible request is not transient.
2. Keep 9Router running. After ensuring the visible ClickUp Browser is no longer generating, stop the Gateway using Ctrl+C and close its Chromium window to release the profile.
3. In PowerShell 1, after `git pull`:

```powershell
cd E:\Toolss\clickuptoapi
git pull
$env:CLICKUP_GATEWAY_API_KEY = (Get-Content -Raw .local\gateway.key).Trim()
.\.venv\Scripts\python.exe tools\local_gateway.py --port 8787 --router-mode --ui-research
```

Manually open authorized Brain UI, then press ENTER to enable the local API.

4. In PowerShell 2, read-only:

```powershell
.\.venv\Scripts\python.exe tools\send_gateway_request.py --diagnostics
```

No new prompts are required to prove code initialization. The reason counters become meaningful only after **future** requests. You can inspect 9Router's existing error details for the specific prior 422 if available, but never upload raw request bodies, prompts, tool schemas, auth headers, account IDs or private browser artifacts.

## Immediate working choices

**A. Basic text chat via the current Gateway:** Use a text-only OpenAI Chat Completions client (or the already-verified `tools/check_9router_path.py`) with `http://127.0.0.1:20128/v1`, model `brain/clickup-ui-current`, and an **inbound 9Router client key**. Keep a short prompt below 8,000 characters; system/developer chat histories count toward the same compiled budget. Text-only models still cannot read files or execute terminal tools autonomously.

**B. Hermes as a real coding agent:** Select a different model/provider that genuinely supports OpenAI-compatible **tool calls** and a context window large enough for its system instructions, tool schemas and repository history. Hermes documents a minimum context recommendation of 64k tokens. Its optional `--safe-mode` and `/tools` features can constrain tools, but there is no guarantee they shrink generated prompts below the current gateway cap; disabling a tool-use enforcement prompt is not the same as implementing tool calls.

**Do NOT:** blindly retry 422, remove the 8,000-character guard without verifying the UI editor, silently clip prompts, change `finish_reason` to a fake `stop`, pretend buffered SSE is token streaming, or claim Hermes can edit local code using this text-only provider.

## Remaining issues

The observed `string_too_long` identifies at least one incompatible request to the provider, but **the exact offending field index/length is not visible** in the cropped 9Router connection row. An additional oversized compiled transcript or unsupported tools error could follow when the first one is resolved. Do not assume a short user-visible greeting means the whole request is short. The fix in this chapter clarifies and protects failure handling; full Hermes agent interoperability remains unimplemented.
