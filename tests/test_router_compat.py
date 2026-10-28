"""Basic 9Router text and buffered-SSE compatibility tests: synthetic only.

No ClickUp browser, authentication state or network access is required.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from tools.local_gateway import (
    LiveBrowserEngine, GatewaySendError, create_app,
)
from tools.router_compat import (
    RouterChatRequest, RouterMessage, flatten_messages, make_buffered_sse,
)

KEY = "synthetic-router-api-key-abcdef123456789"
AUTH = {"Authorization": f"Bearer {KEY}"}


class StubEngine:
    def __init__(self, *, isolated=True):
        self.new_chat_per_request = isolated
        self.ready = True
        self.calls = []

    def is_ready(self):
        return self.ready

    def session_diagnostics(self):
        return {
            "completed_replies": len(self.calls),
            "same_conversation_pairs": 0,
            "different_conversation_pairs": 0,
            "last_relation": "unobserved",
        }

    async def complete(self, prompt):
        self.calls.append(prompt)
        return "Xin chào, OK."


class RouterHTTPTests(unittest.TestCase):
    def setUp(self):
        self.engine = StubEngine()
        self.client = TestClient(
            create_app(self.engine, api_key=KEY, router_mode=True),
            base_url="http://127.0.0.1:8787",
        )
        self.addCleanup(self.client.close)

    def request(self, **changes):
        return {
            "model": "clickup-ui-current",
            "messages": [{"role": "user", "content": "Reply OK"}],
            "stream": False,
            **changes,
        }

    def test_basic_nonstream_chat_and_discovery(self):
        models = self.client.get("/v1/models", headers=AUTH)
        self.assertEqual(models.status_code, 200)
        self.assertEqual(models.json()["data"][0]["id"], "clickup-ui-current")
        r = self.client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json=self.request(),
        )
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["choices"][0]["message"]["content"], "Xin chào, OK.")
        self.assertEqual(d["model"], "clickup-ui-current")
        self.assertNotIn("usage", d)
        self.assertIsNone(d["choices"][0]["finish_reason"])
        self.assertEqual(self.engine.calls, ["Reply OK"])

    def test_buffered_sse_frames_are_valid_unicode(self):
        r = self.client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json=self.request(stream=True),
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(r.headers["x-stream-mode"], "buffered")
        events = [
            x.removeprefix("data: ")
            for x in r.text.split("\n\n") if x.startswith("data: ")
        ]
        self.assertEqual(events[-1], "[DONE]")
        chunks = [json.loads(x) for x in events[:-1]]
        self.assertEqual(
            [x["object"] for x in chunks],
            ["chat.completion.chunk"] * 3,
        )
        self.assertEqual(chunks[0]["choices"][0]["delta"]["role"], "assistant")
        self.assertEqual(
            chunks[1]["choices"][0]["delta"]["content"],
            "Xin chào, OK.",
        )
        self.assertIsNone(chunks[-1]["choices"][0]["finish_reason"])
        self.assertEqual(self.engine.calls, ["Reply OK"])

    def test_history_is_serialized_not_discarded(self):
        body = self.request(messages=[
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "Name a word."},
            {"role": "assistant", "content": "ALPHA"},
            {"role": "user", "content": "What was that word?"},
        ])
        r = self.client.post("/v1/chat/completions", headers=AUTH, json=body)
        self.assertEqual(r.status_code, 200, r.text)
        sent = self.engine.calls[-1]
        self.assertIn('"role":"system"', sent)
        self.assertIn('"role":"assistant"', sent)
        self.assertIn("ALPHA", sent)
        self.assertIn("not privileged", sent)
        self.assertIn("What was that word?", sent)

    def test_rejects_tools_images_sampling_and_long_history(self):
        invalid = [
            {"tools": [{"type": "function", "function": {"name": "shell"}}]},
            {"tool_choice": "auto"},
            {"temperature": 0.9},
            {"max_tokens": 500},
            {"response_format": {"type": "json_object"}},
            {"messages": [{"role": "user", "content": [
                {"type": "text", "text": "ping"},
                {"type": "image_url", "image_url": {"url": "data:xx"}},
            ]}]},
            {"messages": [{"role": "tool", "content": "done"}]},
            {"messages": [{"role": "assistant", "content": "No user"}]},
            {"messages": [{"role": "user", "content": "x"}] * 33},
            {"model": "cc/claude-opus-5-5"},
            {"unrecognized": True},
        ]
        for body in invalid:
            with self.subTest(body=str(body)[:60]):
                r = self.client.post(
                    "/v1/chat/completions",
                    headers=AUTH,
                    json=self.request(**body),
                )
                self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(self.engine.calls, [])

    def test_rejects_history_exceeding_composer(self):
        body = self.request(messages=[
            {"role": "system", "content": "x" * 7900},
            {"role": "user", "content": "Hello"},
        ])
        r = self.client.post("/v1/chat/completions", headers=AUTH, json=body)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.engine.calls, [])

    def test_missing_auth_rejected(self):
        r = self.client.post("/v1/chat/completions", json=self.request())
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.engine.calls, [])

    def test_requires_isolated_browser_worker_and_disallows_owner_combo(self):
        self.engine.new_chat_per_request = False
        r = self.client.post(
            "/v1/chat/completions", headers=AUTH, json=self.request()
        )
        self.assertEqual(r.status_code, 503)
        with self.assertRaises(ValueError):
            create_app(self.engine, api_key=KEY, router_mode=True, require_session=True)


class FakeLocator:
    async def wait_for(self, *, state, timeout):
        assert state == "visible"


class FakeBrowserPage:
    def __init__(self):
        self.url = "https://app.clickup.com/123/ai/brain?conversationId=old"
        self.navigate_calls = []

    def is_closed(self):
        return False

    async def goto(self, target, *, wait_until, timeout):
        self.navigate_calls.append(target)
        self.url = target

    def locator(self, selector):
        self.last_selector = selector
        return FakeLocator()


class FakeContext:
    def __init__(self, page):
        self.pages = [page]


def started(rid, cid):
    return json.dumps({"event": {
        "name": "aiConversationStarted",
        "payload": {"ai_result_id": rid, "conversation_id": cid},
    }})


def created(rid, cid, text):
    return json.dumps({"event": {
        "name": "chatCommentCreated",
        "version_event_data": {"changes": [
            {"field": "ai_result_id", "after": rid},
            {"field": "conversation_id", "after": cid},
            {"field": "comment", "after": json.dumps([{"text": text}])},
        ]},
    }})


class RouterBrowserIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.page = FakeBrowserPage()
        self.engine = LiveBrowserEngine(
            profile=Path(".local/synthetic-not-used"),
            url="https://app.clickup.com/",
            new_chat_per_request=True,
            strict_conversation=False,
        )
        self.engine._context = FakeContext(self.page)
        self.engine.mark_ready()

    async def asyncTearDown(self):
        self.engine.bridge.close()

    async def test_every_request_navigates_fresh_brain_landing(self):
        async def fake_send(page, prompt, composer_css, send_css):
            n = len(page.navigate_calls)
            self.assertNotIn("conversationId", page.url)
            self.engine.bridge.on_frame(started("rid" + str(n), "chat" + str(n)))
            self.engine.bridge.on_frame(created("rid" + str(n), "chat" + str(n), "OK"))

        with patch("tools.local_gateway._send_via_ui", side_effect=fake_send):
            self.assertEqual(await self.engine.complete("A"), "OK")
            self.assertEqual(await self.engine.complete("B"), "OK")
        self.assertEqual(self.page.navigate_calls, [
            "https://app.clickup.com/123/ai/brain",
            "https://app.clickup.com/123/ai/brain",
        ])
        self.assertEqual(self.engine.session_diagnostics()["different_conversation_pairs"], 1)

    async def test_redirect_back_to_old_conversation_fails_closed(self):
        async def redirected(target, *, wait_until, timeout):
            self.page.url = target + "?conversationId=old"
        self.page.goto = redirected
        with patch("tools.local_gateway._send_via_ui") as send:
            with self.assertRaises(GatewaySendError):
                await self.engine.complete("test")
            send.assert_not_called()
        self.assertFalse(self.engine.is_ready())


if __name__ == "__main__":
    unittest.main()
