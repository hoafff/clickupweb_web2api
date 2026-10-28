"""UI research safeguards and opt-in endpoint offline tests.

No browser, no real account and no actual ClickUp/9Router requests.
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from tools.brain_ui_state_probe import (
    BOOLEAN_FIELDS, COUNT_FIELDS, BRAIN_UI_STATE_JS, sanitize_ui_snapshot,
)
from tools.check_brain_ui_state import (
    ResearchProbeError, collect, get_snapshot, main, summarise,
)
from tools.local_gateway import create_app

KEY = "synthetic-UI-research-gateway-authorization-key"
AUTH = {"Authorization": "Bearer " + KEY}
PRIVATE = "SECRET_TEXT_DO_NOT_ECHO"

SAMPLE = {
    "page_is_brain": True,
    "document_visible": True,
    "composer_visible": True,
    "composer_disabled": False,
    "send_visible": True,
    "send_disabled": False,
    "visible_button_count": 7,
    "stop_candidate_count": 1,
    "stop_near_composer_count": 1,
    "generating_candidate_count": 1,
    "visible_progressbar_count": 0,
    "visible_aria_busy_count": 1,
}


class StubEngine:
    def __init__(self, *, ready=True, snapshot=None):
        self.ready = ready
        self.snapshot = snapshot or SAMPLE
        self.calls = 0

    def is_ready(self):
        return self.ready

    async def snapshot_ui_state(self):
        self.calls += 1
        return self.snapshot

    async def complete(self, prompt):
        return "OK"

    def session_diagnostics(self):
        return {
            "completed_replies": 0,
            "same_conversation_pairs": 0,
            "different_conversation_pairs": 0,
            "last_relation": "unobserved",
        }


class UIStateUnitTests(unittest.TestCase):
    def test_only_boolean_and_bounded_ints_are_exported(self):
        snapshot = {**SAMPLE, "secret_message": PRIVATE,
                    "conversation_id": PRIVATE, "account": PRIVATE}
        cleaned = sanitize_ui_snapshot(snapshot)
        self.assertEqual(cleaned, SAMPLE)
        self.assertNotIn(PRIVATE, json.dumps(cleaned))
        for field in BOOLEAN_FIELDS:
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    sanitize_ui_snapshot({**SAMPLE, field: PRIVATE})
        for field in COUNT_FIELDS:
            with self.subTest(field=field):
                for invalid in (True, -1, 501, PRIVATE):
                    with self.assertRaises(ValueError):
                        sanitize_ui_snapshot({**SAMPLE, field: invalid})

    def test_browser_js_does_not_read_message_values(self):
        self.assertNotIn(".textContent", BRAIN_UI_STATE_JS)
        self.assertNotIn(".innerText", BRAIN_UI_STATE_JS)
        self.assertNotIn(".innerHTML", BRAIN_UI_STATE_JS)
        self.assertNotIn("localStorage", BRAIN_UI_STATE_JS)
        self.assertNotIn("document.cookie", BRAIN_UI_STATE_JS)
        self.assertNotIn(".value", BRAIN_UI_STATE_JS)
        self.assertNotIn("fetch(", BRAIN_UI_STATE_JS)
        self.assertNotIn("click(", BRAIN_UI_STATE_JS)

    def test_summary_restricts_output_to_fixed_keys_and_counts(self):
        changed = {**SAMPLE, "stop_candidate_count": 0,
                   "generating_candidate_count": 0,
                   "visible_aria_busy_count": 0, "conversation_id": PRIVATE}
        # Summarise should be called only on sanitized snapshot outputs.
        clean_changed = sanitize_ui_snapshot(changed)
        summary = summarise([SAMPLE, clean_changed], 1)
        self.assertEqual(summary["samples"], 2)
        self.assertEqual(summary["failed_samples"], 1)
        self.assertEqual(summary["different_snapshot_shapes"], 2)
        self.assertEqual(summary["stop_control_hint_samples"], 1)
        self.assertEqual(summary["generating_control_hint_samples"], 1)
        self.assertNotIn(PRIVATE, json.dumps(summary))
        self.assertIn("NOT a verified", summary["interpretation"])


class UIResearchEndpointTests(unittest.TestCase):
    def test_off_by_default_even_with_valid_authorization(self):
        stub = StubEngine()
        with TestClient(create_app(stub, api_key=KEY, router_mode=True)) as client:
            r = client.get("/v1/research/ui-state", headers=AUTH)
            self.assertEqual(r.status_code, 404)
            self.assertEqual(stub.calls, 0)

    def test_opt_in_requires_bearer_and_never_leaks_extra_fields(self):
        stub = StubEngine()
        stub.snapshot = {**SAMPLE, "prompt": PRIVATE, "cookie": PRIVATE}
        with TestClient(create_app(
            stub, api_key=KEY, router_mode=True, ui_research=True,
        )) as client:
            self.assertEqual(client.get("/v1/research/ui-state").status_code, 401)
            self.assertEqual(stub.calls, 0)
            r = client.get("/v1/research/ui-state", headers=AUTH)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json(), SAMPLE)
            self.assertNotIn(PRIVATE, r.text)

    def test_probe_fail_closed_if_not_ready_or_malformed(self):
        stub = StubEngine(ready=False)
        with TestClient(create_app(
            stub, api_key=KEY, router_mode=True, ui_research=True,
        )) as client:
            self.assertEqual(
                client.get("/v1/research/ui-state", headers=AUTH).status_code,
                503,
            )
            self.assertEqual(stub.calls, 0)
            stub.ready = True
            stub.snapshot = {"text": PRIVATE}
            r = client.get("/v1/research/ui-state", headers=AUTH)
            self.assertEqual(r.status_code, 503)
            self.assertNotIn(PRIVATE, r.text)

    def test_strict_lease_required_when_research_enabled(self):
        stub = StubEngine()
        with TestClient(create_app(
            stub, api_key=KEY, require_session=True, ui_research=True,
        )) as client:
            self.assertEqual(
                client.get("/v1/research/ui-state", headers=AUTH).status_code,
                409,
            )
            claim = client.post("/v1/session/claim", headers=AUTH)
            self.assertEqual(claim.status_code, 200)
            token = claim.json()["session_token"]
            self.assertEqual(
                client.get("/v1/research/ui-state", headers={
                    **AUTH, "X-ClickUp-Session": token,
                }).status_code, 200
            )


class FakeHTTPGateway(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != "/v1/research/ui-state":
            self.send_error(404)
            return
        if self.headers.get("Authorization") != "Bearer " + KEY:
            self.send_response(401)
            self.end_headers()
            return
        body = json.dumps({**SAMPLE, "secret": PRIVATE}).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class UIResearchClientLoopbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHTTPGateway)
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

    def test_snapshot_over_real_local_http_and_no_raw_secret(self):
        observed = get_snapshot(port=self.port, key=KEY)
        self.assertEqual(observed, SAMPLE)
        self.assertNotIn(PRIVATE, json.dumps(observed))
        with self.assertRaises(ResearchProbeError):
            get_snapshot(port=self.port, key="wrong")

    def test_collect_stops_and_handles_bounded_samples(self):
        seen, fails = collect(
            port=self.port, key=KEY, samples=3, interval=0.2
        )
        self.assertEqual(len(seen), 3)
        self.assertEqual(fails, 0)
        self.assertEqual(summarise(seen, fails)["samples"], 3)

    def test_cli_snapshot_and_watch_no_prompt(self):
        import contextlib
        from tools.check_brain_ui_state import main
        with tempfile.TemporaryDirectory(prefix="research-fixture-") as folder:
            key = Path(folder) / "gateway.key"
            key.write_text(KEY + "\n", encoding="ascii")
            with patch("tools.check_brain_ui_state.get_snapshot", wraps=get_snapshot) as spy:
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    result = main([
                        "--snapshot", "--port", str(self.port),
                        "--key-file", str(key),
                    ])
                self.assertEqual(result, 0)
                self.assertEqual(spy.call_count, 1)
                self.assertNotIn(PRIVATE, stdout.getvalue())
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    result = main([
                        "--watch", "--samples", "2", "--interval", "0.2",
                        "--port", str(self.port), "--key-file", str(key),
                    ])
                self.assertEqual(result, 0)
                self.assertIn('"samples": 2', stdout.getvalue())
                self.assertNotIn(PRIVATE, stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
