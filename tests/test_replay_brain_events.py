"""Offline tests for replay command; no source trace/private credentials."""
import json
import unittest

from tools.replay_brain_events import replay


def frame(name, *, aid, cid, text=None):
    event = {"name": name}
    if name == "aiConversationStarted":
        event["payload"] = {"ai_result_id": aid, "conversation_id": cid}
    elif name == "chatCommentCreated":
        event["version_event_data"] = {
            "changes": [
                {"field": "ai_result_id", "after": aid},
                {"field": "conversation_id", "after": cid},
                {"field": "comment", "after": json.dumps([{"text": text}])},
            ]
        }
    return {"kind": "ws_frame_content", "payload": {"data": {"event": event}}}


class ReplayTests(unittest.TestCase):
    def test_replay_handles_interleaved_and_early_comment(self):
        records = [
            frame("chatCommentCreated", aid="opaque-one", cid="conv-1", text="first"),
            frame("aiConversationStarted", aid="opaque-two", cid="conv-2"),
            frame("aiConversationStarted", aid="opaque-one", cid="conv-1"),
            frame("chatCommentCreated", aid="opaque-two", cid="conv-2", text="second"),
        ]
        result = replay(records)
        self.assertEqual(result["correlation_counters"]["matched"], 2)
        self.assertEqual(result["processed_ws_frames"], 4)
        self.assertEqual(result["event_classification"]["reply_buffered"], 1)
        self.assertNotIn("opaque-one", str(result))
        self.assertNotIn("first", str(result))


if __name__ == "__main__":
    unittest.main()
