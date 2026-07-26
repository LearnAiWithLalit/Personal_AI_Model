"""Unit tests for Phase 5 Connectors (connectors.py)."""

import os
import tempfile
import time
import unittest
from pathlib import Path

from guardian_agent.accounts import register_account
from guardian_agent.connectors import (
    IdempotencyLedger,
    complete_connector_operation,
    fail_connector_operation,
    get_connector,
    reconcile_connector_outcome,
    reserve_connector_operation,
)
from guardian_agent.core import GuardianError, initialize


class TestConnectors(unittest.TestCase):
    def test_canva_connector_lifecycle_with_vault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Connector Test", "Phase 5 test")
            register_account(
                brain,
                account_id="canva1",
                service_name="canva",
                account_label="Canva Test",
                vault_ref="vault:canva_key",
                allowed_domains=["canva.com"],
            )

            conn = get_connector("canva", "canva1")

            # Without vault secret, auth must fail and return authentication_required
            auth = conn.authenticate(brain)
            self.assertFalse(auth["authenticated"])
            self.assertFalse(auth["credential_available"])
            self.assertFalse(auth["remote_authenticated"])
            self.assertEqual(auth["status"], "authentication_required")
            self.assertNotIn("vault_ref", auth)

            with self.assertRaises(GuardianError):
                conn.create_asset(brain, title="Header Graphic", allow_mock=True)

            # Set vault secret via environment fallback
            os.environ["CANVA_KEY"] = "secret_api_token_123"
            try:
                auth = conn.authenticate(brain)
                self.assertTrue(auth["credential_available"])
                self.assertFalse(auth["authenticated"])
                self.assertFalse(auth["remote_authenticated"])
                self.assertEqual(auth["status"], "credential_available")
                self.assertNotIn("secret_api_token_123", str(auth))

                # First creation
                created1 = conn.create_asset(brain, title="Header Graphic", allow_mock=True)
                self.assertEqual(created1["status"], "created")

                # Duplicate creation call must return identical cached receipt (durable idempotency)
                created2 = conn.create_asset(brain, title="Header Graphic", allow_mock=True)
                self.assertEqual(created1["asset_id"], created2["asset_id"])

                exported = conn.export_asset(brain, created1["asset_id"], export_format="png", allow_mock=True)
                self.assertTrue(Path(exported["artifact_path"]).is_file())
            finally:
                os.environ.pop("CANVA_KEY", None)

    def test_session_revocation_wipes_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Connector Test", "Phase 5 test")
            register_account(
                brain,
                account_id="canva2",
                service_name="canva",
                account_label="Canva Test 2",
                vault_ref="vault:canva_key2",
                allowed_domains=["canva.com"],
            )
            os.environ["CANVA_KEY2"] = "token2"
            try:
                conn = get_connector("canva", "canva2")
                self.assertTrue(conn.authenticate(brain)["credential_available"])

                # Revoke session
                res = conn.revoke_session(brain)
                self.assertTrue(res["revoked"])

                with self.assertRaises(GuardianError):
                    conn.authenticate(brain)
            finally:
                os.environ.pop("CANVA_KEY2", None)

    def test_idempotency_owner_token_completion_enforcement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Idempotency Test", "Phase 5 test")
            res = reserve_connector_operation(brain, "canva", "create_asset", "idem-key-100", ttl_seconds=300)
            self.assertFalse(res["already_completed"])
            token = res["owner_token"]
            self.assertTrue(token.startswith("otok-"))

            # Completion with wrong owner token must be rejected
            with self.assertRaises(GuardianError) as cm1:
                complete_connector_operation(
                    brain, "canva", "create_asset", "idem-key-100", {"status": "ok"}, owner_token="wrong_token"
                )
            self.assertIn("owner token mismatch", str(cm1.exception))

            # Completion without owner token must be rejected
            with self.assertRaises(GuardianError) as cm2:
                complete_connector_operation(
                    brain, "canva", "create_asset", "idem-key-100", {"status": "ok"}, owner_token=""
                )
            self.assertIn("owner_token is required", str(cm2.exception))

            # Completion with valid owner token must succeed
            complete_connector_operation(
                brain, "canva", "create_asset", "idem-key-100", {"status": "ok", "asset_id": "a-100"}, owner_token=token
            )

            # Re-completing or overwriting an already completed operation must be rejected
            with self.assertRaises(GuardianError) as cm3:
                complete_connector_operation(
                    brain, "canva", "create_asset", "idem-key-100", {"status": "overwritten"}, owner_token=token
                )
            self.assertIn("immutable and cannot be overwritten", str(cm3.exception))

            # Re-reserving completed operation returns receipt
            res2 = reserve_connector_operation(brain, "canva", "create_asset", "idem-key-100")
            self.assertTrue(res2["already_completed"])
            self.assertEqual(res2["receipt"]["asset_id"], "a-100")

    def test_mark_unknown_requires_matching_owner_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Idempotency Test", "Phase 5 test")
            res = reserve_connector_operation(brain, "canva", "create_asset", "idem-key-150")
            token = res["owner_token"]

            # Marking unknown without token must be rejected
            with self.assertRaises(GuardianError) as cm1:
                fail_connector_operation(brain, "canva", "create_asset", "idem-key-150", "Error reason", owner_token=None)
            self.assertIn("owner_token is required", str(cm1.exception))

            # Marking unknown with wrong token must be rejected
            with self.assertRaises(GuardianError) as cm2:
                fail_connector_operation(brain, "canva", "create_asset", "idem-key-150", "Error reason", owner_token="wrong_tok")
            self.assertIn("owner token mismatch", str(cm2.exception))

            # Marking unknown with matching token succeeds
            fail_connector_operation(brain, "canva", "create_asset", "idem-key-150", "Error reason", owner_token=token)

    def test_live_reserved_operation_cannot_be_reconciled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Idempotency Test", "Phase 5 test")
            res = reserve_connector_operation(brain, "canva", "create_asset", "idem-key-180", ttl_seconds=300)
            self.assertTrue(res["owner_token"].startswith("otok-"))

            # Reconciling a live reserved operation must be rejected
            with self.assertRaises(GuardianError) as cm:
                reconcile_connector_outcome(
                    brain, "canva", "create_asset", "idem-key-180", resolution="cancelled", resolution_reason="Cancel live"
                )
            self.assertIn("live reserved operation", str(cm.exception))

    def test_idempotency_stale_ttl_expiration_transitions_to_unknown_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Idempotency Test", "Phase 5 test")
            comp_key = "canva:create_asset:idem-key-200"

            # Manually inject a stale reservation entry with timestamp in the past
            ledger = IdempotencyLedger.load(brain)
            ledger[comp_key] = {
                "status": "reserved",
                "payload_hash": "hash123",
                "owner_token": "otok-old",
                "reserved_at": "2026-01-01 00:00 UTC",
                "reserved_timestamp": time.time() - 400,  # Expired (400s > 300s TTL)
            }
            IdempotencyLedger._save_under_lock(brain, ledger)

            # Attempting to reserve an expired stale operation must transition to unknown_outcome and fail closed
            with self.assertRaises(GuardianError) as cm:
                reserve_connector_operation(brain, "canva", "create_asset", "idem-key-200", ttl_seconds=300)
            self.assertIn("reservation expired", str(cm.exception))

            # Verify ledger state is now unknown_outcome
            fresh_ledger = IdempotencyLedger.load(brain)
            self.assertEqual(fresh_ledger[comp_key]["status"], "unknown_outcome")
            self.assertIn("Stale reservation TTL expired", fresh_ledger[comp_key]["error_reason"])

    def test_idempotency_unknown_outcome_reconciliation_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Idempotency Test", "Phase 5 test")

            # Reserve and mark unknown
            res = reserve_connector_operation(brain, "canva", "create_asset", "idem-key-300")
            token = res["owner_token"]
            fail_connector_operation(brain, "canva", "create_asset", "idem-key-300", "Network drop", owner_token=token)

            # Retry is blocked while in unknown_outcome
            with self.assertRaises(GuardianError) as cm:
                reserve_connector_operation(brain, "canva", "create_asset", "idem-key-300")
            self.assertIn("unknown_outcome", str(cm.exception))

            # Reconcile as cancelled (allowing retry)
            rec_res = reconcile_connector_outcome(
                brain, "canva", "create_asset", "idem-key-300", resolution="cancelled", resolution_reason="Verified not created on Canva"
            )
            self.assertTrue(rec_res["reconciled"])

            # Retry now succeeds after reconciliation
            res2 = reserve_connector_operation(brain, "canva", "create_asset", "idem-key-300")
            self.assertFalse(res2["already_completed"])


if __name__ == "__main__":
    unittest.main()
