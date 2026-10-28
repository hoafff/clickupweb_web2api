"""Offline async correlator tests; no ClickUp credentials, network, or tokens."""
import asyncio
import json
import unittest

from tools.conversation_correlator import (
    ConversationEventCorrelator,
    ConversationMismatchError,
    CorrelationExpiredError,
    CorrelatorClosedError,
    CorrelationError,
)


def started(result, conversation, *, at="2026-10-28T05:00:01+00:00"):
    return {
        "kind": "ws_frame_content", "direction": "received", "timestamp_utc": at,
        "payload": {"data": {"event": {
            "name": "aiConversationStarted",
            "payload": {"ai_result_id": result, "conversation_id": conversation},
        }}},
    }


def created(result, conversation, text, *, at="2026-10-28T05:00:02+00:00"):
    fields = [
        {"field": "comment", "after": json.dumps([{"text": text, "attributes": {}}])},
        {"field": "ai_result_id", "after": result},
        {"field": "conversation_id", "after": conversation},
    ]
    return {
        "kind": "ws_frame_content", "direction": "received", "timestamp_utc": at,
        "payload": {"data": {"event": {
            "name": "chatCommentCreated",
            "version_event_data": {"changes": fields},
        }}},
    }


class CorrelatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.c = ConversationEventCorrelator(scope_id="fixture-workspace")

    async def asyncTearDown(self):
        self.c.close()

    async def test_two_interleaved_conversations_do_not_cross(self):
        a = asyncio.create_task(self.c.wait_for_created("a", conversation_id="chat-a"))
        b = asyncio.create_task(self.c.wait_for_created("b", conversation_id="chat-b"))
        await asyncio.sleep(0)
        self.assertEqual(self.c.ingest(started("a", "chat-a")), "started")
        self.assertEqual(self.c.ingest(started("b", "chat-b")), "started")
        self.assertEqual(self.c.ingest(created("b", "chat-b", "response B")), "reply_created")
        self.assertEqual(self.c.ingest(created("a", "chat-a", "response A")), "reply_created")
        ra, rb = await asyncio.gather(a, b)
        self.assertEqual(ra.text, "response A")
        self.assertEqual(rb.text, "response B")
        self.assertEqual(ra.conversation_id, "chat-a")
        self.assertEqual(rb.conversation_id, "chat-b")
        self.assertEqual(self.c.statistics()["matched"], 2)

    async def test_reply_arrives_before_start(self):
        waiter = asyncio.create_task(self.c.wait_for_created("late"))
        await asyncio.sleep(0)
        self.assertEqual(self.c.ingest(created("late", "conv", "early reply")), "reply_buffered")
        self.assertFalse(waiter.done())
        self.assertEqual(self.c.ingest(started("late", "conv")), "started")
        self.assertEqual((await waiter).text, "early reply")

    async def test_duplicate_events_are_idempotent(self):
        self.assertEqual(self.c.ingest(started("x", "conv")), "started")
        self.assertEqual(self.c.ingest(started("x", "conv")), "duplicate_start")
        self.assertEqual(self.c.ingest(created("x", "conv", "hello")), "reply_created")
        self.assertEqual(self.c.ingest(created("x", "conv", "hello")), "duplicate_comment")
        self.assertEqual((await self.c.wait_for_created("x")).text, "hello")
        self.assertEqual(self.c.statistics()["matched"], 1)

    async def test_conversation_mismatch_rejects_reply(self):
        task = asyncio.create_task(self.c.wait_for_created("x", conversation_id="expected"))
        await asyncio.sleep(0)
        self.assertEqual(self.c.ingest(started("x", "expected")), "started")
        self.assertEqual(self.c.ingest(created("x", "different", "wrong")), "mismatch")
        with self.assertRaises(ConversationMismatchError):
            await task
        self.assertEqual(self.c.statistics()["mismatches"], 1)

    async def test_conflicting_duplicate_is_not_silently_accepted(self):
        self.c.ingest(started("x", "conv"))
        self.c.ingest(created("x", "conv", "v1"))
        self.assertEqual(self.c.ingest(created("x", "conv", "v2")), "conflict")
        with self.assertRaises(CorrelationError):
            await self.c.wait_for_created("x")

    async def test_one_waiter_timeout_does_not_cancel_other(self):
        fast = asyncio.create_task(self.c.wait_for_created("x", timeout=0.001))
        slow = asyncio.create_task(self.c.wait_for_created("x", timeout=2))
        with self.assertRaises(asyncio.TimeoutError):
            await fast
        self.c.ingest(started("x", "conv"))
        self.c.ingest(created("x", "conv", "reply"))
        self.assertEqual((await slow).text, "reply")

    async def test_cancelled_waiter_does_not_prevent_later_reader(self):
        task = asyncio.create_task(self.c.wait_for_created("x"))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.c.ingest(started("x", "conv"))
        self.c.ingest(created("x", "conv", "still available"))
        self.assertEqual((await self.c.wait_for_created("x")).text, "still available")

    async def test_expiry_with_injected_clock(self):
        now = [0.0]
        corr = ConversationEventCorrelator(
            scope_id="workspace", ttl_seconds=5, clock=lambda: now[0]
        )
        try:
            waiter = asyncio.create_task(corr.wait_for_created("x"))
            await asyncio.sleep(0)
            now[0] += 5.1
            self.assertEqual(corr.prune(), 1)
            with self.assertRaises(CorrelationExpiredError):
                await waiter
            self.assertEqual(corr.statistics()["cached_records"], 0)
        finally:
            corr.close()

    async def test_capacity_eviction_rejects_old_pending(self):
        corr = ConversationEventCorrelator(scope_id="workspace", max_records=1)
        try:
            waiter = asyncio.create_task(corr.wait_for_created("old"))
            await asyncio.sleep(0)
            corr.ingest(started("new", "new-conv"))
            with self.assertRaises(CorrelationExpiredError):
                await waiter
            self.assertEqual(corr.statistics()["evicted"], 1)
        finally:
            corr.close()

    async def test_sent_ws_and_user_comment_are_ignored(self):
        e = started("x", "conv")
        e["direction"] = "sent"
        self.assertEqual(self.c.ingest(e), "ignored_sent")
        self.assertEqual(self.c.ingest({
            "kind": "ws_frame_content", "payload": {"data": {
                "event": {"name": "chatCommentCreated", "version_event_data": {
                    "changes": [{"field": "comment", "after": '[{"text":"hi"}]'}]
                }}
            }}
        }), "ignored_user_comment")
        self.assertEqual(self.c.statistics()["cached_records"], 0)

    async def test_close_fails_pending_waiter(self):
        waiter = asyncio.create_task(self.c.wait_for_created("x"))
        await asyncio.sleep(0)
        self.c.close()
        with self.assertRaises(CorrelatorClosedError):
            await waiter

    async def test_invalid_rich_text_does_not_satisfy_waiter(self):
        self.c.ingest(started("x", "conv"))
        event = created("x", "conv", "good")
        event["payload"]["data"]["event"]["version_event_data"]["changes"][0]["after"] = "not-json"
        self.assertEqual(self.c.ingest(event), "invalid_comment")
        self.assertEqual(self.c.statistics().get("matched", 0), 0)

    async def test_scopes_are_separate_instances(self):
        a = ConversationEventCorrelator(scope_id="workspace-a")
        b = ConversationEventCorrelator(scope_id="workspace-b")
        try:
            a.ingest(started("id", "conv"))
            a.ingest(created("id", "conv", "only-a"))
            self.assertEqual((await a.wait_for_created("id")).text, "only-a")
            with self.assertRaises(asyncio.TimeoutError):
                await b.wait_for_created("id", timeout=0.001)
        finally:
            a.close()
            b.close()


if __name__ == "__main__":
    unittest.main()
