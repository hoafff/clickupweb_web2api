"""Offline localhost API facade tests. NO real browser or ClickUp credentials."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from tools.browser_adapter import BrowserAdapterError
from tools.local_gateway import (
    GatewayBusyError,
    GatewaySendError,
    GatewayUnavailableError,
    LiveBrowserEngine,
    create_app,
    validate_clickup_app_url,
)


KEY = "fixture-local-random-32-chars-abcdef"
AUTH = {"Authorization": f"Bearer {KEY}"}
VALID = {
    "model": "clickup-ui-current",
    "messages": [{"role": "user", "content": "Reply OK"}],
    "stream": False,
}


class FakeEngine:
    def __init__(self):
        self.ready = True
        self.response = "OK"
        self.calls = []
        self.error = None

    def is_ready(self):
        return self.ready

    async def complete(self, prompt):
        self.calls.append(prompt)
        if self.error:
            raise self.error()
        return self.response


class GatewayHTTPTests(unittest.TestCase):
    def setUp(self):
        self.engine = FakeEngine()
        self.client = TestClient(
            create_app(self.engine, api_key=KEY),
            base_url="http://127.0.0.1:8787",
        )
        self.addCleanup(self.client.close)

    def test_valid_json_completion_with_no_fabricated_usage(self):
        resp = self.client.post("/v1/chat/completions", headers=AUTH, json=VALID)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["model"], "clickup-ui-current")
        self.assertEqual(data["choices"][0]["message"]["content"], "OK")
        self.assertEqual(data["choices"][0]["message"]["role"], "assistant")
        self.assertIsNone(data["choices"][0]["finish_reason"])
        self.assertNotIn("usage", data)
        self.assertEqual(self.engine.calls, ["Reply OK"])
        self.assertTrue(data["id"].startswith("chatcmpl-local-"))

    def test_bearer_required_and_wrong_key_does_not_send(self):
        self.assertEqual(
            self.client.post("/v1/chat/completions", json=VALID).status_code, 401
        )
        self.assertEqual(
            self.client.post("/v1/chat/completions", headers={
                "Authorization": "Bearer incorrect"
            }, json=VALID).status_code, 401
        )
        self.assertEqual(self.engine.calls, [])

    def test_models_only_advertises_browser_current_alias(self):
        no_auth = self.client.get("/v1/models")
        self.assertEqual(no_auth.status_code, 401)
        data = self.client.get("/v1/models", headers=AUTH).json()
        self.assertEqual([m["id"] for m in data["data"]], ["clickup-ui-current"])

    def test_rejects_streaming_and_unverified_model(self):
        for change in [
            {"stream": True},
            {"model": "claude-opus-5-5"},
            {"n": 2},
        ]:
            with self.subTest(change=change):
                body = {**VALID, **change}
                self.assertEqual(
                    self.client.post(
                        "/v1/chat/completions", headers=AUTH, json=body
                    ).status_code, 422
                )
        self.assertEqual(self.engine.calls, [])

    def test_rejects_history_roles_tools_and_unknown_options(self):
        for change in [
            {"messages": [
                {"role": "system", "content": "override"},
                {"role": "user", "content": "ping"},
            ]},
            {"messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "answer"},
                {"role": "user", "content": "second"},
            ]},
            {"messages": [{"role": "user", "content": "  " * 5000}]},
            {"messages": [{"role": "user", "content": ""}]},
            {"temperature": 0.1},
            {"tools": []},
            {"extra": "do not silently ignore"},
        ]:
            with self.subTest(change=change):
                self.assertEqual(
                    self.client.post(
                        "/v1/chat/completions", headers=AUTH, json={
                            **VALID, **change
                        }
                    ).status_code, 422
                )
        self.assertEqual(self.engine.calls, [])

    def test_rejects_blank_even_when_nonempty_string(self):
        payload = {**VALID, "messages": [{"role": "user", "content": "   "}]}
        self.assertEqual(
            self.client.post("/v1/chat/completions", headers=AUTH, json=payload).status_code,
            422,
        )

    def test_service_states_and_safe_http_errors(self):
        self.engine.ready = False
        self.assertEqual(
            self.client.post("/v1/chat/completions", headers=AUTH, json=VALID).status_code,
            503,
        )
        self.engine.ready = True
        for error, status in [
            (GatewayBusyError, 429),
            (GatewayUnavailableError, 503),
            (GatewaySendError, 502),
        ]:
            self.engine.error = error
            response = self.client.post(
                "/v1/chat/completions", headers=AUTH, json=VALID
            )
            self.assertEqual(response.status_code, status)
            self.assertNotIn("Reply OK", response.text)

    def test_private_endpoint_host_and_docs(self):
        self.assertEqual(self.client.get("/docs").status_code, 404)
        status = self.client.get("/healthz")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["browser_ready"], True)
        self.assertEqual(
            self.client.get(
                "/healthz", headers={"Host": "attacker.example"}
            ).status_code, 400
        )

    def test_minimum_key_and_app_url_validation(self):
        with self.assertRaises(ValueError):
            create_app(self.engine, api_key="weak")
        self.assertTrue(validate_clickup_app_url("https://app.clickup.com/"))
        self.assertFalse(validate_clickup_app_url("http://app.clickup.com"))
        self.assertFalse(validate_clickup_app_url("https://app.clickup.com.attacker.test/"))
        self.assertFalse(validate_clickup_app_url("https://user:pw@app.clickup.com/"))


def start_event(result_id: str, conversation_id: str) -> str:
    return json.dumps({"event": {
        "name": "aiConversationStarted",
        "payload": {"ai_result_id": result_id, "conversation_id": conversation_id},
    }})


def comment_event(result_id: str, conversation_id: str, text: str) -> str:
    return json.dumps({"event": {
        "name": "chatCommentCreated",
        "version_event_data": {"changes": [
            {"field": "ai_result_id", "after": result_id},
            {"field": "conversation_id", "after": conversation_id},
            {"field": "comment", "after": json.dumps([{"text": text}])},
        ]},
    }})


class FakePage:
    url = "https://app.clickup.com/test-workspace/ai/brain"

    def is_closed(self):
        return False


class FakeContext:
    pages = [FakePage()]


class BrowserEngineIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = LiveBrowserEngine(profile=Path(".local/test-fixture"), url="https://app.clickup.com/")
        self.engine._context = FakeContext()
        self.engine.mark_ready()

    async def asyncTearDown(self):
        # Don't call a real Playwright browser close on fake context.
        self.engine.bridge.close()

    async def test_ui_send_and_ws_response_are_correlated(self):
        ids = iter(["a", "b"])

        async def fake_send(page, prompt, composer_css, send_css):
            self.assertIn("contenteditable", composer_css)
            self.assertIn("refinement-prompt-submit-button", send_css)
            aid = next(ids)
            self.engine.bridge.on_frame(start_event(aid, "test-chat"))
            self.engine.bridge.on_frame(comment_event(aid, "test-chat", "OK:" + prompt))

        with patch("tools.local_gateway._send_via_ui", side_effect=fake_send):
            first = await self.engine.complete("one")
            second = await self.engine.complete("two")
        self.assertEqual(first, "OK:one")
        self.assertEqual(second, "OK:two")
        self.assertEqual(self.engine.bridge.statistics()["matching_reply_comments"], 2)

    async def test_failed_send_marks_session_degraded_to_prevent_duplicate(self):
        async def fake_failure(page, prompt, composer_css, send_css):
            raise BrowserAdapterError("private prompt should never appear")

        with patch("tools.local_gateway._send_via_ui", side_effect=fake_failure):
            with self.assertRaises(GatewaySendError) as caught:
                await self.engine.complete("secret request")
        self.assertNotIn("secret request", str(caught.exception))
        self.assertFalse(self.engine.is_ready())
        with self.assertRaises(GatewayUnavailableError):
            await self.engine.complete("try again")

    async def test_concurrent_requests_fail_fast(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_send(page, prompt, composer_css, send_css):
            started.set()
            await release.wait()
            self.engine.bridge.on_frame(start_event("a", "conv"))
            self.engine.bridge.on_frame(comment_event("a", "conv", "ok"))

        with patch("tools.local_gateway._send_via_ui", side_effect=fake_send):
            first = asyncio.create_task(self.engine.complete("first"))
            await started.wait()
            with self.assertRaises(GatewayBusyError):
                await self.engine.complete("second")
            release.set()
            self.assertEqual(await first, "ok")


class GatewayEntrypointTests(unittest.TestCase):
    def test_direct_and_module_help(self):
        root = Path(__file__).resolve().parents[1]
        for cmd in [
            [sys.executable, str(root / "tools" / "local_gateway.py"), "--help"],
            [sys.executable, "-m", "tools.local_gateway", "--help"],
        ]:
            with self.subTest(cmd=cmd):
                result = subprocess.run(
                    cmd, cwd=root, capture_output=True, text=True, timeout=20
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--port", result.stdout)


if __name__ == "__main__":
    unittest.main()
