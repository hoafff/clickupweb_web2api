"""Synthetic-only v2 WS audit tests: no ClickUp account, browser or network.

Recreates the user's 602/203/8/16/152 counts with PRIVATE FAKE identifiers,
then demonstrates what the first metadata report could not distinguish.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.audit_brain_completion_deep import audit_deep

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "audit_brain_completion_deep.py"
SECRET = "PRIVATE_SYNTHETIC_REPLY_OR_TOKEN_NEVER_PRINT"


def frame(name: str, *, direction="received", payload=None, changes=None):
    return {
        "kind": "ws_frame_content",
        "direction": direction,
        "timestamp_utc": "2026-10-28T12:00:00+00:00",
        "payload": {
            "data": {"event": {
                "name": name,
                "payload": payload or {},
                "version_event_data": {"changes": changes or []},
                "secret": SECRET,
            }},
        },
    }


def edit(field, value):
    return {"field": field, "after": value}


class CompletionDeepAuditTests(unittest.TestCase):
    def test_recreates_user_aggregates_and_distinguishes_ai_vs_non_ai(self):
        rows = []
        for i in range(8):
            rid = f"secret-ai-{i}"
            rows.extend([
                frame("aiConversationStarted", payload={"ai_result_id": rid}),
                frame("chatCommentCreated", changes=[
                    edit("comment", SECRET),
                    edit("ai_result_id", rid),
                ]),
                frame("chatCommentCreated", changes=[edit("comment", SECRET)]),
            ])
        rows.extend(frame("workspaceChanged") for _ in range(152))
        rows.extend({
            "kind": "ws_frame_content", "direction": "received",
            "payload": {"data": {"other": SECRET}},
        } for _ in range(27))
        rows.extend({"kind": "http_response", "payload": SECRET} for _ in range(399))
        self.assertEqual(len(rows), 602)

        report = audit_deep(rows)
        self.assertEqual(report["jsonl_records"], 602)
        self.assertEqual(report["websocket_inbound_frames"], 203)
        self.assertEqual(report["non_event_inbound_frames"], 27)
        self.assertEqual(report["ai_conversation_started_events"], 8)
        self.assertEqual(report["chat_comment_created_events"], 16)
        self.assertEqual(report["comment_created_with_ai_result_id"], 8)
        self.assertEqual(report["comment_created_without_ai_result_id"], 8)
        self.assertEqual(report["matching_start_created_id_pairs"], 8)
        self.assertEqual(report["other_uncategorized_events"], 152)
        self.assertEqual(report["known_terminal_named_events"], 0)
        self.assertNotIn(SECRET, json.dumps(report))
        self.assertNotIn("workspaceChanged", json.dumps(report))
        self.assertNotIn("secret-ai-", json.dumps(report))
        self.assertNotIn("comment", report["interpretation"].split("NOT")[0])

    def test_edited_event_and_unknown_completion_hint_not_assumed_final(self):
        rows = [
            frame("chatCommentEdited", changes=[edit("comment", SECRET)]),
            frame("chatCommentEdited", changes=[
                edit("ai_result_id", SECRET),
            ]),
            frame("chatCommentUpdated"),
            frame("resultEnded", payload={"status": "completed"}),
            frame("aiResponseCompleted"),
            frame("aiPong", payload={"status": "pending"}),
            frame("chatTypingChanged", changes=[edit("status", "done")]),
            frame("messageStreamFinished", direction="sent"),
        ]
        output = audit_deep(rows)
        self.assertEqual(output["chat_comment_edited_events"], 2)
        self.assertEqual(output["comment_edited_with_comment_change"], 1)
        self.assertEqual(output["comment_edited_with_ai_result_id"], 1)
        self.assertEqual(output["chat_comment_updated_events"], 1)
        self.assertEqual(output["unknown_named_events_with_terminal_hint"], 1)
        self.assertEqual(output["known_terminal_named_events"], 1)
        self.assertEqual(output["terminal_status_in_event_or_payload"], 1)
        self.assertEqual(output["terminal_status_in_version_changes"], 1)
        self.assertEqual(output["other_ai_prefixed_events"], 1)
        self.assertEqual(output["other_chat_prefixed_events"], 1)
        self.assertEqual(output["other_response_or_generation_prefixed_events"], 1)
        self.assertEqual(output["websocket_inbound_frames"], 7)
        self.assertNotIn(SECRET, json.dumps(output))

    def test_in_memory_matching_includes_comment_before_start(self):
        rows = [
            frame("chatCommentCreated", changes=[edit("ai_result_id", "x")]),
            frame("aiConversationStarted", payload={"ai_result_id": "x"}),
            frame("aiConversationStarted", payload={"ai_result_id": "y"}),
            frame("chatCommentCreated", changes=[edit("ai_result_id", "z")]),
            frame("chatCommentCreated", changes=[edit("ai_result_id", "z")]),
        ]
        report = audit_deep(rows)
        self.assertEqual(report["unique_ai_started_ids"], 2)
        self.assertEqual(report["unique_ai_created_comment_ids"], 2)
        self.assertEqual(report["matching_start_created_id_pairs"], 1)
        self.assertEqual(report["started_ai_ids_without_created"], 1)
        self.assertEqual(report["created_ai_ids_not_in_starts"], 1)
        self.assertEqual(report["comment_created_with_ai_result_id"], 3)

    def test_cli_prints_only_fixed_fields_and_does_not_leak_secret(self):
        with tempfile.TemporaryDirectory(prefix="private-ws-test-") as folder:
            path = Path(folder) / "private-SECRET.jsonl"
            with path.open("wb") as file:
                file.write(json.dumps(frame(SECRET, payload={
                    "ai_result_id": SECRET, "status": SECRET,
                })).encode("utf-8") + b"\n")
                file.write(b"{invalid-json}\n")
            result = subprocess.run(
                [sys.executable, str(CLI), str(path)],
                cwd=ROOT, capture_output=True, text=True,
                encoding="utf-8", timeout=20, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            parsed = json.loads(result.stdout)
            self.assertEqual(parsed["jsonl_records"], 2)
            self.assertEqual(parsed["invalid_jsonl_records"], 1)
            self.assertEqual(parsed["other_uncategorized_events"], 1)
            self.assertNotIn(SECRET, result.stdout + result.stderr)
            self.assertNotIn(str(path), result.stdout + result.stderr)

    def test_missing_file_does_not_echo_private_filename(self):
        with tempfile.TemporaryDirectory(prefix="private-ws-test-") as folder:
            target = Path(folder) / "very-private-secret.jsonl"
            result = subprocess.run(
                [sys.executable, str(CLI), str(target)],
                capture_output=True, text=True, timeout=15, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(str(target), result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
