"""Unit tests for Phase 4 & Phase 5A Hardened Control Plane."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path


from guardian_agent.accounts import register_account, revoke_account
from guardian_agent.connectors import CanvaConnector, ConnectorNotConfigured, get_connector
from guardian_agent.core import GuardianError, initialize
from guardian_agent.execution import ExecutionLockManager, plan_execution
from guardian_agent.orchestration import (
    orchestrate_confirm,
    orchestrate_dispatch,
    orchestrate_show,
    orchestrate_start,
)
from guardian_agent.policy import (
    approve_action_request,
    consume_action_approval,
    request_action_approval,
)
from guardian_agent.security_url import validate_and_sanitize_url
from guardian_agent.vault import store_secret


class Phase5AHardeningTests(unittest.TestCase):

    def setUp(self):
        os.environ["GUARDIAN_VAULT_PASSPHRASE"] = "test-passphrase-123"
        self.tmp_dir = tempfile.mkdtemp()
        self.root = Path(self.tmp_dir) / "demo"
        self.brain = initialize(self.root, "Hardening Tests", "Phase 5A test suite")


    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_writable_task_without_approved_paths_blocks_confirmation(self):
        start = orchestrate_start(self.brain, "Implement user login form", limit=3)
        orch_id = start["orchestration_id"]
        show = orchestrate_show(self.brain, orch_id)
        self.assertEqual(show["status"], "draft")
        self.assertIn("Writable coding task requires explicit approved paths", show["errors"][0])

        with self.assertRaises(GuardianError):
            orchestrate_confirm(self.brain, orch_id, "Confirm login form")

    def test_writable_task_with_allowed_paths_confirms_successfully(self):
        start = orchestrate_start(
            self.brain,
            "Implement user login form",
            limit=3,
            approved_paths=["src/auth/", "tests/auth/"],
        )
        orch_id = start["orchestration_id"]
        orchestrate_confirm(self.brain, orch_id, "Confirm login form")
        orchestrate_dispatch(self.brain, orch_id)

        ex = plan_execution(self.brain, orch_id)
        self.assertEqual(ex["status"], "planned")
        self.assertIn("src/auth/", ex["stages"][0]["allowed_paths"])

    def test_path_traversal_and_absolute_paths_rejected_in_orchestration(self):
        with self.assertRaises(GuardianError):
            orchestrate_start(self.brain, "Implement auth", approved_paths=["/etc/passwd"])

        with self.assertRaises(GuardianError):
            orchestrate_start(self.brain, "Implement auth", approved_paths=["src/../../outside"])

        with self.assertRaises(GuardianError):
            orchestrate_start(self.brain, "Implement auth", approved_paths=[".env"])

    def test_execution_lock_file_path(self):
        lock_mgr = ExecutionLockManager(self.brain)
        expected_path = self.brain.directory / "executions.lock"
        self.assertEqual(lock_mgr.lock_file.resolve(), expected_path.resolve())

    def test_approval_target_mismatch_rejected(self):
        req = request_action_approval(
            self.brain,
            "browser_delete",
            "https://safe.example/item/1",
            "Delete test item",
        )
        approve_action_request(self.brain, req["id"])

        with self.assertRaises(GuardianError):
            consume_action_approval(
                self.brain,
                req["id"],
                "browser_delete",
                "https://different.example/item/999",
            )

    def test_approval_exact_canonical_target_consumed(self):
        req = request_action_approval(
            self.brain,
            "browser_delete",
            "https://safe.example/item/1",
            "Delete test item",
        )
        approve_action_request(self.brain, req["id"])

        consumed = consume_action_approval(
            self.brain,
            req["id"],
            "browser_delete",
            "https://safe.example/item/1",
        )
        self.assertEqual(consumed["status"], "consumed")

    def test_connector_not_configured_raised_for_mock(self):
        store_secret(self.brain, "CANVA_KEY", "secret-value")
        register_account(
            self.brain,
            "canva-test",
            "canva",
            "Test Canva Account",
            "vault://CANVA_KEY",
            ["canva.com"],
        )

        connector = get_connector("canva", "canva-test")
        auth = connector.authenticate(self.brain)
        self.assertTrue(auth["credential_available"])
        self.assertFalse(auth["remote_authenticated"])

        with self.assertRaises(ConnectorNotConfigured):
            connector.create_asset(self.brain, "Test Title", allow_mock=False)

    def test_export_asset_path_traversal_rejected(self):
        store_secret(self.brain, "CANVA_KEY", "secret-value")
        register_account(
            self.brain,
            "canva-test",
            "canva",
            "Test Canva Account",
            "vault://CANVA_KEY",
            ["canva.com"],
        )

        connector = CanvaConnector("canva-test")
        with self.assertRaises(GuardianError):
            connector.export_asset(self.brain, "../../escaped", "png", allow_mock=True)

        with self.assertRaises(GuardianError):
            connector.export_asset(self.brain, "valid_id", "exe", allow_mock=True)

    def test_export_asset_valid_containment(self):
        store_secret(self.brain, "CANVA_KEY", "secret-value")
        register_account(
            self.brain,
            "canva-test",
            "canva",
            "Test Canva Account",
            "vault://CANVA_KEY",
            ["canva.com"],
        )

        connector = CanvaConnector("canva-test")
        res = connector.export_asset(self.brain, "valid-asset-01", "png", allow_mock=True)
        art_path = Path(res["artifact_path"])
        self.assertTrue(art_path.is_file())
        self.assertTrue(art_path.name.endswith(".png"))


if __name__ == "__main__":
    unittest.main()
