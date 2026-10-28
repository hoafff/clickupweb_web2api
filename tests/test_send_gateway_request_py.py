"""Real loopback-wire tests for the Python gateway client.

Uses a SYNTHETIC HTTP server bound to 127.0.0.1:0. Never contacts ClickUp,
reads a browser profile, or uses the researcher's actual gateway key.
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

from tools.send_gateway_request import (
    load_session_token,
    write_session_token_once,
    LocalClientError,
    encode_request,
    get_answer,
    load_key,
    request_json,
    safe_diagnostics,
)

KEY = "synthetic-research-gateway-key-123456789"
SECRET = "private-chat-content-never-exposed"
PY_CLIENT = Path(__file__).resolve().parents[1] / "tools" / "send_gateway_request.py"


class GatewayHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # No raw HTTP request logging.
        pass

    def send_json(self, code, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path == "/v1/session/claim":
            self.server.received.append({
                "method": "POST",
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
            })
            if self.headers.get("Authorization") != f"Bearer {KEY}":
                self.send_json(401, {"detail": SECRET})
                return
            self.send_json(200, {
                "object": "browser.session",
                "session_token": "synthetic-owner-token-at-least-32-characters",
            })
            return
        if self.path != "/v1/chat/completions":
            self.send_json(404, {"detail": "not found"})
            return
        size = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(size)
        self.server.received.append({
            "method": "POST",
            "authorization": self.headers.get("Authorization"),
            "owner": self.headers.get("X-ClickUp-Session"),
            "content_type": self.headers.get("Content-Type"),
            "raw": raw,
        })
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            self.send_json(401, {"detail": SECRET})
            return
        try:
            request = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"detail": SECRET})
            return
        self.server.received[-1]["parsed"] = request
        self.send_json(200, {
            "choices": [{"message": {"role": "assistant", "content": "OK"}}]
        })

    def do_GET(self):
        if self.path != "/v1/session/diagnostics":
            self.send_json(404, {"detail": "not found"})
            return
        self.server.received.append({
            "method": "GET",
            "authorization": self.headers.get("Authorization"),
        })
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            self.send_json(401, {"detail": SECRET})
            return
        self.send_json(200, {
            "completed_replies": 2,
            "same_conversation_pairs": 1,
            "different_conversation_pairs": 0,
            "last_relation": "same",
            "conversation_id": SECRET,
            "ai_result_id": SECRET,
        })


class PythonGatewayClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        cls.server.received = []
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()

    def setUp(self):
        self.server.received.clear()
        self.tmp = tempfile.TemporaryDirectory(prefix="brain-gateway-client-")
        self.addCleanup(self.tmp.cleanup)
        self.key_path = Path(self.tmp.name) / "key"
        self.key_path.write_text(KEY + "\n", encoding="ascii")

    def test_utf8_vietnamese_request_over_real_loopback_tcp(self):
        prompt = "Trả lời đúng một từ: OK"
        raw = encode_request(prompt)
        self.assertIn(prompt.encode("utf-8"), raw)
        response = request_json(
            port=self.port, key=load_key(self.key_path),
            path="/v1/chat/completions", body=raw, timeout=5,
        )
        self.assertEqual(get_answer(response), "OK")
        received = self.server.received
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["parsed"]["messages"][0]["content"], prompt)
        self.assertEqual(received[0]["content_type"], "application/json; charset=utf-8")
        self.assertEqual(received[0]["authorization"], f"Bearer {KEY}")
        self.assertIs(received[0]["parsed"]["stream"], False)

    def test_safe_diagnostics_strips_private_server_fields(self):
        raw = request_json(
            port=self.port, key=KEY, path="/v1/session/diagnostics", timeout=5
        )
        output = safe_diagnostics(raw)
        self.assertEqual(output["completed_replies"], 2)
        self.assertEqual(output["last_relation"], "same")
        self.assertNotIn(SECRET, json.dumps(output))
        self.assertNotIn("conversation_id", output)

    def test_exclusive_session_client_claim_and_local_owner_file(self):
        # Test file is inside a synthetic repo .local folder; never uses
        # the researcher's real account key or active browser profile.
        test_root = Path(self.tmp.name)
        owner_file = test_root / ".local" / "owner.key"
        with patch("tools.send_gateway_request.PROJECT_ROOT", test_root):
            claim = request_json(
                port=self.port, key=KEY, path="/v1/session/claim", timeout=5,
            )
            write_session_token_once(owner_file, claim["session_token"])
            token = load_session_token(owner_file)
            with self.assertRaises(LocalClientError):
                write_session_token_once(owner_file, claim["session_token"])
        answer = request_json(
            port=self.port, key=KEY, path="/v1/chat/completions",
            body=encode_request("Reply OK"), timeout=5,
            session_token=token,
        )
        self.assertEqual(get_answer(answer), "OK")
        self.assertEqual(self.server.received[-1]["owner"], token)
        self.assertNotIn(token, json.dumps(answer))

    def test_invalid_key_never_echoes_server_response_body(self):
        with self.assertRaises(LocalClientError) as cm:
            request_json(
                port=self.port, key="wrong-key", path="/v1/chat/completions",
                body=encode_request("Test"), timeout=5,
            )
        self.assertIn("HTTP 401", str(cm.exception))
        self.assertNotIn(SECRET, str(cm.exception))
        self.assertNotIn(KEY, str(cm.exception))

    def test_cli_direct_script_sends_unicode_and_prints_only_reply(self):
        prompt = "Xin chào, chỉ trả lời OK"
        proc = subprocess.run(
            [sys.executable, str(PY_CLIENT),
             "--key-file", str(self.key_path),
             "--port", str(self.port),
             "--timeout", "5",
             "--prompt", prompt],
            cwd=PY_CLIENT.parents[1], capture_output=True, text=True,
            timeout=12, check=False, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "OK")
        self.assertNotIn(KEY, proc.stdout + proc.stderr)
        self.assertNotIn(prompt, proc.stdout + proc.stderr)

    def test_cli_diagnostics_not_leak_server_ids(self):
        proc = subprocess.run(
            [sys.executable, str(PY_CLIENT),
             "--key-file", str(self.key_path),
             "--port", str(self.port),
             "--diagnostics", "--timeout", "5"],
            cwd=PY_CLIENT.parents[1], capture_output=True, text=True,
            timeout=12, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["last_relation"], "same")
        self.assertNotIn(SECRET, proc.stdout)

    def test_empty_prompts_and_bad_diagnostics_rejected(self):
        for prompt in ("", " ", "x" * 8001):
            with self.assertRaises(LocalClientError):
                encode_request(prompt)
        with self.assertRaises(LocalClientError):
            safe_diagnostics({
                "completed_replies": 2,
                "same_conversation_pairs": 0,
                "different_conversation_pairs": 1,
                "last_relation": SECRET,
            })

    def test_missing_key_does_not_disclose_path(self):
        with self.assertRaises(LocalClientError) as cm:
            load_key(Path(self.tmp.name) / "missing-secret-file")
        self.assertNotIn(self.tmp.name, str(cm.exception))

    def test_client_rejects_external_endpoint_path_or_bad_port(self):
        with self.assertRaises(LocalClientError):
            request_json(port=self.port, key=KEY, path="http://evil.example/")
        with self.assertRaises(LocalClientError):
            request_json(port=999, key=KEY, path="/v1/session/diagnostics")


if __name__ == "__main__":
    unittest.main()
