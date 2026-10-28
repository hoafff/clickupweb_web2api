"""Synthetic HTTP tests for 422 redaction and agent-compatibility diagnosis.

No real browser, secret, network provider, or ClickUp allowance is used.
"""
from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from tools.local_gateway import create_app
from tools.router_validation import (
    REASON_OVERSIZE, REASON_TOOLS, REASON_NON_TEXT,
    REASON_FORMAT, REASON_OTHER, reason_from_errors,
)

KEY = "fake-research-router-validation-key-123456"
AUTH = {"Authorization": f"Bearer {KEY}"}
PRIVATE = "PRIVATE_HERMES_SYSTEM_INSTRUCTIONS_NEVER_ECHO"


class FakeEngine:
    new_chat_per_request = True

    def __init__(self):
        self.calls = []

    def is_ready(self):
        return True

    async def complete(self, prompt):
        self.calls.append(prompt)
        return "OK"

    def session_diagnostics(self):
        return {
            "completed_replies": len(self.calls),
            "same_conversation_pairs": 0,
            "different_conversation_pairs": 0,
            "last_relation": "unobserved",
        }


class ValidationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.engine = FakeEngine()
        self.client = TestClient(
            create_app(self.engine, api_key=KEY, router_mode=True),
            base_url="http://127.0.0.1:8787",
        )
        self.addCleanup(self.client.close)

    def post(self, content="OK", **other):
        body = {
            "model": "clickup-ui-current",
            "stream": False,
            "messages": [{"role": "user", "content": content}],
            **other,
        }
        return self.client.post(
            "/v1/chat/completions", headers=AUTH, json=body,
        )

    def diagnostics(self):
        return self.client.get(
            "/v1/session/diagnostics", headers=AUTH,
        ).json()

    def test_hermes_long_system_message_rejected_without_echo(self):
        private_prompt = PRIVATE + "_" + ("x" * 50200)
        response = self.post(content="hello", messages=[
            {"role": "system", "content": private_prompt},
            {"role": "user", "content": "hello"},
        ])
        self.assertEqual(response.status_code, 422)
        data = response.json()
        self.assertEqual(data["detail"][0]["type"], "string_too_long")
        self.assertEqual(data["error"]["code"], REASON_OVERSIZE)
        self.assertNotIn("input", response.text.lower())
        self.assertNotIn(PRIVATE, response.text)
        self.assertNotIn("x" * 30, response.text)
        self.assertEqual(self.engine.calls, [])
        counters = self.diagnostics()
        self.assertEqual(counters["http_chat_422"], 1)
        self.assertEqual(counters["http_chat_rejected_message_too_long"], 1)
        self.assertEqual(counters["http_chat_2xx"], 0)

    def test_rejects_tool_schemas_without_echoing_tool_definition(self):
        response = self.post(tools=[{
            "type": "function",
            "function": {
                "name": "run_tool",
                "description": PRIVATE,
                "parameters": {"type": "object"},
            },
        }])
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], REASON_TOOLS)
        self.assertNotIn(PRIVATE, response.text)
        self.assertIn("text-chat only", response.text)
        self.assertEqual(
            self.diagnostics()["http_chat_rejected_unsupported_tool_calling"], 1,
        )
        self.assertEqual(self.engine.calls, [])

    def test_multimodal_and_sampling_rejections_are_distinct(self):
        multimodal = self.post(content=[{"type": "text", "text": PRIVATE}])
        self.assertEqual(multimodal.status_code, 422)
        self.assertEqual(multimodal.json()["error"]["code"], REASON_NON_TEXT)
        self.assertNotIn(PRIVATE, multimodal.text)
        sampling = self.post(temperature=0.7)
        self.assertEqual(sampling.status_code, 422)
        self.assertEqual(sampling.json()["error"]["code"], REASON_FORMAT)
        self.assertEqual(self.engine.calls, [])
        counts = self.diagnostics()
        self.assertEqual(counts["http_chat_rejected_unsupported_non_text_messages"], 1)
        self.assertEqual(counts["http_chat_rejected_incompatible_request_format"], 1)

    def test_other_invalid_and_compiled_transcript_still_safe(self):
        other = self.post(content="hi", messages=[
            {"role": "tool", "content": PRIVATE},
        ])
        self.assertEqual(other.status_code, 422)
        self.assertEqual(other.json()["error"]["code"], REASON_OTHER)
        self.assertNotIn(PRIVATE, other.text)
        big = self.post(content="hello", messages=[
            {"role": "system", "content": PRIVATE + "x" * 49900},
            {"role": "user", "content": "Hello"},
        ])
        self.assertEqual(big.status_code, 422)
        self.assertNotIn(PRIVATE, big.text)
        self.assertIn("Compiled text transcript exceeds", big.text)
        counters = self.diagnostics()
        self.assertEqual(
            counters["http_chat_rejected_compiled_transcript_too_long"], 1,
        )
        self.assertEqual(
            counters["http_chat_rejected_message_too_long"], 0,
        )
        self.assertEqual(self.engine.calls, [])

    def test_40k_agent_system_transcript_now_validates_as_plain_text(self):
        # Passing validation does NOT imply Hermes tool-calling support.
        long_system = PRIVATE + ("b" * 39900)
        r = self.post(content="xin chào", messages=[
            {"role": "system", "content": long_system},
            {"role": "user", "content": "xin chào"},
        ])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.engine.calls), 1)
        compiled = self.engine.calls[0]
        self.assertIn(PRIVATE, compiled)
        self.assertIn('"role":"system"', compiled)
        self.assertGreater(len(compiled), len(long_system))

    def test_plain_chat_still_returns_reply_and_no_422(self):
        result = self.post(content="Hi!")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["choices"][0]["message"]["content"], "OK")
        self.assertEqual(self.engine.calls, ["Hi!"])
        diag = self.diagnostics()
        self.assertEqual(diag["http_chat_received"], 1)
        self.assertEqual(diag["http_chat_2xx"], 1)
        self.assertEqual(diag["http_chat_422"], 0)

    def test_reason_logic_never_serializes_untrusted_input_or_type(self):
        errors = [{
            "type": "string_too_long",
            "loc": ("body", "messages", 0, "content"),
            "input": PRIVATE + "x" * 50200,
            "msg": PRIVATE,
            "ctx": {"max_length": 50000},
        }]
        self.assertEqual(reason_from_errors(errors), REASON_OVERSIZE)
        strange = [{
            "type": PRIVATE, "loc": ("body", PRIVATE),
            "msg": PRIVATE, "input": PRIVATE,
        }]
        self.assertEqual(reason_from_errors(strange), REASON_OTHER)
        self.assertNotIn(PRIVATE, json.dumps(
            {"reason": reason_from_errors(strange)}
        ))


if __name__ == "__main__":
    unittest.main()
