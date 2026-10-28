"""Offline tests for local remembered ClickUp Brain start route.

Never reads a real browser profile, auth cookie or workspace IDs from user.
"""
from pathlib import Path
import tempfile
import unittest

from tools.brain_start_url import (
    DEFAULT_URL,
    choose_start_url,
    load_start_url,
    normalize_brain_start_url,
    remember_start_url,
)


class BrainStartRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="brain-route-fixture-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / ".local" / "brain-start-url.txt"

    def test_no_saved_route_defaults_to_clickup_home(self):
        self.assertEqual(choose_start_url(None, self.path), DEFAULT_URL)

    def test_remember_brain_strips_existing_chat_and_fragment(self):
        original = (
            "https://app.clickup.com/123456789/ai/brain"
            "?conversationId=private-opaque-should-not-persist#sensitive"
        )
        clean = remember_start_url(original, self.path)
        self.assertEqual(clean, "https://app.clickup.com/123456789/ai/brain")
        self.assertEqual(load_start_url(self.path), clean)
        self.assertEqual(choose_start_url(None, self.path), clean)
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn("conversationId", raw)
        self.assertNotIn("private-opaque", raw)
        self.assertNotIn("sensitive", raw)

    def test_valid_saved_route_reused_and_explicit_override_wins(self):
        remember_start_url(
            "https://app.clickup.com/444/ai/brain?conversationId=old",
            self.path,
        )
        explicit = "https://app.clickup.com/555/ai/brain?conversationId=current"
        self.assertEqual(choose_start_url(explicit, self.path), explicit)
        self.assertEqual(
            load_start_url(self.path), "https://app.clickup.com/444/ai/brain"
        )

    def test_two_verified_workspaces_overwrite_only_workspace_route(self):
        remember_start_url("https://app.clickup.com/111/ai/brain", self.path)
        remember_start_url("https://app.clickup.com/222/ai/brain", self.path)
        self.assertEqual(
            load_start_url(self.path), "https://app.clickup.com/222/ai/brain"
        )

    def test_rejects_non_brain_route_and_host_spoofing(self):
        bad = [
            "https://app.clickup.com/",
            "https://app.clickup.com/111/v/o/s/other",
            "https://app.clickup.com/111/ai/brain/extra",
            "https://app.clickup.com.evil.invalid/111/ai/brain",
            "http://app.clickup.com/111/ai/brain",
            "https://evil@app.clickup.com/111/ai/brain",
            "https://app.clickup.com:444/111/ai/brain",
            "https://app.clickup.com/../ai/brain",
            "javascript:alert(1)",
        ]
        for value in bad:
            with self.subTest(url=value), self.assertRaises(ValueError):
                normalize_brain_start_url(value)
        self.assertFalse(self.path.exists())

    def test_rejects_tampered_local_route_not_navigate_away(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            "https://app.clickup.com.evil.invalid/123/ai/brain\n",
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            choose_start_url(None, self.path)

    def test_unicode_and_empty_route_handling(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("  \n", encoding="utf-8")
        self.assertEqual(load_start_url(self.path), None)
        self.assertEqual(choose_start_url(None, self.path), DEFAULT_URL)
        with self.assertRaises(ValueError):
            normalize_brain_start_url("https://app.clickup.com/workspace/ai/brain")


if __name__ == "__main__":
    unittest.main()
