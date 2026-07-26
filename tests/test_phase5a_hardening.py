"""Unit tests for Phase 4 & Phase 5A Hardened Control Plane."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from guardian_agent.accounts import register_account, revoke_account
from guardian_agent.connectors import CanvaConnector, ConnectorNotConfigured, get_connector

from guardian_agent.core import GuardianError, initialize
from guardian_agent.execution import ExecutionLockManager, plan_execution, record_execution_result
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
    reserve_action_approval,
)
from guardian_agent.security_url import fetch_url_content_safe, validate_and_sanitize_url


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

    def test_nested_protected_path_components_rejected_in_orchestration(self):
        with self.assertRaises(GuardianError):
            orchestrate_start(self.brain, "Implement auth", approved_paths=["src/.env"])

        with self.assertRaises(GuardianError):
            orchestrate_start(self.brain, "Implement auth", approved_paths=["sub/vault/keys.pem"])

        with self.assertRaises(GuardianError):
            orchestrate_start(self.brain, "Implement auth", approved_paths=["project/.agent/config"])

    def test_empty_allowed_paths_prohibits_file_writes_in_execution(self):
        start = orchestrate_start(self.brain, "Research architecture", limit=2)
        orch_id = start["orchestration_id"]
        orchestrate_confirm(self.brain, orch_id, "Research architecture")
        orchestrate_dispatch(self.brain, orch_id)
        ex = plan_execution(self.brain, orch_id)
        stage_id = ex["stages"][0]["id"]

        with self.assertRaises(GuardianError):
            record_execution_result(
                self.brain,
                ex["id"],
                stage_id,
                lease_id="dummy",
                outcome="passed",
                evidence="Finished research",
                artifacts_changed=["src/written.py"],
            )

    def test_execution_lock_file_path(self):
        lock_mgr = ExecutionLockManager(self.brain)
        expected_path = self.brain.directory / "executions.lock"
        self.assertEqual(lock_mgr.lock_file.resolve(), expected_path.resolve())

    def test_two_stage_pre_action_approval_reservation(self):
        req = request_action_approval(
            self.brain,
            "browser_delete",
            "https://safe.example/item/1",
            "Delete test item",
            account_id="acc-01",
            connector_scope="canva",
        )
        approve_action_request(self.brain, req["id"])

        # Stage 1: Reservation
        reserved = reserve_action_approval(
            self.brain,
            req["id"],
            "browser_delete",
            "https://safe.example/item/1",
            account_id="acc-01",
            connector_scope="canva",
        )
        self.assertEqual(reserved["status"], "reserved")

        # Stage 2: Completion
        consumed = consume_action_approval(
            self.brain,
            req["id"],
            "browser_delete",
            "https://safe.example/item/1",
            account_id="acc-01",
            connector_scope="canva",
        )
        self.assertEqual(consumed["status"], "consumed")

    def test_sensitive_action_missing_scope_rejected(self):
        req = request_action_approval(
            self.brain,
            "browser_delete",
            "https://safe.example/item/1",
            "Delete test item",
            # missing account_id and connector_scope on request
        )
        approve_action_request(self.brain, req["id"])

        with self.assertRaises(GuardianError):
            reserve_action_approval(
                self.brain,
                req["id"],
                "browser_delete",
                "https://safe.example/item/1",
                account_id="acc-01",
            )

    def test_connector_authentication_status_wording(self):
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
        self.assertFalse(auth["authenticated"])
        self.assertEqual(auth["status"], "authentication_required")
        self.assertFalse(auth["remote_authenticated"])


if __name__ == "__main__":
    unittest.main()
