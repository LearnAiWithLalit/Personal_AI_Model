"""Unit tests for Phase 4 Final Closure & Phase 5 Hardened Control Plane."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from guardian_agent.accounts import register_account, revoke_account
from guardian_agent.adapters import _get_project_context, generate_adapter_config
from guardian_agent.connectors import CanvaConnector, ConnectorNotConfigured, get_connector
from guardian_agent.core import GuardianError, initialize
from guardian_agent.execution import ExecutionLockManager, claim_execution_stage, plan_execution, record_execution_result
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
        self.assertIn("Writable task requires explicit approved paths", show["errors"][0])

        with self.assertRaises(GuardianError):
            orchestrate_confirm(self.brain, orch_id, "Confirm login form")

    def test_documentation_task_with_access_mode_write_requires_approved_paths(self):
        start = orchestrate_start(
            self.brain,
            "Update README documentation",
            limit=3,
            access_mode="write",
        )
        orch_id = start["orchestration_id"]
        with self.assertRaises(GuardianError):
            orchestrate_confirm(self.brain, orch_id, "Update documentation")

    def test_nested_protected_path_components_rejected_in_orchestration(self):
        with self.assertRaises(GuardianError):
            orchestrate_start(self.brain, "Implement auth", approved_paths=["src/.env"])

        with self.assertRaises(GuardianError):
            orchestrate_start(self.brain, "Implement auth", approved_paths=["sub/vault/keys.pem"])

        with self.assertRaises(GuardianError):
            orchestrate_start(self.brain, "Implement auth", approved_paths=["project/.agent/config"])

    def test_empty_allowed_paths_prohibits_file_writes_with_valid_claimed_lease(self):
        start = orchestrate_start(self.brain, "Research architecture", limit=2)
        orch_id = start["orchestration_id"]
        orchestrate_confirm(self.brain, orch_id, "Research architecture")
        orchestrate_dispatch(self.brain, orch_id)
        ex = plan_execution(self.brain, orch_id)
        stage_id = ex["stages"][0]["id"]
        claim = claim_execution_stage(self.brain, ex["id"], stage_id, lease_seconds=300)
        lease_id = claim["lease_id"]

        with self.assertRaises(GuardianError) as cm:
            record_execution_result(
                self.brain,
                ex["id"],
                stage_id,
                lease_id=lease_id,
                outcome="passed",
                evidence="Finished research",
                artifacts_changed=["src/written.py"],
            )
        self.assertIn("This stage has no writable paths", str(cm.exception))

    def test_adapter_empty_stage_allowed_paths_remains_empty(self):
        start = orchestrate_start(self.brain, "Research architecture", limit=2)
        orch_id = start["orchestration_id"]
        orchestrate_confirm(self.brain, orch_id, "Research architecture")
        orchestrate_dispatch(self.brain, orch_id)
        ex = plan_execution(self.brain, orch_id)

        self.assertEqual(ex["stages"][0]["allowed_paths"], [])

        # Check adapter project context with empty allowed_paths
        ctx = _get_project_context(self.brain, stage_allowed_paths=[])
        self.assertEqual(ctx["allowed_paths"], [])

    def test_unscoped_sensitive_approval_reservation_rejected(self):
        req = request_action_approval(
            self.brain,
            "browser_delete",
            "https://safe.example/item/1",
            "Delete item without scope",
            # Omitted user_id, account_id, connector_scope
        )
        approve_action_request(self.brain, req["id"])

        with self.assertRaises(GuardianError) as cm:
            reserve_action_approval(
                self.brain,
                req["id"],
                "browser_delete",
                "https://safe.example/item/1",
                user_id="u1",
                account_id="acc-01",
                connector_scope="canva",
            )
        self.assertIn("lacks or has mismatched mandatory", str(cm.exception))

    def test_reserved_approval_consumed_with_wrong_action_target_or_token_rejected(self):
        req = request_action_approval(
            self.brain,
            "browser_delete",
            "https://safe.example/item/1",
            "Delete item",
            user_id="u1",
            account_id="acc-01",
            connector_scope="canva",
        )
        approve_action_request(self.brain, req["id"])
        res = reserve_action_approval(
            self.brain,
            req["id"],
            "browser_delete",
            "https://safe.example/item/1",
            user_id="u1",
            account_id="acc-01",
            connector_scope="canva",
        )
        token = res["reservation_token"]
        self.assertTrue(token.startswith("tok-"))

        # Consumption without reservation token must be rejected
        with self.assertRaises(GuardianError) as cm1:
            consume_action_approval(
                self.brain,
                req["id"],
                "browser_delete",
                "https://safe.example/item/1",
                user_id="u1",
                account_id="acc-01",
                connector_scope="canva",
                reservation_token=None,
            )
        self.assertIn("requires a valid matching reservation token", str(cm1.exception))

        # Consumption with wrong action must be rejected
        with self.assertRaises(GuardianError) as cm2:
            consume_action_approval(
                self.brain,
                req["id"],
                "browser_publish",
                "https://safe.example/item/1",
                user_id="u1",
                account_id="acc-01",
                connector_scope="canva",
                reservation_token=token,
            )
        self.assertIn("action mismatch", str(cm2.exception))

        # Consumption with wrong target must be rejected
        with self.assertRaises(GuardianError) as cm3:
            consume_action_approval(
                self.brain,
                req["id"],
                "browser_delete",
                "https://safe.example/item/wrong",
                user_id="u1",
                account_id="acc-01",
                connector_scope="canva",
                reservation_token=token,
            )
        self.assertIn("target mismatch", str(cm3.exception))

        # Successful consumption with matching token and scope
        consumed = consume_action_approval(
            self.brain,
            req["id"],
            "browser_delete",
            "https://safe.example/item/1",
            user_id="u1",
            account_id="acc-01",
            connector_scope="canva",
            reservation_token=token,
        )
        self.assertEqual(consumed["status"], "consumed")

    def test_consumed_approval_cannot_be_reapproved(self):
        req = request_action_approval(
            self.brain,
            "browser_delete",
            "https://safe.example/item/1",
            "Delete item",
            user_id="u1",
            account_id="acc-01",
            connector_scope="canva",
        )
        approve_action_request(self.brain, req["id"])
        res = reserve_action_approval(
            self.brain,
            req["id"],
            "browser_delete",
            "https://safe.example/item/1",
            user_id="u1",
            account_id="acc-01",
            connector_scope="canva",
        )
        token = res["reservation_token"]
        consume_action_approval(
            self.brain,
            req["id"],
            "browser_delete",
            "https://safe.example/item/1",
            user_id="u1",
            account_id="acc-01",
            connector_scope="canva",
            reservation_token=token,
        )

        with self.assertRaises(GuardianError) as cm:
            approve_action_request(self.brain, req["id"])
        self.assertIn("not 'pending'", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
