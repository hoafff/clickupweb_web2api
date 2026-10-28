"""CLI regression tests for the Windows ModuleNotFoundError: tools.

The test uses fabricated WebSocket events only, never a real private trace.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "replay_brain_events.py"


def _fixture(name: str, *, ai_id: str, conversation: str, text: str = "") -> dict:
    event: dict = {"name": name}
    if name == "aiConversationStarted":
        event["payload"] = {
            "ai_result_id": ai_id,
            "conversation_id": conversation,
        }
    elif name == "chatCommentCreated":
        event["version_event_data"] = {
            "changes": [
                {"field": "ai_result_id", "after": ai_id},
                {"field": "conversation_id", "after": conversation},
                {"field": "comment", "after": json.dumps([{"text": text}])},
            ]
        }
    return {"kind": "ws_frame_content", "payload": {"data": {"event": event}}}


class ReplayCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="brain-cli-smoke-")
        self.addCleanup(self.tmp.cleanup)
        self.data_path = Path(self.tmp.name) / "synthetic.jsonl"
        records = [
            _fixture("aiConversationStarted", ai_id="test-result-A", conversation="test-thread-A"),
            _fixture("aiConversationStarted", ai_id="test-result-B", conversation="test-thread-B"),
            _fixture("chatCommentCreated", ai_id="test-result-A",
                     conversation="test-thread-A", text="first"),
            _fixture("chatCommentCreated", ai_id="test-result-B",
                     conversation="test-thread-B", text="second"),
        ]
        self.data_path.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )

    def _run(self, *launch_args: str, expected: int = 2) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *launch_args, str(self.data_path), "--expected", str(expected)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def test_direct_script_with_real_cli_arguments(self) -> None:
        result = self._run(str(SCRIPT))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["correlation_counters"]["matched"], 2)
        self.assertNotIn("test-thread-A", result.stdout)
        self.assertNotIn("first", result.stdout)

    def test_module_invocation_with_real_cli_arguments(self) -> None:
        result = self._run("-m", "tools.replay_brain_events")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["correlation_counters"]["matched"], 2)

    def test_mismatched_expected_count_is_nonzero(self) -> None:
        result = self._run(str(SCRIPT), expected=3)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Expected 3 matches but got 2", result.stdout)


if __name__ == "__main__":
    unittest.main()
