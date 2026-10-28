"""Private-trace metadata audit fixtures; no real user messages or credentials."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.audit_brain_completion_metadata import (
    audit_records, iter_local_jsonl,
)

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "audit_brain_completion_metadata.py"
SECRET = "SENSITIVE_PRIVATE_TOKEN_MUST_NOT_LEAK"


def record(name: str, payload=None) -> dict:
    return {
        "kind": "ws_frame_content", "direction": "received",
        "payload": {
            "data": {"event": {
                "name": name,
                "payload": payload or {},
                "reply": SECRET,
                "version_event_data": {
                    "changes": [{
                        "field": "comment", "after": SECRET,
                    }],
                },
            }},
        },
    }


class AuditMetadataTests(unittest.TestCase):
    def test_only_allowlisted_counters_never_raw_names_text_or_ids(self):
        rows = [
            record("aiConversationStarted", {"ai_result_id": SECRET}),
            record("chatCommentCreated"),
            record("chatCommentUpdated"),
            record("aiResponseCompleted", {"status": "completed"}),
            record(SECRET, {"status": SECRET}),
            {"kind": "ws_frame_content", "direction": "sent",
             "payload": {"data": {"event": {"name": SECRET}}}},
            None,
            False,
        ]
        report = audit_records(rows)
        self.assertEqual(report["jsonl_records"], 8)
        self.assertEqual(report["inbound_websocket_frames"], 5)
        self.assertEqual(report["ai_conversation_started"], 1)
        self.assertEqual(report["chat_comment_created"], 1)
        self.assertEqual(report["chat_comment_updated"], 1)
        self.assertEqual(report["terminal_event_name_candidates"], 1)
        self.assertEqual(report["terminal_status_value_candidates"], 1)
        self.assertEqual(report["other_event_frames"], 1)
        self.assertEqual(report["malformed_jsonl_records"], 1)
        self.assertEqual(report["oversize_line_records"], 1)
        self.assertNotIn(SECRET, json.dumps(report))
        self.assertIn("not", report["interpretation"])

    def test_cli_jsonl_parser_no_raw_payload_in_output(self):
        with tempfile.TemporaryDirectory(prefix="completion-probe-") as temp:
            path = Path(temp) / "private-trace.jsonl"
            with path.open("wb") as file:
                for row in (
                    record("aiConversationStarted", {"secret": SECRET}),
                    record("chatCommentCreated"),
                ):
                    file.write(json.dumps(row).encode("utf-8") + b"\n")
                file.write(b"{invalid-json}\n")
            parsed = list(iter_local_jsonl(path))
            self.assertEqual(len(parsed), 3)
            r = subprocess.run(
                [sys.executable, str(CLI), str(path)],
                capture_output=True, text=True, timeout=15,
                encoding="utf-8", check=False, cwd=ROOT,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["jsonl_records"], 3)
            self.assertEqual(json.loads(r.stdout)["malformed_jsonl_records"], 1)
            self.assertNotIn(SECRET, r.stdout + r.stderr)
            self.assertNotIn(str(path), r.stdout + r.stderr)

    def test_missing_path_is_safe_nonzero(self):
        with tempfile.TemporaryDirectory(prefix="completion-probe-") as temp:
            path = Path(temp) / "missing.jsonl"
            r = subprocess.run(
                [sys.executable, str(CLI), str(path)],
                capture_output=True, text=True, timeout=15,
                encoding="utf-8", check=False,
            )
            self.assertNotEqual(r.returncode, 0)
            self.assertNotIn(str(path), r.stderr)

    def test_zero_final_candidates_is_not_claim_of_completion(self):
        result = audit_records([record("aiConversationStarted"), record("chatCommentCreated")])
        self.assertEqual(result["terminal_event_name_candidates"], 0)
        self.assertIn("zero count does not prove", result["interpretation"].lower())


if __name__ == "__main__":
    unittest.main()
