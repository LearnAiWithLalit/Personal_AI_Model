"""Unit tests for Computer Operator Browser Controller (browser_operator.py)."""

import json
import tempfile
import unittest
from pathlib import Path

from guardian_agent.accounts import register_account
from guardian_agent.browser_operator import (
    cancel_takeover,
    check_playwright_available,
    execute_browser_action,
    get_takeover_status,
    inspect_web_page,
    pause_for_takeover,
    resume_takeover,
)
from guardian_agent.core import GuardianError, initialize


class BrowserOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Browser Demo", "Browser operator test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_playwright_availability_check(self) -> None:
        avail = check_playwright_available()
        self.assertIsInstance(avail, bool)

    def test_inspect_web_page_graceful_fallback(self) -> None:
        res = inspect_web_page(self.brain, url="https://example.invalid")
        self.assertIn("status", res)
        self.assertIn("method", res)
        self.assertTrue(res["status"] in {"success", "fallback_http", "failed"})

    def test_submit_requires_approval_before_browser_is_opened(self) -> None:
        with self.assertRaises(GuardianError):
            execute_browser_action(
                self.brain, url="https://example.invalid", action="submit", selector="button[type=submit]"
            )

    def test_manual_takeover_status_and_control_signals(self) -> None:
        register_account(
            self.brain,
            account_id="acc_tk1",
            service_name="canva",
            account_label="Takeover Account",
            vault_ref="vault:canva_key",
            allowed_domains=["canva.com"],
        )


        st1 = get_takeover_status(self.brain, "acc_tk1")
        self.assertEqual(st1["status"], "inactive")

        # Resume without active signal
        res_res = resume_takeover(self.brain, "acc_tk1")
        self.assertEqual(res_res["status"], "resumed")

        # Cancel without active signal
        can_res = cancel_takeover(self.brain, "acc_tk1")
        self.assertEqual(can_res["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
