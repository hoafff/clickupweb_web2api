"""Offline unit tests: no browser or ClickUp account is required."""

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Playwright must be installed to import the tracer; tests use its pure functions only.
try:
    trace = load_module("trace_browser", ROOT / "tools" / "trace_browser.py")
except ModuleNotFoundError:
    trace = None

summary = load_module("summarize_trace", ROOT / "tools" / "summarize_trace.py")


@unittest.skipIf(trace is None, "Install requirements-research.txt to test trace_browser")
class TestRedaction(unittest.TestCase):
    def test_removes_query_fragment_and_numeric_identifiers(self):
        value = trace.sanitize_url(
            "https://app.clickup.com/90182985436/ai/brain?access_token=SECRET#fragment"
        )
        self.assertEqual(value, "https://app.clickup.com/{id}/ai/brain")
        self.assertNotIn("SECRET", value)

    def test_uuid_and_opaque_segments_masked(self):
        url = trace.sanitize_url(
            "https://app.clickup.com/api/123e4567-e89b-42d3-a456-426614174000/"
            "abcdefghijklmnopqrstuvwxyz0123456789"
        )
        self.assertEqual(url, "https://app.clickup.com/api/{id}/{token}")

    def test_mixed_short_object_identifier_is_masked(self):
        self.assertEqual(
            trace.sanitize_url(
                "https://app.clickup.com/comments/view/z8rzdfj8qw-98?token=secret"
            ),
            "https://app.clickup.com/comments/view/{token}",
        )

    def test_websocket_schema_extracts_only_key_paths(self):
        payload = '{"event":"chat_update","data":{"model":"private-value","text":"secret prompt"}}'
        keys = trace.ws_json_key_paths(payload)
        self.assertIn("data.model", keys)
        self.assertIn("data.text", keys)
        self.assertNotIn("secret prompt", str(keys))
        self.assertEqual(trace.ws_json_key_paths("not json"), [])
        self.assertEqual(trace.ws_json_key_paths(b"binary"), [])

    def test_host_scope_exact_and_subdomain(self):
        self.assertTrue(trace.host_in_scope("https://app.clickup.com/ai", ("clickup.com",)))
        self.assertTrue(trace.host_in_scope("wss://socket.clickup.com/ai", ("clickup.com",)))
        self.assertFalse(trace.host_in_scope("https://evilclickup.com/", ("clickup.com",)))

    def test_json_key_paths_contain_no_values(self):
        data = {
            "model": "SECRET_MODEL_ID",
            "messages": [{"role": "user", "content": "private prompt here"}],
            "token": "SECRET_TOKEN",
        }
        paths = trace.describe_json_keys(data)
        self.assertIn("messages[].content", paths)
        self.assertIn("model", paths)
        self.assertNotIn("SECRET_MODEL_ID", str(paths))
        self.assertNotIn("private prompt here", str(paths))
        self.assertNotIn("SECRET_TOKEN", str(paths))


class TestAggregation(unittest.TestCase):
    def test_groups_http_and_websockets_without_message_body(self):
        events = [
            {
                "kind": "http_request",
                "request_id": "1",
                "method": "POST",
                "url": "https://app.clickup.com/api/ai",
                "resource_type": "fetch",
                "json_key_paths": ["messages", "model"],
            },
            {
                "kind": "http_response",
                "request_id": "1",
                "status": 200,
                "content_type": "text/event-stream",
            },
            {"kind": "http_finished", "request_id": "1", "duration_ms": 45},
            {"kind": "ws_open", "websocket_id": "socket-1", "url": "wss://app.clickup.com/ws"},
            {
                "kind": "ws_frame",
                "websocket_id": "socket-1",
                "direction": "received",
                "payload_length": 150,
            },
        ]
        result = summary.aggregate(events)
        self.assertEqual(result["http_request_count"], 1)
        self.assertEqual(result["http_endpoints"][0]["count"], 1)
        self.assertEqual(result["http_endpoints"][0]["mean_latency_ms"], 45)
        self.assertEqual(result["websockets"][0]["received"], 1)


if __name__ == "__main__":
    unittest.main()
