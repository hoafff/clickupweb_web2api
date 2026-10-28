"""Router smoke CLI regression tests using a synthetic loopback HTTP server.

Specifically catches the real-world bug where uvicorn emits lowercase
"x-stream-mode" but the previous CLI used dict.get("X-Stream-Mode").
No ClickUp login, browser profile, real AI usage or 9Router process needed.
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

from tools.check_router_compat import parse_sse_result, request_local
from tools.router_compat import make_buffered_sse


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "check_router_compat.py"
KEY = "fixture-only-router-check-key-1234567890"


class FakeRouterGateway(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def respond(self, status: int, data: bytes, content_type: str,
                *, buffered: bool = False) -> None:
        self.send_response(status)
        # Mimic uvicorn's normal lowercase HTTP header spelling.
        self.send_header("content-type", content_type)
        if buffered:
            self.send_header("x-stream-mode", "buffered")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path != "/v1/models" or self.headers.get("Authorization") != f"Bearer {KEY}":
            self.respond(401, b'{"detail":"denied"}', "application/json")
            return
        body = json.dumps({
            "object": "list",
            "data": [{"id": "clickup-ui-current", "object": "model"}],
        }).encode("utf-8")
        self.respond(200, body, "application/json")

    def do_POST(self):
        if self.path != "/v1/chat/completions" or self.headers.get("Authorization") != f"Bearer {KEY}":
            self.respond(401, b'{"detail":"denied"}', "application/json")
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length)
        body = json.loads(payload.decode("utf-8"))
        self.server.messages.append(body)
        if body.get("stream"):
            sse = make_buffered_sse("OK")
            self.respond(200, sse, "text/event-stream; charset=utf-8", buffered=True)
        else:
            result = json.dumps({
                "choices": [{"message": {"role": "assistant", "content": "OK"}}],
            }).encode("utf-8")
            self.respond(200, result, "application/json")


class RouterCheckRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeRouterGateway)
        cls.server.messages = []
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()

    def setUp(self):
        self.server.messages.clear()
        self.tmp = tempfile.TemporaryDirectory(prefix="router-smoke-fixture-")
        self.addCleanup(self.tmp.cleanup)
        self.keyfile = Path(self.tmp.name) / "key"
        self.keyfile.write_text(KEY + "\n", encoding="ascii")

    def _run(self, *arguments: str):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--key-file", str(self.keyfile),
             "--port", str(self.port), *arguments],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            timeout=15, check=False,
        )

    def test_real_http_header_names_normalized_lowercase(self):
        status, headers, payload = request_local(
            "/v1/chat/completions", KEY,
            {"model": "clickup-ui-current",
             "messages": [{"role": "user", "content": "OK"}],
             "stream": True},
            self.port,
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["x-stream-mode"], "buffered")
        self.assertTrue(headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(parse_sse_result(payload), "OK")
        self.assertTrue(all(key == key.lower() for key in headers))

    def test_cli_stream_no_false_negative(self):
        result = self._run("--stream")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Models endpoint: PASS", result.stdout)
        self.assertIn("Buffered SSE: PASS", result.stdout)
        self.assertIn("Reply preview: OK", result.stdout)
        self.assertEqual(self.server.messages[-1]["stream"], True)
        self.assertNotIn(KEY, result.stdout + result.stderr)

    def test_cli_json_and_history_unchanged(self):
        for flag in (None, "--history"):
            with self.subTest(flag=flag):
                args = (flag,) if flag else ()
                result = self._run(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("JSON Chat Completions: PASS", result.stdout)
                self.assertIn("Reply preview: OK", result.stdout)
        self.assertEqual(len(self.server.messages), 2)
        self.assertEqual(len(self.server.messages[0]["messages"]), 1)
        self.assertEqual(len(self.server.messages[1]["messages"]), 4)

    def test_rejects_missing_done_or_invalid_sse(self):
        for malformed in (
            "data: {}\n\n",
            "data: not-json\n\ndata: [DONE]\n\n",
            "",
        ):
            with self.subTest(malformed=malformed):
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    parse_sse_result(malformed)


if __name__ == "__main__":
    unittest.main()
