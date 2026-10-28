"""Offline tests for opt-in Playwright research capture and credential redaction."""

import unittest

from tools.payload_capture import (
    allows_http_body,
    parse_content,
    redact_payload,
    safe_url,
)


class PayloadRedactionTests(unittest.TestCase):
    def test_nested_credentials_masked_but_model_and_effort_remain(self):
        body = {
            "model": "opus-5-5",
            "thinking_effort": "medium",
            "messages": [{"role": "user", "content": "ping"}],
            "accessToken": "visible-access-secret",
            "headers": {"Authorization": "Bearer vulnerable-secret"},
            "config": {
                "refresh_token": "visible-refresh-secret",
                "sessionKey": "visible-session-key",
                "max_tokens": 2048,
            },
        }
        sanitized = redact_payload(body)
        dump = str(sanitized)
        self.assertIn("opus-5-5", dump)
        self.assertIn("medium", dump)
        self.assertIn("ping", dump)
        self.assertNotIn("visible-access-secret", dump)
        self.assertNotIn("visible-refresh-secret", dump)
        self.assertNotIn("visible-session-key", dump)
        self.assertNotIn("vulnerable-secret", dump)
        self.assertEqual(sanitized["accessToken"], "<redacted>")
        self.assertEqual(sanitized["config"]["max_tokens"], 2048)

    def test_analytics_writekey_and_session_id_are_redacted(self):
        captured = {
            "writeKey": "private-key-value",
            "sessionId": "private-session-id",
            "session_id": "private-session-id-2",
            "aiSessionId": "private-ai-session-id",
            "reasoningLevel": "medium",
        }
        sanitized = redact_payload(captured)
        self.assertEqual(sanitized["writeKey"], "<redacted>")
        self.assertEqual(sanitized["sessionId"], "<redacted>")
        self.assertEqual(sanitized["session_id"], "<redacted>")
        self.assertEqual(sanitized["aiSessionId"], "<redacted>")
        self.assertEqual(sanitized["reasoningLevel"], "medium")

    def test_bearer_jwt_and_api_keys_masked_within_string(self):
        data = {
            "message": (
                "Authorization: Bearer abcdefghijklmnop "
                "JWT eyJhbGciOiJub25lIn0.eyJzdWIiOiIxMjM0NSJ9.ABCDEFGHIJKLMNOP "
                "key sk-abcdefghijklmnopqrstuvwx"
            )
        }
        val = str(redact_payload(data))
        self.assertNotIn("abcdefghijklmnop ", val)
        self.assertNotIn("eyJhbGci", val)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwx", val)

    def test_json_capture_preserves_safe_body(self):
        out = parse_content(
            b'{"query":"ping","model":"max","thinking_effort":"auto","access_token":"private"}',
            content_type="application/json",
        )
        self.assertEqual(out["format"], "json")
        self.assertEqual(out["data"]["query"], "ping")
        self.assertEqual(out["data"]["thinking_effort"], "auto")
        self.assertEqual(out["data"]["access_token"], "<redacted>")

    def test_socket_io_frame(self):
        out = parse_content(
            '42["chat_update",{"model":"opus","thinking":"low","token":"abc"}]',
        )
        self.assertEqual(out["format"], "json")
        self.assertEqual(out["data"][0], "chat_update")
        self.assertEqual(out["data"][1]["thinking"], "low")
        self.assertEqual(out["data"][1]["token"], "<redacted>")

    def test_sse_json_events_and_done(self):
        content = (
            'data: {"delta":"hello","session_token":"private"}\n\n'
            'data: [DONE]\n\n'
        )
        out = parse_content(content, content_type="text/event-stream")
        self.assertEqual(out["format"], "sse_json")
        self.assertEqual(out["events"][0]["delta"], "hello")
        self.assertEqual(out["events"][0]["session_token"], "<redacted>")
        self.assertEqual(out["events"][1], {"done": True})

    def test_binary_unknown_and_large_payload_are_not_collected(self):
        self.assertEqual(parse_content(b"\xff\xfe")["format"], "skipped")
        self.assertEqual(parse_content("non-json")["format"], "skipped")
        self.assertEqual(
            parse_content("x" * 300_000, max_bytes=200_000)["reason"], "too_large"
        )
        self.assertFalse(allows_http_body("image/png"))
        self.assertFalse(allows_http_body("text/html; charset=utf-8"))
        self.assertTrue(allows_http_body("application/json; charset=utf-8"))

    def test_url_sanitized_without_query_userinfo_or_identifiers(self):
        value = "https://user:password@app.clickup.com/123456789012/abcDEF1234?token=secret#x"
        sanitized = safe_url(value)
        self.assertEqual(sanitized, "https://app.clickup.com/{id}/{id}")
        self.assertNotIn("secret", sanitized)
        self.assertNotIn("password", sanitized)


if __name__ == "__main__":
    unittest.main()
