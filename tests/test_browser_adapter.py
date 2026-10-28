"""Offline browser-adapter tests: no login, network, session or prompt capture."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess
import sys
import unittest

from tools.browser_adapter import (
    BrainBrowserBridge,
    BrowserAdapterError,
    _parse_ws_payload,
    _send_via_ui,
    _ws_in_scope,
)


def frame(name: str, *, result: str = "r1", conv: str = "c1",
          text: str = "Hello") -> str:
    event = {"name": name}
    if name == "aiConversationStarted":
        event["payload"] = {"ai_result_id": result, "conversation_id": conv}
    elif name == "chatCommentCreated":
        event["version_event_data"] = {"changes": [
            {"field": "ai_result_id", "after": result},
            {"field": "conversation_id", "after": conv},
            {"field": "comment", "after": json.dumps([{"text": text}])},
        ]}
    return json.dumps({"event": event})


class _FakeLocator:
    def __init__(self, *, count: int = 1, visible: bool = True,
                 enabled: bool = True, on_fill=None):
        self._count = count
        self._visible = visible
        self._enabled = enabled
        self.on_fill = on_fill
        self.filled = None
        self.clicked = False

    async def count(self):
        return self._count

    async def is_visible(self):
        return self._visible

    async def is_enabled(self):
        return self._enabled

    async def wait_for(self, *, state, timeout):
        assert state == "visible"
        if not self._visible or self._count == 0:
            from playwright.async_api import Error as PlaywrightError
            raise PlaywrightError("not visible")

    async def fill(self, value, *, timeout):
        self.filled = value
        if self.on_fill is not None:
            self.on_fill()

    async def click(self, *, timeout):
        self.clicked = True


class _FakePage:
    def __init__(self, composer: _FakeLocator, sender: _FakeLocator):
        self.composer, self.sender = composer, sender

    def locator(self, selector):
        return {"[data-test=composer]": self.composer,
                "[data-test=send]": self.sender}[selector]


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bridge = BrainBrowserBridge()

    async def asyncTearDown(self):
        self.bridge.close()

    async def test_start_reply_matches_in_one_armed_ui_operation(self):
        self.bridge.arm()
        waiter = asyncio.create_task(self.bridge.await_reply_created(timeout=1))
        await asyncio.sleep(0)
        self.bridge.on_frame(frame("aiConversationStarted"))
        self.bridge.on_frame(frame("chatCommentCreated", text="OK"))
        reply = await waiter
        self.assertEqual(reply.text, "OK")
        self.assertEqual(reply.conversation_id, "c1")
        self.assertEqual(self.bridge.statistics()["matching_reply_comments"], 1)

    async def test_created_before_start(self):
        self.bridge.arm()
        waiter = asyncio.create_task(self.bridge.await_reply_created(timeout=1))
        await asyncio.sleep(0)
        self.bridge.on_frame(frame("chatCommentCreated", text="reply first"))
        self.bridge.on_frame(frame("aiConversationStarted"))
        self.assertEqual((await waiter).text, "reply first")

    async def test_duplicate_start_is_ignored(self):
        self.bridge.arm()
        waiter = asyncio.create_task(self.bridge.await_reply_created(timeout=1))
        await asyncio.sleep(0)
        self.bridge.on_frame(frame("aiConversationStarted"))
        self.bridge.on_frame(frame("aiConversationStarted"))
        self.bridge.on_frame(frame("chatCommentCreated"))
        self.assertEqual((await waiter).text, "Hello")

    async def test_multiple_unrelated_ai_starts_fail_closed(self):
        self.bridge.arm()
        waiter = asyncio.create_task(self.bridge.await_reply_created(timeout=1))
        await asyncio.sleep(0)
        self.bridge.on_frame(frame("aiConversationStarted", result="r1", conv="c1"))
        self.bridge.on_frame(frame("aiConversationStarted", result="r2", conv="c2"))
        with self.assertRaisesRegex(BrowserAdapterError, "More than one"):
            await waiter

    async def test_timeout_and_disarm(self):
        self.bridge.arm()
        with self.assertRaisesRegex(BrowserAdapterError, "No aiConversationStarted"):
            await self.bridge.await_reply_created(timeout=0.003)
        with self.assertRaisesRegex(BrowserAdapterError, "not armed"):
            await self.bridge.await_reply_created(timeout=0.003)

    async def test_unarmed_ai_started_does_not_enqueue(self):
        self.bridge.on_frame(frame("aiConversationStarted"))
        self.bridge.arm()
        with self.assertRaisesRegex(BrowserAdapterError, "No aiConversationStarted"):
            await self.bridge.await_reply_created(timeout=0.003)

    async def test_scope_and_json_validation(self):
        self.assertTrue(_ws_in_scope(
            "wss://frontdoor-prod-ap-southeast-1-1.clickup.com/ws"))
        self.assertFalse(_ws_in_scope("wss://clickup.com.evil.org/ws"))
        self.assertFalse(_ws_in_scope("https://frontdoor.clickup.com/ws"))
        self.assertFalse(_ws_in_scope("wss://frontdoor.clickup.com/other"))
        self.assertIsNone(_parse_ws_payload(b"binary"))
        self.assertIsNone(_parse_ws_payload("not-json"))
        self.assertIsNone(_parse_ws_payload('{"not_event":true}'))

    async def test_ui_requires_unique_and_visible_controls(self):
        composer = _FakeLocator(count=2)
        sender = _FakeLocator()
        page = _FakePage(composer, sender)
        with self.assertRaisesRegex(BrowserAdapterError, "exactly one"):
            await _send_via_ui(page, "ping", "[data-test=composer]", "[data-test=send]")
        self.assertIsNone(composer.filled)
        self.assertFalse(sender.clicked)

        composer._count = 1
        sender._visible = False
        with self.assertRaisesRegex(BrowserAdapterError, "not visible"):
            await _send_via_ui(page, "ping", "[data-test=composer]", "[data-test=send]")
        self.assertEqual(composer.filled, "ping")
        self.assertFalse(sender.clicked)

        sender._visible = True
        await _send_via_ui(page, "ping", "[data-test=composer]", "[data-test=send]")
        self.assertEqual(composer.filled, "ping")
        self.assertTrue(sender.clicked)

    async def test_send_button_can_appear_only_after_typing(self):
        sender = _FakeLocator(count=0, visible=False)
        composer = _FakeLocator(on_fill=lambda: (
            setattr(sender, "_count", 1),
            setattr(sender, "_visible", True),
        ))
        page = _FakePage(composer, sender)
        await _send_via_ui(
            page, "OK", "[data-test=composer]", "[data-test=send]"
        )
        self.assertEqual(composer.filled, "OK")
        self.assertTrue(sender.clicked)

    async def test_disabled_send_never_clicked(self):
        sender = _FakeLocator(enabled=False)
        composer = _FakeLocator()
        page = _FakePage(composer, sender)
        with self.assertRaisesRegex(BrowserAdapterError, "disabled"):
            await _send_via_ui(
                page, "OK", "[data-test=composer]", "[data-test=send]"
            )
        self.assertFalse(sender.clicked)

    async def test_missing_or_blank_prompt_refuses_send(self):
        sender = _FakeLocator()
        page = _FakePage(_FakeLocator(), sender)
        with self.assertRaises(BrowserAdapterError):
            await _send_via_ui(page, " ", "[data-test=composer]", "[data-test=send]")
        self.assertFalse(sender.clicked)


class BrowserAdapterEntrypointTests(unittest.TestCase):
    def test_direct_and_module_help_do_not_import_fail(self):
        project = Path(__file__).resolve().parents[1]
        scripts = [
            [sys.executable, str(project / "tools" / "browser_adapter.py"), "--help"],
            [sys.executable, "-m", "tools.browser_adapter", "--help"],
        ]
        for args in scripts:
            with self.subTest(args=args):
                p = subprocess.run(
                    args, cwd=project, capture_output=True, text=True,
                    timeout=15, check=False,
                )
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIn("--mode", p.stdout)
                self.assertIn("--confirm-send", p.stdout)


if __name__ == "__main__":
    unittest.main()
