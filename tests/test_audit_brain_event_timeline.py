"""Synthetic-only timeline/shape tests. No ClickUp traffic or real private trace."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.audit_brain_event_timeline import audit_timeline

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "tools" / "audit_brain_event_timeline.py"
SECRET = "SENSITIVE_PRIVATE_MESSAGE_OR_AUTH_TOKEN_NEVER_PRINT"
T0 = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)


def frame(seconds: int, name: str, *, aid: str | None = None,
          changes=None, status=None, stamp=True):
    payload = {"secret": SECRET}
    if aid is not None and name == "aiConversationStarted":
        payload["ai_result_id"] = aid
    if status is not None:
        payload["status"] = status
    if changes is None:
        changes = []
    if aid is not None and name == "chatCommentCreated":
        changes = changes + [{"field": "ai_result_id", "after": aid}]
    return {
        "kind": "ws_frame_content",
        "direction": "received",
        "timestamp_utc": (T0 + timedelta(seconds=seconds)).isoformat()
        if stamp else "SENSITIVE_INVALID_TIMESTAMP",
        "payload": {"data": {
            "event": {
                "name": name, "payload": payload,
                "version_event_data": {"changes": changes},
                "private_content": SECRET,
            },
        }},
    }


class EventTimelineTests(unittest.TestCase):
    def test_edit_timing_buckets_and_noncausal_proximity(self):
        events = [
            frame(0, "aiConversationStarted", aid="private-a"),
            frame(1, "chatCommentEdited", changes=[]),
            frame(2, "chatCommentCreated", aid="private-a"),
            frame(3, "chatCommentEdited"),
            frame(7, "chatCommentEdited"),
            frame(15, "chatCommentEdited"),
            frame(45, "chatCommentEdited"),
            frame(50, "aiConversationStarted", aid="private-b"),
            frame(51, "chatCommentEdited"),
            frame(56, "chatCommentCreated", aid="private-b"),
        ]
        result = audit_timeline(events)
        self.assertEqual(result["ai_start_events"], 2)
        self.assertEqual(result["ai_reply_created_events"], 2)
        self.assertEqual(result["chat_comment_edited_events"], 6)
        self.assertEqual(result["edited_while_any_ai_start_pending"], 2)
        self.assertEqual(result["edited_before_first_ai_reply"], 1)
        self.assertEqual(result["edited_after_prior_ai_reply"], 5)
        self.assertEqual(result["edited_within_2s_after_prior_ai_reply"], 1)
        self.assertEqual(result["edited_2_to_10s_after_prior_ai_reply"], 1)
        self.assertEqual(result["edited_10_to_30s_after_prior_ai_reply"], 1)
        # 51s edit occurs during the new B generation, but only nearest
        # previous reply A has an observed timestamp: never infer the edit
        # belongs to either message.
        self.assertEqual(result["edited_more_than_30s_after_prior_ai_reply"], 2)
        self.assertEqual(result["matched_ai_start_reply_timestamps"], 2)
        self.assertEqual(result["matched_ai_latency_1_to_5s"], 1)
        self.assertEqual(result["matched_ai_latency_5_to_30s"], 1)
        self.assertIn("cannot be attributed", result["interpretation"])
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn("private-a", json.dumps(result))

    def test_explicit_edit_shape_and_event_buckets(self):
        events = [
            frame(1, "chatCommentEdited",
                  changes=[{"field": "comment", "after": SECRET}],
                  status="working"),
            frame(2, "chatTypingStateChanged"),
            frame(3, "chatConversationChanged"),
            frame(4, "chatCommentSomethingChanged"),
            frame(5, "chatStatusChanged"),
            frame(6, "chatWhatever"),
            frame(7, "chatStreamingProgress"),
            frame(8, "unrecognizedCompletionPrivate", status="done"),
            frame(9, "aiConversationStarted", aid="private-x", stamp=False),
            frame(10, "chatCommentCreated", aid="private-x"),
            frame(11, "chatCommentEdited", stamp=False),
        ]
        result = audit_timeline(events)
        self.assertEqual(result["edited_with_payload_dict"], 2)
        self.assertEqual(result["edited_with_version_data_dict"], 2)
        self.assertEqual(result["edited_with_changes_array"], 2)
        self.assertEqual(result["edited_with_nonempty_changes"], 1)
        self.assertEqual(result["edited_with_payload_status_key"], 1)
        self.assertEqual(result["edited_with_valid_timestamp"], 1)
        self.assertEqual(
            result["edited_without_comparable_prior_ai_reply_timestamp"], 2
        )
        self.assertEqual(result["other_chat_events"], 6)
        self.assertEqual(result["other_chat_typing_hint"], 2)
        self.assertEqual(result["other_chat_conversation_hint"], 1)
        self.assertEqual(result["other_chat_comment_hint"], 1)
        self.assertEqual(result["other_chat_status_or_state_hint"], 1)
        self.assertEqual(result["other_chat_other_hint"], 1)
        self.assertEqual(result["ai_created_without_matching_start_timestamp"], 1)
        self.assertNotIn("unrecognizedCompletionPrivate", json.dumps(result))

    def test_cli_safe_report_and_absent_trace(self):
        with tempfile.TemporaryDirectory(prefix="timeline-private-") as temp:
            source = Path(temp) / "PRIVATE_WORKSPACE_TRACE.jsonl"
            with source.open("wb") as handle:
                for event in [
                    frame(0, "aiConversationStarted", aid=SECRET),
                    frame(1, "chatCommentCreated", aid=SECRET),
                    frame(2, "chatCommentEdited", status=SECRET),
                ]:
                    handle.write(json.dumps(event).encode("utf-8") + b"\n")
                handle.write(b"{malformed}\n")
            args = [sys.executable, str(CLI), str(source)]
            run = subprocess.run(
                args, cwd=REPO, capture_output=True, text=True, timeout=20,
                encoding="utf-8", check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            safe = json.loads(run.stdout)
            self.assertEqual(safe["ai_start_events"], 1)
            self.assertEqual(safe["ai_reply_created_events"], 1)
            self.assertEqual(safe["chat_comment_edited_events"], 1)
            self.assertNotIn(SECRET, run.stdout + run.stderr)
            self.assertNotIn(str(source), run.stdout + run.stderr)

            absent = subprocess.run(
                [sys.executable, str(CLI), str(source) + ".no"],
                cwd=REPO, capture_output=True, text=True, timeout=20,
                encoding="utf-8", check=False,
            )
            self.assertNotEqual(absent.returncode, 0)
            self.assertNotIn(str(source), absent.stdout + absent.stderr)

    def test_unordered_timestamps_not_claimed_success(self):
        result = audit_timeline([
            frame(10, "aiConversationStarted", aid="A"),
            frame(5, "chatCommentCreated", aid="A"),
        ])
        self.assertEqual(result["matched_ai_start_reply_timestamps"], 1)
        self.assertEqual(result["matched_ai_negative_or_unordered_timestamps"], 1)
        self.assertEqual(result["matched_ai_latency_under_1s"], 0)


if __name__ == "__main__":
    unittest.main()
