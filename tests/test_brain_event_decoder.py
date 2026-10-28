"""Fixture-only tests: no credentials, network or ClickUp session required."""
import json
import unittest

from tools.brain_event_decoder import parse_rich_text, reconstruct


def ws(t, name, **fields):
    event = {"name": name}
    event.update(fields)
    return {
        "timestamp_utc": f"2026-10-28T05:00:{t:02d}+00:00",
        "kind": "ws_frame_content",
        "payload": {"data": {"event": event}},
    }


def create(t, comment, *, result_id=None, conversation_id=None):
    changes = [{"field": "comment", "after": json.dumps(
        [{"text": comment, "attributes": {}}], ensure_ascii=False
    )}]
    if result_id is not None:
        changes.append({"field": "ai_result_id", "after": result_id})
    if conversation_id is not None:
        changes.append({"field": "conversation_id", "after": conversation_id})
    return ws(t, "chatCommentCreated", version_event_data={"changes": changes})


class BrainDecoderTests(unittest.TestCase):
    def test_rich_text_decoding_and_rejection(self):
        self.assertEqual(parse_rich_text(
            '[{"text":"Hello "},{"text":"world","attributes":{}}]'
        ), "Hello world")
        self.assertEqual(parse_rich_text("[]"), "")
        self.assertIsNone(parse_rich_text("not json"))
        self.assertIsNone(parse_rich_text('{"text":"wrong shape"}'))
        self.assertIsNone(parse_rich_text('[{"invalid":"not supported"}]'))

    def test_reconstruct_started_user_and_assistant_comments(self):
        records = [
            ws(1, "aiConversationStarted",
               payload={"ai_result_id": "SECRET_AI_RESULT", "conversation_id": "SECRET_CONV"}),
            create(2, "ping"),
            create(4, "OK", result_id="SECRET_AI_RESULT", conversation_id="SECRET_CONV"),
            ws(5, "chatCommentEdited", version_event_data={"changes": []}),
        ]
        replies, report = reconstruct(records)
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0].text, "OK")
        self.assertEqual(replies[0].elapsed_seconds, 3)
        self.assertEqual(report["ai_started_count"], 1)
        self.assertEqual(report["ai_reply_created_count"], 1)
        self.assertEqual(report["user_comment_created_count"], 1)
        self.assertEqual(report["ai_reply_matched_count"], 1)
        self.assertEqual(report["conversation_mismatch_count"], 0)
        self.assertEqual(report["reply_text_lengths"], [2])
        self.assertNotIn("SECRET_AI_RESULT", str(report))
        self.assertNotIn("SECRET_CONV", str(report))
        self.assertNotIn("ping", str(report))
        self.assertNotIn("OK", str(report))

    def test_conversation_mismatch_and_missing_start(self):
        records = [
            ws(1, "aiConversationStarted",
               payload={"ai_result_id": "a", "conversation_id": "c1"}),
            create(4, "one", result_id="a", conversation_id="c2"),
            create(5, "two", result_id="unknown", conversation_id="c3"),
        ]
        replies, report = reconstruct(records)
        self.assertEqual(len(replies), 2)
        self.assertEqual(report["ai_reply_matched_count"], 1)
        self.assertEqual(report["conversation_mismatch_count"], 1)
        self.assertIsNone(replies[1].elapsed_seconds)


if __name__ == "__main__":
    unittest.main()
