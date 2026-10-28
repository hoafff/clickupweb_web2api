"""Synthetic local HTTP tests for 9Router -> Brain gateway path client.

No actual 9Router process or ClickUp session. The fake server exposes the
same two port-20128 endpoints and demands a separate fake 9Router key.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from tools.check_9router_path import (
    ROOT, RouterPathError, chat_once, classify_auth_error, main, parse_models,
    parse_stream, read_key, reject_reused_upstream_key, request_router, save_key,
)
from tools.router_compat import make_buffered_sse

KEY = "test-only-9router-local-client-key"
MODEL = "brain/clickup-ui-current"
SCRIPT = ROOT / "tools" / "check_9router_path.py"


class Fake9Router(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def json_response(self, status, data):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            self.json_response(401, {"detail": "private-key-never-echo"})
            return
        if self.path != "/v1/models":
            self.json_response(404, {})
            return
        self.json_response(200, {
            "data": [{"id": "another/other"},
                     {"id": MODEL}],
            "object": "list",
        })

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.json_response(404, {})
            return
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            self.json_response(401, {"error": {
                "type": "authentication_error", "code": "invalid_api_key",
                "message": "Invalid API key",
            }})
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.requests.append({
            "body": request,
            "accept": self.headers.get("Accept"),
            "authorization": self.headers.get("Authorization"),
        })
        if request.get("stream"):
            payload = make_buffered_sse("OK")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.json_response(200, {
                "choices": [{"message": {"role": "assistant", "content": "OK"}}]
            })


class RouterPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Fake9Router)
        cls.server.requests = []
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True
        )
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()

    def setUp(self):
        self.server.requests.clear()
        self.tmp = tempfile.TemporaryDirectory(prefix="fake-9router-")
        self.addCleanup(self.tmp.cleanup)
        self.keyfile = Path(self.tmp.name) / "ninerouter.key"
        self.keyfile.write_text(KEY + "\n", encoding="ascii")

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT),
             "--port", str(self.port),
             "--key-file", str(self.keyfile), *args],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            timeout=20, check=False,
        )

    def test_models_only_queries_9router_without_prompt(self):
        result = self.run_cli("--models-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(MODEL, result.stdout)
        self.assertIn("Total model IDs: 2", result.stdout)
        self.assertEqual(self.server.requests, [])
        self.assertNotIn(KEY, result.stdout + result.stderr)

    def test_json_9router_roundtrip_on_real_loopback_tcp(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("9Router -> Brain Gateway -> ClickUp: PASS", result.stdout)
        self.assertIn("Reply preview: OK", result.stdout)
        self.assertEqual(len(self.server.requests), 1)
        req = self.server.requests[0]
        self.assertEqual(req["body"]["model"], MODEL)
        self.assertIs(req["body"]["stream"], False)
        self.assertEqual(req["accept"], "application/json")
        self.assertEqual(req["authorization"], f"Bearer {KEY}")

    def test_stream_9router_sse_roundtrip(self):
        result = self.run_cli("--stream")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Response: SSE", result.stdout)
        self.assertIn("Reply preview: OK", result.stdout)
        req = self.server.requests[-1]
        self.assertIs(req["body"]["stream"], True)
        self.assertEqual(req["accept"], "text/event-stream")

    def test_history_roundtrip_and_custom_unicode_prompt(self):
        result = self.run_cli("--history")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.server.requests), 1)
        history = self.server.requests[-1]["body"]["messages"]
        self.assertEqual([m["role"] for m in history], [
            "system", "user", "assistant", "user",
        ])
        self.assertEqual(history[-1]["content"].startswith("What word"), True)
        self.server.requests.clear()
        result = self.run_cli("--prompt", "Trả lời bằng OK")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.server.requests[-1]["body"]["messages"][0]["content"],
            "Trả lời bằng OK",
        )

    def test_min_reply_length_detects_short_result(self):
        result = self.run_cli(
            "--prompt", "Write 3 sentences.",
            "--min-reply-chars", "100",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("shorter than the requested", result.stderr)
        self.assertNotIn(KEY, result.stdout + result.stderr)
        # Request reached router; rejecting short output is only a client
        # acceptance failure, not a transport or authentication failure.
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(
            self.server.requests[-1]["body"]["messages"][0]["content"],
            "Write 3 sentences.",
        )

    def test_rejects_invalid_prompt_before_chat_dispatch(self):
        result = self.run_cli("--prompt", " " * 3)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("1..7600", result.stderr)
        self.assertEqual(self.server.requests, [])

    def test_missing_or_wrong_key_does_not_echo_server_body(self):
        self.keyfile.unlink()
        unauth = self.run_cli()
        self.assertNotEqual(unauth.returncode, 0)
        self.assertIn("HTTP 401", unauth.stderr)
        self.assertNotIn("private-key-never-echo", unauth.stderr)
        self.assertNotIn(KEY, unauth.stdout + unauth.stderr)

    def test_rejected_chat_key_reports_only_safe_marker(self):
        with self.assertRaisesRegex(RouterPathError, "invalid_api_key") as cm:
            request_router(
                port=self.port, path="/v1/chat/completions", key="wrong",
                body={"model": MODEL,
                      "messages": [{"role": "user", "content": "OK"}],
                      "stream": False},
            )
        self.assertNotIn(KEY, str(cm.exception))

    def test_client_key_matching_gateway_secret_blocked_before_chat(self):
        upstream = Path(self.tmp.name) / "gateway.key"
        upstream.write_text(KEY + "\n", encoding="ascii")
        with self.assertRaisesRegex(RouterPathError, "distinct authentication roles") as cm:
            reject_reused_upstream_key(KEY, upstream)
        self.assertNotIn(KEY, str(cm.exception))
        self.assertEqual(self.server.requests, [])
        reject_reused_upstream_key("real-9router-issued-client-key", upstream)
        reject_reused_upstream_key(None, upstream)
        reject_reused_upstream_key(KEY, upstream.with_name("absent.key"))

    def test_allowlisted_401_diagnostics_never_echo_secrets(self):
        examples = [
            (b'{"error":{"message":"Invalid API key","type":"authentication_error","code":"invalid_api_key"}}', "invalid_api_key"),
            (b'{"detail":"Unauthorized"}', "unauthorized"),
            (b'{"error":{"code":"authentication_error","message":"PRIVATE-TOKEN-DO-NOT-LOG"}}', "authentication_error"),
            (b'{"error":{"message":"PRIVATE-TOKEN-DO-NOT-LOG"}}', "not recognized"),
        ]
        for raw, expected in examples:
            with self.subTest(expected=expected):
                classification = classify_auth_error(401, raw)
                self.assertIn(expected, classification)
                self.assertNotIn("PRIVATE-TOKEN-DO-NOT-LOG", classification)
        self.assertEqual(classify_auth_error(500, b'{"detail":"private"}'), "")
        self.assertIn("unrecognized", classify_auth_error(401, b'not-json'))

    def test_model_alias_must_appear_in_9router_catalog(self):
        result = self.run_cli("--model", "brain/not-advertised")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not present", result.stderr)
        self.assertEqual(self.server.requests, [])

    def test_save_key_is_hidden_and_never_overwrites(self):
        path = Path(self.tmp.name) / ".local" / "ninerouter.key"
        with patch("tools.check_9router_path.ROOT", Path(self.tmp.name)), \
                patch("tools.check_9router_path.getpass.getpass", return_value=KEY):
            save_key(path)
            self.assertEqual(read_key(path), KEY)
            with self.assertRaises(RouterPathError):
                save_key(path)

    def test_validates_path_port_json_and_sse(self):
        with self.assertRaises(RouterPathError):
            request_router(port=self.port, path="/outside", key=KEY)
        with self.assertRaises(RouterPathError):
            request_router(port=999, path="/v1/models", key=KEY)
        self.assertEqual(
            parse_models('{"data":[{"id":"brain/clickup-ui-current"}]}'),
            [MODEL],
        )
        with self.assertRaises(RouterPathError):
            parse_stream('data: {}\n\n')
        with self.assertRaises(RouterPathError):
            parse_models('{"data":{}}')

    def test_default_api_key_file_is_optional_but_not_silently_fabricated(self):
        self.assertIsNone(read_key(Path(self.tmp.name) / "no-key"))
        empty_key = Path(self.tmp.name) / "empty.key"
        empty_key.write_text("\n", encoding="ascii")
        with self.assertRaises(RouterPathError):
            read_key(empty_key)


if __name__ == "__main__":
    unittest.main()
