"""Offline checks for safe Brain UI selector inspection; never access user account."""
from pathlib import Path
import subprocess
import sys
import unittest

from tools.inspect_brain_ui import PROBE_JS, select_brain_page, valid_clickup_url


class FakePage:
    def __init__(self, url: str, *, closed: bool = False):
        self.url = url
        self._closed = closed

    def is_closed(self):
        return self._closed


class UiInspectorTests(unittest.TestCase):
    def test_scope_only_authorized_clickup_application(self):
        self.assertTrue(valid_clickup_url("https://app.clickup.com/"))
        self.assertTrue(valid_clickup_url("https://app.clickup.com/workspace/ai/brain"))
        self.assertFalse(valid_clickup_url("http://app.clickup.com/"))
        self.assertFalse(valid_clickup_url("https://app.clickup.com.evil.invalid/"))
        self.assertFalse(valid_clickup_url("https://other.clickup.com/"))

    def test_prefers_brain_tab_even_if_initial_tab_is_dashboard(self):
        pages = [
            FakePage("https://app.clickup.com/dashboard"),
            FakePage("https://app.clickup.com/workspace/ai/brain"),
        ]
        self.assertIs(select_brain_page(pages), pages[1])

    def test_multiple_non_brain_tabs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Multiple ClickUp tabs"):
            select_brain_page([
                FakePage("https://app.clickup.com/dashboard"),
                FakePage("https://app.clickup.com/list"),
            ])
        with self.assertRaisesRegex(ValueError, "No ClickUp tab"):
            select_brain_page([FakePage("https://example.com/")])

    def test_closed_tab_is_skipped(self):
        pages = [
            FakePage("https://app.clickup.com/ai/brain", closed=True),
            FakePage("https://app.clickup.com/ai/brain"),
        ]
        self.assertIs(select_brain_page(pages), pages[1])

    def test_dom_probe_does_not_read_message_bodies_or_input_values(self):
        for forbidden in (".innerText", ".textContent", ".innerHTML",
                          ".outerHTML", ".value", "localStorage",
                          "document.cookie", "fetch(", "XMLHttpRequest"):
            self.assertNotIn(forbidden, PROBE_JS)
        self.assertIn("querySelectorAll", PROBE_JS)
        self.assertIn("aria-label", PROBE_JS)
        self.assertIn("data-testid", PROBE_JS)

    def test_cli_help_windows_direct_module_mode(self):
        root = Path(__file__).resolve().parents[1]
        commands = [
            [sys.executable, str(root / "tools" / "inspect_brain_ui.py"), "--help"],
            [sys.executable, "-m", "tools.inspect_brain_ui", "--help"],
        ]
        for command in commands:
            with self.subTest(command=command):
                p = subprocess.run(command, cwd=root, capture_output=True,
                                   text=True, timeout=15, check=False)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIn("--profile-dir", p.stdout)


if __name__ == "__main__":
    unittest.main()
