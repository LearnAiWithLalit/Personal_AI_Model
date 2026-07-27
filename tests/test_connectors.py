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
from guardian_agent.policy import approve_action_request, request_action_approval


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_approval(
    brain,
    action: str,
    target: str,
    account_id: str = "acc-test",
    connector_scope: str = "canva",
) -> str:
    """Create and approve a real approval, returning its request ID."""
    req = request_action_approval(
        brain, action, target, "test-reason",
        account_id=account_id, connector_scope=connector_scope,
    )
    rid = req["id"]
    approve_action_request(brain, rid)
    return rid


def _minimal_evidence(
    connector: str = "canva",
    action: str = "create",
    idempotency_key: str = "test-key",
    approval_id: str = "dummy",
) -> dict:
    return {
        "account_id": "acc-test",
        "connector": connector,
        "action": action,
        "idempotency_key": idempotency_key,
        "approval_id": approval_id,
        "operator_identity": "tester",
        "evidence_type": "manual_review",
        "evidence_reference": "https://example.com/audit/ref",
        "timestamp": time.time(),
        "resolution_reason": "Test evidence",
    }


# ---------------------------------------------------------------------------
# Original connector tests
# ---------------------------------------------------------------------------

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
        """Reconciling a live (reserved) operation is rejected.
        Uses matching evidence to reach the ledger status check."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Idempotency Test", "Phase 5 test")
            res = reserve_connector_operation(brain, "canva", "create_asset", "idem-key-180", ttl_seconds=300)
            self.assertTrue(res["owner_token"].startswith("otok-"))

            comp_key = "canva:create_asset:idem-key-180"
            rid = _setup_approval(brain, "create_asset", comp_key)
            evidence = _minimal_evidence(
                connector="canva", action="create_asset",
                idempotency_key=comp_key, approval_id=rid,
            )

            with self.assertRaises(GuardianError) as cm:
                reconcile_connector_outcome(
                    brain, "canva", "create_asset", "idem-key-180",
                    resolution="cancelled", resolution_reason="Cancel live",
                    evidence=evidence, approval_id=rid,
                )
            # Should fail because status != unknown_outcome
            self.assertIn("only 'unknown_outcome' operations", str(cm.exception))

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
        """Reserve → fail → reconcile (with real approval) → retry."""
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

            # Create a real approved approval
            comp_key = "canva:create_asset:idem-key-300"
            rid = _setup_approval(brain, "create_asset", comp_key)

            # Reconcile as cancelled with evidence and approval (allowing retry)
            evidence = _minimal_evidence(
                connector="canva", action="create_asset",
                idempotency_key=comp_key, approval_id=rid,
            )
            rec_res = reconcile_connector_outcome(
                brain, "canva", "create_asset", "idem-key-300",
                resolution="cancelled", resolution_reason="Verified not created on Canva",
                evidence=evidence, approval_id=rid,
            )
            self.assertTrue(rec_res["reconciled"])
            self.assertEqual(rec_res["status"], "reconciled_cancelled")

            # Retry now succeeds after reconciliation (lock released)
            res2 = reserve_connector_operation(brain, "canva", "create_asset", "idem-key-300")
            self.assertFalse(res2["already_completed"])
            self.assertTrue(res2.get("re_reserved"))

    # --- Phase 5B: Connector Lifecycle Correctness ---

    def test_completion_from_unknown_outcome_is_rejected(self) -> None:
        """Verify that complete() rejects operations in unknown_outcome state."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Idempotency Test", "Phase 5B")

            # Reserve and then mark unknown
            res = reserve_connector_operation(brain, "canva", "create", "key-unk-compl")
            token = res["owner_token"]
            fail_connector_operation(
                brain, "canva", "create", "key-unk-compl", "Interrupted", owner_token=token
            )

            # Verify ledger status is now unknown_outcome
            ledger = IdempotencyLedger.load(brain)
            comp_key = "canva:create:key-unk-compl"
            self.assertEqual(ledger[comp_key]["status"], "unknown_outcome")

            # Attempting to complete an unknown_outcome record must be rejected
            with self.assertRaises(GuardianError) as cm:
                complete_connector_operation(
                    brain, "canva", "create", "key-unk-compl",
                    {"status": "ok"}, owner_token=token,
                )
            self.assertIn("unknown_outcome", str(cm.exception))
            self.assertIn("reconcile", str(cm.exception).lower())

    def test_completion_from_non_reserved_state_rejected(self) -> None:
        """Verify that complete() rejects operations that are not in 'reserved' state."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Idempotency Test", "Phase 5B")

            # Reserve and complete successfully
            res = reserve_connector_operation(brain, "canva", "create", "key-nr-compl")
            token = res["owner_token"]
            complete_connector_operation(
                brain, "canva", "create", "key-nr-compl",
                {"status": "ok", "asset_id": "a-999"}, owner_token=token,
            )

            # Attempting to complete an already-completed operation must be rejected
            with self.assertRaises(GuardianError) as cm:
                complete_connector_operation(
                    brain, "canva", "create", "key-nr-compl",
                    {"status": "overwrite"}, owner_token=token,
                )
            self.assertIn("immutable", str(cm.exception))

    def test_reconciliation_without_evidence_rejected(self) -> None:
        """Verify that reconcile() rejects operations without structured evidence."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Idempotency Test", "Phase 5B")

            # Reserve and mark unknown
            res = reserve_connector_operation(brain, "canva", "create", "key-rec-noev")
            token = res["owner_token"]
            fail_connector_operation(
                brain, "canva", "create", "key-rec-noev", "Error", owner_token=token
            )

            # Reconcile with empty evidence must be rejected
            with self.assertRaises(GuardianError) as cm:
                reconcile_connector_outcome(
                    brain, "canva", "create", "key-rec-noev",
                    resolution="cancelled", resolution_reason="Test",
                    evidence={}, approval_id="approval-001",
                )
            self.assertIn("evidence", str(cm.exception).lower())

            # Reconcile with missing fields in evidence must be rejected
            with self.assertRaises(GuardianError) as cm2:
                reconcile_connector_outcome(
                    brain, "canva", "create", "key-rec-noev",
                    resolution="cancelled", resolution_reason="Test",
                    evidence={"account_id": "test"}, approval_id="approval-001",
                )
            self.assertIn("missing required fields", str(cm2.exception).lower())

    def test_reconciliation_without_exact_approval_rejected(self) -> None:
        """Verify that reconcile() rejects operations without a valid approval_id."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Idempotency Test", "Phase 5B")

            # Reserve and mark unknown
            res = reserve_connector_operation(brain, "canva", "create", "key-rec-noapp")
            token = res["owner_token"]
            fail_connector_operation(
                brain, "canva", "create", "key-rec-noapp", "Error", owner_token=token
            )

            comp_key = "canva:create:key-rec-noapp"
            evidence = _minimal_evidence(
                connector="canva", action="create",
                idempotency_key=comp_key, approval_id="",
            )

            # Reconcile with empty approval_id must be rejected
            with self.assertRaises(GuardianError) as cm:
                reconcile_connector_outcome(
                    brain, "canva", "create", "key-rec-noapp",
                    resolution="cancelled", resolution_reason="Test",
                    evidence=evidence, approval_id="",
                )
            self.assertIn("approval_id", str(cm.exception).lower())

            # Reconcile with whitespace-only approval_id must be rejected
            with self.assertRaises(GuardianError) as cm2:
                reconcile_connector_outcome(
                    brain, "canva", "create", "key-rec-noapp",
                    resolution="cancelled", resolution_reason="Test",
                    evidence=evidence, approval_id="   ",
                )
            self.assertIn("approval_id", str(cm2.exception).lower())

    def test_reconciled_cancellation_permits_one_new_reservation(self) -> None:
        """Verify that a reconciled cancellation releases the lock and allows one new reservation."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Idempotency Test", "Phase 5B")

            # Reserve and mark unknown
            res = reserve_connector_operation(brain, "canva", "create", "key-rec-retry")
            token = res["owner_token"]
            fail_connector_operation(
                brain, "canva", "create", "key-rec-retry", "Timeout", owner_token=token
            )

            # Create a real approved approval
            comp_key = "canva:create:key-rec-retry"
            rid = _setup_approval(brain, "create", comp_key)

            # Reconcile as cancelled with full evidence and real approval
            evidence = _minimal_evidence(
                connector="canva", action="create",
                idempotency_key=comp_key, approval_id=rid,
            )
            rec_res = reconcile_connector_outcome(
                brain, "canva", "create", "key-rec-retry",
                resolution="cancelled", resolution_reason="Verified no asset was created - safe to retry",
                evidence=evidence, approval_id=rid,
            )
            self.assertTrue(rec_res["reconciled"])
            self.assertEqual(rec_res["status"], "reconciled_cancelled")

            # Verify ledger entry persists (not deleted)
            ledger = IdempotencyLedger.load(brain)
            self.assertIn(comp_key, ledger)
            self.assertEqual(ledger[comp_key]["status"], "reconciled_cancelled")
            self.assertIn("reconciliation_evidence", ledger[comp_key])
            self.assertEqual(ledger[comp_key]["reconciliation_approval_id"], rid)

            # New reservation must succeed (lock released)
            res2 = reserve_connector_operation(brain, "canva", "create", "key-rec-retry")
            self.assertFalse(res2["already_completed"])
            self.assertTrue(res2.get("re_reserved"))
            self.assertNotEqual(res2["owner_token"], token)  # New token generated

            # Verify the entry is now 'reserved' again
            ledger2 = IdempotencyLedger.load(brain)
            self.assertEqual(ledger2[comp_key]["status"], "reserved")


# ---------------------------------------------------------------------------
# Integration: Full Connector Lifecycle State Machine (End-to-End)
# ---------------------------------------------------------------------------

class ConnectorIntegrationLifecycleTests(unittest.TestCase):
    """Integration tests exercising the complete connector state machine end-to-end.

    Covers all valid transitions:
      → reserved → completed  (success)
      → reserved → unknown_outcome → reconciled_completed (terminal)
      → reserved → unknown_outcome → reconciled_cancelled → retry → reserved → completed
      → reserved → unknown_outcome → reconciled_failed → retry → reserved → completed
      → reserved (stale TTL) → unknown_outcome → reconciled_cancelled → retry → reserved → completed

    And all invalid transitions:
      unknown_outcome → completed (blocked)
      reconciled_completed → reserved (returns receipt)
      reconciled_cancelled → complete (blocked, must re-reserve)
      reconciled → reconcile again (blocked)
    """

    def _setup_recon_approval(
        self, brain, action: str, target: str, suffix: str = "001",
    ) -> str:
        """Create and approve a real approval for a reconciliation."""
        from guardian_agent.policy import approve_action_request, request_action_approval
        req = request_action_approval(
            brain, action, target, "reconciliation-test",
            account_id="int-test", connector_scope="canva",
        )
        rid = req["id"]
        approve_action_request(brain, rid)
        return rid

    def _full_evidence(self, brain, conn, action, idempotency_key, approval_suffix="001") -> dict:
        """Helper to build a complete reconciliation evidence dict.

        The account_id is set to "int-test" to match _setup_recon_approval.
        """
        from guardian_agent.connectors import RECONCILIATION_EVIDENCE_FIELDS
        evidence = {
            "account_id": "int-test",
            "connector": "canva",
            "action": action,
            "idempotency_key": idempotency_key,
            "approval_id": f"int-approval-{approval_suffix}",
            "operator_identity": "integration-test",
            "evidence_type": "manual_review",
            "evidence_reference": "https://canva.com/audit/int-test",
            "timestamp": time.time(),
            "resolution_reason": "Integration test verification",
        }
        # Verify evidence has all required fields
        missing = RECONCILIATION_EVIDENCE_FIELDS - set(evidence.keys())
        self.assertFalse(missing, f"Evidence missing fields: {missing}")
        return evidence

    # ---- Full success lifecycle ----

    def test_integration_success_lifecycle(self) -> None:
        """End-to-end success: reserve → complete → idempotent re-reserve."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Integration Test", "Success lifecycle")

            res = reserve_connector_operation(
                brain, "canva", "create_design", "int-success-001", ttl_seconds=600
            )
            self.assertFalse(res["already_completed"])
            owner_token = res["owner_token"]
            self.assertTrue(owner_token.startswith("otok-"))

            # Ledger state: reserved
            comp_key = "canva:create_design:int-success-001"
            ledger = IdempotencyLedger.load(brain)
            self.assertEqual(ledger[comp_key]["status"], "reserved")

            # Complete
            receipt = {
                "status": "completed",
                "asset_id": "design-001",
                "title": "Integration Test Design",
                "completed_at": time.time(),
            }
            complete_connector_operation(
                brain, "canva", "create_design", "int-success-001",
                receipt, owner_token=owner_token,
            )

            # Ledger state: completed (terminal)
            ledger2 = IdempotencyLedger.load(brain)
            self.assertEqual(ledger2[comp_key]["status"], "completed")
            self.assertEqual(ledger2[comp_key]["receipt"]["asset_id"], "design-001")

            # Re-reserve returns receipt (idempotent)
            res2 = reserve_connector_operation(
                brain, "canva", "create_design", "int-success-001", ttl_seconds=600
            )
            self.assertTrue(res2["already_completed"])
            self.assertEqual(res2["receipt"]["asset_id"], "design-001")

    # ---- Crash-recovery lifecycle ----

    def test_integration_crash_recovery_reconciled_cancelled(self) -> None:
        """Crash-recovery: reserve → crash → unknown_outcome → reconcile cancelled → retry → complete."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Integration Test", "Crash recovery cancelled")
            comp_key = "canva:create_asset:int-crash-001"

            # Step 1: Reserve
            res = reserve_connector_operation(
                brain, "canva", "create_asset", "int-crash-001", ttl_seconds=600
            )
            token = res["owner_token"]

            # Step 2: Crash → mark unknown
            fail_connector_operation(
                brain, "canva", "create_asset", "int-crash-001",
                "API timeout: no response from Canva", owner_token=token,
            )
            ledger = IdempotencyLedger.load(brain)
            self.assertEqual(ledger[comp_key]["status"], "unknown_outcome")

            # Step 3: Retry blocked
            with self.assertRaises(GuardianError) as cm:
                reserve_connector_operation(brain, "canva", "create_asset", "int-crash-001")
            self.assertIn("unknown_outcome", str(cm.exception))

            # Step 4: Create real approval and reconcile as cancelled
            rid = self._setup_recon_approval(brain, "create_asset", comp_key, "cancelled-001")
            evidence = self._full_evidence(brain, "canva", "create_asset", comp_key, "cancelled-001")
            evidence["approval_id"] = rid
            rec_res = reconcile_connector_outcome(
                brain, "canva", "create_asset", "int-crash-001",
                resolution="cancelled", resolution_reason="Verified no asset was created",
                evidence=evidence, approval_id=rid,
            )
            self.assertTrue(rec_res["reconciled"])
            self.assertEqual(rec_res["status"], "reconciled_cancelled")

            # Step 5: Retry succeeds
            res2 = reserve_connector_operation(
                brain, "canva", "create_asset", "int-crash-001", ttl_seconds=600
            )
            self.assertFalse(res2["already_completed"])
            self.assertTrue(res2.get("re_reserved"))

            # Step 6: Complete the retry
            receipt2 = {"status": "completed", "asset_id": "design-retry-001", "retry": True}
            complete_connector_operation(
                brain, "canva", "create_asset", "int-crash-001",
                receipt2, owner_token=res2["owner_token"],
            )

            # Verify final state
            ledger2 = IdempotencyLedger.load(brain)
            self.assertEqual(ledger2[comp_key]["status"], "completed")

    def test_integration_crash_recovery_reconciled_failed(self) -> None:
        """Crash-recovery: reserve → crash → unknown → reconcile failed → retry → complete."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Integration Test", "Crash recovery failed")
            comp_key = "canva:create_asset:int-crash-002"

            # Reserve
            res = reserve_connector_operation(brain, "canva", "create_asset", "int-crash-002")
            token = res["owner_token"]

            # Crash
            fail_connector_operation(
                brain, "canva", "create_asset", "int-crash-002",
                "Network error", owner_token=token,
            )

            # Create real approval and reconcile as failed
            rid = self._setup_recon_approval(brain, "create_asset", comp_key, "failed-001")
            evidence = self._full_evidence(brain, "canva", "create_asset", comp_key, "failed-001")
            evidence["approval_id"] = rid
            rec_res = reconcile_connector_outcome(
                brain, "canva", "create_asset", "int-crash-002",
                resolution="failed", resolution_reason="Confirmed network error occurred",
                evidence=evidence, approval_id=rid,
            )
            self.assertEqual(rec_res["status"], "reconciled_failed")

            # Retry succeeds (failed releases lock)
            res2 = reserve_connector_operation(brain, "canva", "create_asset", "int-crash-002")
            self.assertTrue(res2.get("re_reserved"))

            # Complete
            complete_connector_operation(
                brain, "canva", "create_asset", "int-crash-002",
                {"status": "completed"}, owner_token=res2["owner_token"],
            )
            ledger = IdempotencyLedger.load(brain)
            self.assertEqual(ledger[comp_key]["status"], "completed")

    def test_integration_crash_recovery_reconciled_completed(self) -> None:
        """Crash-recovery: reserve → crash → unknown → reconcile completed (terminal)."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Integration Test", "Crash recovery completed")
            comp_key = "canva:create_asset:int-crash-003"

            # Reserve
            res = reserve_connector_operation(brain, "canva", "create_asset", "int-crash-003")
            token = res["owner_token"]

            # Crash
            fail_connector_operation(
                brain, "canva", "create_asset", "int-crash-003",
                "Unknown outcome after API call", owner_token=token,
            )

            # Create real approval and reconcile as completed
            rid = self._setup_recon_approval(brain, "create_asset", comp_key, "completed-001")
            evidence = self._full_evidence(brain, "canva", "create_asset", comp_key, "completed-001")
            evidence["approval_id"] = rid
            rec_res = reconcile_connector_outcome(
                brain, "canva", "create_asset", "int-crash-003",
                resolution="completed",
                resolution_reason="Verified asset was created successfully via API audit",
                evidence=evidence, approval_id=rid,
                receipt={"status": "verified_completed", "asset_id": "design-verified-001"},
            )
            self.assertEqual(rec_res["status"], "reconciled_completed")

            # Terminal: re-reserve returns receipt
            res2 = reserve_connector_operation(brain, "canva", "create_asset", "int-crash-003")
            self.assertTrue(res2["already_completed"])
            self.assertEqual(res2["receipt"]["asset_id"], "design-verified-001")

            # Cannot reconcile again (already terminal)
            rid3 = self._setup_recon_approval(brain, "create_asset", comp_key, "completed-002")
            evidence3 = self._full_evidence(brain, "canva", "create_asset", comp_key, "completed-002")
            evidence3["approval_id"] = rid3
            with self.assertRaises(GuardianError) as cm:
                reconcile_connector_outcome(
                    brain, "canva", "create_asset", "int-crash-003",
                    resolution="cancelled", resolution_reason="Should fail",
                    evidence=evidence3, approval_id=rid3,
                )
            self.assertIn("unknown_outcome", str(cm.exception))

    # ---- Stale TTL lifecycle ----

    def test_integration_stale_ttl_full_lifecycle(self) -> None:
        """Stale TTL expiry: reserve (stale) → unknown (auto) → reconcile cancelled → retry → complete."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Integration Test", "Stale TTL lifecycle")
            comp_key = "canva:export_design:int-stale-001"

            # Manually inject stale reservation
            ledger = IdempotencyLedger.load(brain)
            ledger[comp_key] = {
                "status": "reserved",
                "payload_hash": "stale-hash",
                "owner_token": "otok-stale",
                "reserved_at": "2026-06-01 00:00 UTC",
                "reserved_timestamp": time.time() - 400,  # Expired (400s > 300s TTL)
            }
            IdempotencyLedger._save_under_lock(brain, ledger)

            # Attempt reserve → triggers TTL check → auto-transitions to unknown_outcome
            with self.assertRaises(GuardianError) as cm:
                reserve_connector_operation(brain, "canva", "export_design", "int-stale-001", ttl_seconds=300)
            self.assertIn("reservation expired", str(cm.exception))

            # Verify auto-transition to unknown_outcome
            ledger2 = IdempotencyLedger.load(brain)
            self.assertEqual(ledger2[comp_key]["status"], "unknown_outcome")

            # Create real approval and reconcile as cancelled
            rid = self._setup_recon_approval(brain, "export_design", comp_key, "stale-001")
            evidence = self._full_evidence(brain, "canva", "export_design", comp_key, "stale-001")
            evidence["approval_id"] = rid
            rec_res = reconcile_connector_outcome(
                brain, "canva", "export_design", "int-stale-001",
                resolution="cancelled", resolution_reason="Stale reservation cleared",
                evidence=evidence, approval_id=rid,
            )
            self.assertTrue(rec_res["reconciled"])

            # Retry succeeds
            res2 = reserve_connector_operation(brain, "canva", "export_design", "int-stale-001")
            self.assertFalse(res2["already_completed"])

            # Complete
            complete_connector_operation(
                brain, "canva", "export_design", "int-stale-001",
                {"status": "completed", "file": "design-export.png"},
                owner_token=res2["owner_token"],
            )
            ledger3 = IdempotencyLedger.load(brain)
            self.assertEqual(ledger3[comp_key]["status"], "completed")

    # ---- Invalid transition enforcement ----

    def test_integration_cannot_complete_from_unknown_outcome(self) -> None:
        """Verify complete() rejects unknown_outcome even with valid owner_token."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Integration Test", "Block unknown complete")

            res = reserve_connector_operation(brain, "canva", "publish", "int-block-001")
            token = res["owner_token"]
            fail_connector_operation(brain, "canva", "publish", "int-block-001", "Interrupted", owner_token=token)

            with self.assertRaises(GuardianError) as cm:
                complete_connector_operation(
                    brain, "canva", "publish", "int-block-001",
                    {"status": "ok"}, owner_token=token,
                )
            self.assertIn("unknown_outcome", str(cm.exception))
            self.assertIn("reconcile", str(cm.exception).lower())

    def test_integration_cannot_complete_from_reconciled(self) -> None:
        """Verify complete() rejects reconciled_cancelled state."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Integration Test", "Block reconciled complete")

            res = reserve_connector_operation(brain, "canva", "delete", "int-block-002")
            token = res["owner_token"]
            fail_connector_operation(brain, "canva", "delete", "int-block-002", "Error", owner_token=token)

            # Create real approval and reconcile as cancelled
            comp_key = "canva:delete:int-block-002"
            rid = self._setup_recon_approval(brain, "delete", comp_key, "block-002")
            evidence = self._full_evidence(brain, "canva", "delete", comp_key, "block-002")
            evidence["approval_id"] = rid
            reconcile_connector_outcome(
                brain, "canva", "delete", "int-block-002",
                resolution="cancelled", resolution_reason="Test",
                evidence=evidence, approval_id=rid,
            )

            # Cannot complete from reconciled_cancelled
            with self.assertRaises(GuardianError) as cm:
                complete_connector_operation(
                    brain, "canva", "delete", "int-block-002",
                    {"status": "overwrite"}, owner_token=token,
                )
            self.assertIn("reconciled_cancelled", str(cm.exception))

    def test_integration_cannot_double_reconcile(self) -> None:
        """Verify once reconciled, a second reconcile is blocked."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Integration Test", "No double reconcile")

            res = reserve_connector_operation(brain, "canva", "update", "int-block-003")
            token = res["owner_token"]
            fail_connector_operation(brain, "canva", "update", "int-block-003", "Err", owner_token=token)

            comp_key = "canva:update:int-block-003"
            rid1 = self._setup_recon_approval(brain, "update", comp_key, "double-001")
            evidence = self._full_evidence(brain, "canva", "update", comp_key, "double-001")
            evidence["approval_id"] = rid1

            # First reconcile succeeds
            r1 = reconcile_connector_outcome(
                brain, "canva", "update", "int-block-003",
                resolution="cancelled", resolution_reason="First reconcile",
                evidence=evidence, approval_id=rid1,
            )
            self.assertTrue(r1["reconciled"])

            # Second reconcile on same (now reconciled_cancelled) key must be blocked
            rid2 = self._setup_recon_approval(brain, "update", comp_key, "double-002")
            evidence2 = self._full_evidence(brain, "canva", "update", comp_key, "double-002")
            evidence2["approval_id"] = rid2
            with self.assertRaises(GuardianError) as cm:
                reconcile_connector_outcome(
                    brain, "canva", "update", "int-block-003",
                    resolution="cancelled", resolution_reason="Second reconcile",
                    evidence=evidence2, approval_id=rid2,
                )
            self.assertIn("unknown_outcome", str(cm.exception))

    # ---- Cross-connector isolation ----

    def test_integration_cross_connector_isolation(self) -> None:
        """Verify different connectors maintain independent ledger keys."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Integration Test", "Cross-connector")

            # Canva operation
            r1 = reserve_connector_operation(brain, "canva", "create_asset", "cross-key-001")
            t1 = r1["owner_token"]

            # Adobe operation with same action and idempotency key must not collide
            r2 = reserve_connector_operation(brain, "adobe", "create_asset", "cross-key-001")
            t2 = r2["owner_token"]

            self.assertNotEqual(t1, t2)

            # Complete Canva, Adobe still reserved
            complete_connector_operation(
                brain, "canva", "create_asset", "cross-key-001",
                {"status": "done"}, owner_token=t1,
            )

            # Adobe can still complete independently
            complete_connector_operation(
                brain, "adobe", "create_asset", "cross-key-001",
                {"status": "done"}, owner_token=t2,
            )

            ledger = IdempotencyLedger.load(brain)
            self.assertEqual(ledger["canva:create_asset:cross-key-001"]["status"], "completed")
            self.assertEqual(ledger["adobe:create_asset:cross-key-001"]["status"], "completed")

    def test_integration_canva_connector_mock_create_asset_success(self) -> None:
        """Full CanvaConnector.create_asset() mock lifecycle: reserve → complete → idempotent."""
        import os
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Integration Test", "Canva mock create")
            register_account(
                brain,
                account_id="canva-int",
                service_name="canva",
                account_label="Canva Integration",
                vault_ref="vault:canva_int_key",
                allowed_domains=["canva.com"],
            )
            os.environ["CANVA_INT_KEY"] = "secret_int_token"
            try:
                conn = get_connector("canva", "canva-int")

                # First creation
                created = conn.create_asset(brain, title="Integration Design", allow_mock=True)
                self.assertEqual(created["status"], "created")
                self.assertTrue(created["asset_id"].startswith("canva-"))

                # Idempotent duplicate returns same result
                created2 = conn.create_asset(brain, title="Integration Design", allow_mock=True)
                self.assertEqual(created["asset_id"], created2["asset_id"])

                # Verify ledger has a completed entry
                ledger = IdempotencyLedger.load(brain)
                completed_entries = [
                    (k, v) for k, v in ledger.items()
                    if v.get("status") == "completed"
                ]
                self.assertGreaterEqual(len(completed_entries), 1)
                _, entry_val = completed_entries[0]
                self.assertEqual(entry_val["receipt"]["asset_id"], created["asset_id"])
            finally:
                os.environ.pop("CANVA_INT_KEY", None)

    def test_integration_canva_connector_mock_create_asset_fail_and_reconcile(self) -> None:
        """Simulate CanvaConnector.create_asset() failure via ledger helpers, then
        reconcile and retry through the actual CanvaConnector."""
        import os
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Integration Test", "Canva reconcile")
            register_account(
                brain,
                account_id="canva-recon",
                service_name="canva",
                account_label="Canva Reconcile",
                vault_ref="vault:canva_recon_key",
                allowed_domains=["canva.com"],
            )
            os.environ["CANVA_RECON_KEY"] = "secret_recon_token"
            try:
                conn = get_connector("canva", "canva-recon")

                # Step 1: Reserve via helpers (simulate what connector does internally)
                r = reserve_connector_operation(
                    brain, "canva", "create_asset", "int-recon-001", ttl_seconds=600
                )
                t = r["owner_token"]

                # Step 2: Simulate crash during create_asset
                fail_connector_operation(
                    brain, "canva", "create_asset", "int-recon-001",
                    "Simulated: Canva API timeout during asset creation", owner_token=t,
                )

                comp_key = "canva:create_asset:int-recon-001"
                ledger = IdempotencyLedger.load(brain)
                self.assertEqual(ledger[comp_key]["status"], "unknown_outcome")

                # Step 3: Create real approval and reconcile as cancelled
                rid = self._setup_recon_approval(brain, "create_asset", comp_key, "recon-001")
                evidence = self._full_evidence(brain, "canva-recon", "create_asset", comp_key, "recon-001")
                evidence["approval_id"] = rid
                rec_res = reconcile_connector_outcome(
                    brain, "canva", "create_asset", "int-recon-001",
                    resolution="cancelled",
                    resolution_reason="Verified via Canva audit log: no asset was created",
                    evidence=evidence, approval_id=rid,
                )
                self.assertTrue(rec_res["reconciled"])

                # Step 4: Retry via the actual connector (creates with different title)
                created = conn.create_asset(brain, title="Retry Design", allow_mock=True)
                self.assertEqual(created["status"], "created")
                self.assertTrue(created["asset_id"].startswith("canva-"))
            finally:
                os.environ.pop("CANVA_RECON_KEY", None)

    # =====================================================================
    # Real Approval Validation Tests
    # =====================================================================

    def test_reconcile_fake_nonexistent_approval_rejected(self) -> None:
        """Reconcile must reject a fake/nonexistent approval_id."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Approval Test", "Fake approval")

            # Reserve and mark unknown
            res = reserve_connector_operation(brain, "canva", "create", "key-fake-appr")
            fail_connector_operation(
                brain, "canva", "create", "key-fake-appr",
                "Error", owner_token=res["owner_token"],
            )

            comp_key = "canva:create:key-fake-appr"
            evidence = _minimal_evidence(
                connector="canva", action="create",
                idempotency_key=comp_key, approval_id="fake-non-existent-id",
            )

            with self.assertRaises(GuardianError) as cm:
                reconcile_connector_outcome(
                    brain, "canva", "create", "key-fake-appr",
                    resolution="cancelled", resolution_reason="Test",
                    evidence=evidence, approval_id="fake-non-existent-id",
                )
            self.assertIn("not found in approval queue", str(cm.exception))

    def test_reconcile_mismatched_evidence_approval_id_rejected(self) -> None:
        """Reconcile must reject when evidence approval_id != supplied approval_id."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Approval Test", "Mismatch approval")

            # Reserve and mark unknown
            res = reserve_connector_operation(brain, "canva", "create", "key-mismatch-appr")
            fail_connector_operation(
                brain, "canva", "create", "key-mismatch-appr",
                "Error", owner_token=res["owner_token"],
            )

            comp_key = "canva:create:key-mismatch-appr"
            rid = _setup_approval(brain, "create", comp_key)

            # Evidence has DIFFERENT approval_id than supplied
            evidence = _minimal_evidence(
                connector="canva", action="create",
                idempotency_key=comp_key,
                approval_id="some-other-id",  # mismatched!
            )

            with self.assertRaises(GuardianError) as cm:
                reconcile_connector_outcome(
                    brain, "canva", "create", "key-mismatch-appr",
                    resolution="cancelled", resolution_reason="Test",
                    evidence=evidence, approval_id=rid,  # supplied rid doesn't match evidence
                )
            self.assertIn("evidence approval_id", str(cm.exception).lower())

    def test_reconcile_mismatched_connector_rejected(self) -> None:
        """Reconcile must reject when evidence connector != ledger connector."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Approval Test", "Mismatch connector")

            res = reserve_connector_operation(brain, "canva", "create", "key-mismatch-conn")
            fail_connector_operation(
                brain, "canva", "create", "key-mismatch-conn",
                "Error", owner_token=res["owner_token"],
            )

            comp_key = "canva:create:key-mismatch-conn"
            rid = _setup_approval(brain, "create", comp_key)

            evidence = _minimal_evidence(
                connector="adobe",  # wrong!
                action="create",
                idempotency_key=comp_key, approval_id=rid,
            )

            with self.assertRaises(GuardianError) as cm:
                reconcile_connector_outcome(
                    brain, "canva", "create", "key-mismatch-conn",
                    resolution="cancelled", resolution_reason="Test",
                    evidence=evidence, approval_id=rid,
                )
            self.assertIn("evidence connector", str(cm.exception).lower())

    def test_reconcile_mismatched_action_rejected(self) -> None:
        """Reconcile must reject when evidence action != ledger action."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Approval Test", "Mismatch action")

            res = reserve_connector_operation(brain, "canva", "create", "key-mismatch-act")
            fail_connector_operation(
                brain, "canva", "create", "key-mismatch-act",
                "Error", owner_token=res["owner_token"],
            )

            comp_key = "canva:create:key-mismatch-act"
            rid = _setup_approval(brain, "delete", comp_key, connector_scope="canva")

            evidence = _minimal_evidence(
                connector="canva",
                action="delete",  # wrong!
                idempotency_key=comp_key, approval_id=rid,
            )

            with self.assertRaises(GuardianError) as cm:
                reconcile_connector_outcome(
                    brain, "canva", "create", "key-mismatch-act",
                    resolution="cancelled", resolution_reason="Test",
                    evidence=evidence, approval_id=rid,
                )
            self.assertIn("evidence action", str(cm.exception).lower())

    def test_reconcile_mismatched_idempotency_key_rejected(self) -> None:
        """Reconcile must reject when evidence idempotency_key != composite_key."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Approval Test", "Mismatch idem key")

            res = reserve_connector_operation(brain, "canva", "create", "key-mismatch-idem")
            fail_connector_operation(
                brain, "canva", "create", "key-mismatch-idem",
                "Error", owner_token=res["owner_token"],
            )

            comp_key = "canva:create:key-mismatch-idem"
            rid = _setup_approval(brain, "create", comp_key)

            evidence = _minimal_evidence(
                connector="canva", action="create",
                idempotency_key="canva:create:WRONG-KEY",  # wrong!
                approval_id=rid,
            )

            with self.assertRaises(GuardianError) as cm:
                reconcile_connector_outcome(
                    brain, "canva", "create", "key-mismatch-idem",
                    resolution="cancelled", resolution_reason="Test",
                    evidence=evidence, approval_id=rid,
                )
            self.assertIn("idempotency_key", str(cm.exception).lower())

    def test_reconcile_reused_approval_rejected(self) -> None:
        """Reconcile must reject reusing the same approval for two different operations."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Approval Test", "Reused approval")

            # Two different operations
            r1 = reserve_connector_operation(brain, "canva", "create", "key-reuse-001")
            fail_connector_operation(brain, "canva", "create", "key-reuse-001", "Err1", owner_token=r1["owner_token"])

            r2 = reserve_connector_operation(brain, "canva", "create", "key-reuse-002")
            fail_connector_operation(brain, "canva", "create", "key-reuse-002", "Err2", owner_token=r2["owner_token"])

            # Single approval
            comp_key1 = "canva:create:key-reuse-001"
            comp_key2 = "canva:create:key-reuse-002"
            rid = _setup_approval(brain, "create", comp_key1)

            # First reconcile succeeds
            evidence1 = _minimal_evidence(
                connector="canva", action="create",
                idempotency_key=comp_key1, approval_id=rid,
            )
            rec1 = reconcile_connector_outcome(
                brain, "canva", "create", "key-reuse-001",
                resolution="cancelled", resolution_reason="First",
                evidence=evidence1, approval_id=rid,
            )
            self.assertTrue(rec1["reconciled"])

            # Second reconcile with SAME approval must be rejected
            # (the approval was consumed already)
            evidence2 = _minimal_evidence(
                connector="canva", action="create",
                idempotency_key=comp_key2, approval_id=rid,
            )
            with self.assertRaises(GuardianError) as cm:
                reconcile_connector_outcome(
                    brain, "canva", "create", "key-reuse-002",
                    resolution="cancelled", resolution_reason="Second",
                    evidence=evidence2, approval_id=rid,  # same rid, already consumed
                )
            # The approval is in 'consumed' state, not 'approved'
            error_msg = str(cm.exception).lower()
            self.assertTrue(
                "not 'approved'" in error_msg or "consumed" in error_msg
            )

    def test_reconcile_valid_exact_approval_succeeds(self) -> None:
        """Verify that a valid, exactly-matching approval succeeds exactly once."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Approval Test", "Valid approval")

            res = reserve_connector_operation(brain, "canva", "publish", "key-valid-001")
            fail_connector_operation(
                brain, "canva", "publish", "key-valid-001",
                "Timeout", owner_token=res["owner_token"],
            )

            comp_key = "canva:publish:key-valid-001"
            rid = _setup_approval(brain, "publish", comp_key)

            evidence = _minimal_evidence(
                connector="canva", action="publish",
                idempotency_key=comp_key, approval_id=rid,
            )

            # First reconcile succeeds
            rec = reconcile_connector_outcome(
                brain, "canva", "publish", "key-valid-001",
                resolution="cancelled", resolution_reason="Valid test",
                evidence=evidence, approval_id=rid,
            )
            self.assertTrue(rec["reconciled"])
            self.assertTrue(rec["approval_consumed"])

            # Second reconcile with same key (but fresh approval) blocked by ledger
            rid2 = _setup_approval(brain, "publish", "canva:publish:key-valid-001")
            evidence2 = _minimal_evidence(
                connector="canva", action="publish",
                idempotency_key=comp_key, approval_id=rid2,
            )
            with self.assertRaises(GuardianError) as cm:
                reconcile_connector_outcome(
                    brain, "canva", "publish", "key-valid-001",
                    resolution="cancelled", resolution_reason="Second",
                    evidence=evidence2, approval_id=rid2,
                )
            self.assertIn("unknown_outcome", str(cm.exception).lower())

    # ---- Abort Preflight Tests ----

    def test_abort_preflight_transitions_to_preflight_aborted(self) -> None:
        """Verify abort_preflight transitions reserved → preflight_aborted."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Abort Test", "Phase 5B")

            # Reserve
            res = reserve_connector_operation(brain, "canva", "create", "key-abort-001")
            token = res["owner_token"]

            # Abort preflight
            IdempotencyLedger.abort_preflight(
                brain, "canva:create:key-abort-001", "Selector not found on page", owner_token=token,
            )

            # Verify preflight_aborted state
            comp_key = "canva:create:key-abort-001"
            ledger = IdempotencyLedger.load(brain)
            self.assertEqual(ledger[comp_key]["status"], "preflight_aborted")
            self.assertIn("Selector not found on page", ledger[comp_key]["preflight_reason"])

    def test_abort_preflight_no_unknown_outcome_created(self) -> None:
        """Verify abort does NOT create an unknown_outcome entry."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Abort Test", "Phase 5B")

            res = reserve_connector_operation(brain, "canva", "create", "key-abort-002")
            token = res["owner_token"]

            IdempotencyLedger.abort_preflight(
                brain, "canva:create:key-abort-002", "Preflight reason", owner_token=token,
            )

            comp_key = "canva:create:key-abort-002"
            ledger = IdempotencyLedger.load(brain)
            self.assertEqual(ledger[comp_key]["status"], "preflight_aborted")
            self.assertNotEqual(ledger[comp_key]["status"], "unknown_outcome")

    def test_abort_preflight_wrong_token_rejected(self) -> None:
        """Verify abort with wrong owner token is rejected (fail-closed)."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Abort Test", "Phase 5B")

            res = reserve_connector_operation(brain, "canva", "create", "key-abort-003")

            with self.assertRaises(GuardianError) as cm:
                IdempotencyLedger.abort_preflight(
                    brain, "canva:create:key-abort-003", "Reason", owner_token="wrong_token",
                )
            self.assertIn("owner token mismatch", str(cm.exception).lower())

    def test_abort_preflight_then_retry_receives_new_token(self) -> None:
        """Verify that after abort, re-reservation gets a new owner token."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Abort Test", "Phase 5B")

            res = reserve_connector_operation(brain, "canva", "create", "key-abort-004")
            token1 = res["owner_token"]

            IdempotencyLedger.abort_preflight(
                brain, "canva:create:key-abort-004", "Preflight failed", owner_token=token1,
            )

            # Re-reserve must succeed with new token
            res2 = reserve_connector_operation(brain, "canva", "create", "key-abort-004")
            self.assertFalse(res2["already_completed"])
            self.assertTrue(res2.get("re_reserved"))
            self.assertNotEqual(res2["owner_token"], token1)

    def test_abort_preflight_completed_entry_rejected(self) -> None:
        """Verify abort on a completed entry is rejected (immutable)."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Abort Test", "Phase 5B")

            res = reserve_connector_operation(brain, "canva", "create", "key-abort-005")
            token = res["owner_token"]
            complete_connector_operation(
                brain, "canva", "create", "key-abort-005", {"status": "ok"}, owner_token=token,
            )

            with self.assertRaises(GuardianError) as cm:
                IdempotencyLedger.abort_preflight(
                    brain, "canva:create:key-abort-005", "Cannot abort", owner_token=token,
                )
            self.assertIn("immutable", str(cm.exception).lower())

    def test_abort_preflight_unknown_outcome_rejected(self) -> None:
        """Verify abort on an unknown_outcome entry is rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Abort Test", "Phase 5B")

            res = reserve_connector_operation(brain, "canva", "create", "key-abort-006")
            token = res["owner_token"]
            fail_connector_operation(
                brain, "canva", "create", "key-abort-006", "Timeout", owner_token=token,
            )

            with self.assertRaises(GuardianError) as cm:
                IdempotencyLedger.abort_preflight(
                    brain, "canva:create:key-abort-006", "Cannot abort", owner_token=token,
                )
            self.assertIn("unknown_outcome", str(cm.exception).lower())

    def test_complete_from_preflight_aborted_rejected(self) -> None:
        """Verify complete() rejects preflight_aborted state."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Abort Test", "Phase 5B")

            res = reserve_connector_operation(brain, "canva", "create", "key-abort-007")
            token = res["owner_token"]
            IdempotencyLedger.abort_preflight(
                brain, "canva:create:key-abort-007", "Preflight failed", owner_token=token,
            )

            with self.assertRaises(GuardianError) as cm:
                complete_connector_operation(
                    brain, "canva", "create", "key-abort-007",
                    {"status": "should fail"}, owner_token=token,
                )
            self.assertIn("preflight-aborted", str(cm.exception).lower())

    def test_mark_unknown_from_preflight_aborted_rejected(self) -> None:
        """Verify mark_unknown() rejects preflight_aborted state."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Abort Test", "Phase 5B")

            res = reserve_connector_operation(brain, "canva", "create", "key-abort-008")
            token = res["owner_token"]
            IdempotencyLedger.abort_preflight(
                brain, "canva:create:key-abort-008", "Preflight", owner_token=token,
            )

            with self.assertRaises(GuardianError) as cm:
                fail_connector_operation(
                    brain, "canva", "create", "key-abort-008", "Error", owner_token=token,
                )
            self.assertIn("preflight-aborted", str(cm.exception).lower())

    # ---- WAL Crash Recovery Tests ----

    def test_wal_recover_before_approval_rollback_to_unknown(self) -> None:
        """Simulate crash AFTER Phase 1 (WAL written) but BEFORE Phase 2 (approval consumed).

        Recovery should rollback the entry to 'unknown_outcome'.
        """
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "WAL Test", "Recover before approval")
            comp_key = "canva:create:key-wal-001"

            # Reserve and mark unknown
            res = reserve_connector_operation(brain, "canva", "create", "key-wal-001")
            fail_connector_operation(
                brain, "canva", "create", "key-wal-001", "Timeout", owner_token=res["owner_token"],
            )

            # Manually inject reconciling_started WAL entry (simulating crash after Phase 1)
            rid = _setup_approval(brain, "create", comp_key)
            ledger = IdempotencyLedger.load(brain)
            ledger[comp_key] = {
                "status": "reconciling_started",
                "reconciling_resolution": "cancelled",
                "reconciling_approval_id": rid,
                "reconciling_evidence": _minimal_evidence(
                    connector="canva", action="create",
                    idempotency_key=comp_key, approval_id=rid,
                ),
                "reconciling_started_at": time.time(),
            }
            IdempotencyLedger._save_under_lock(brain, ledger)

            # Trigger recovery via reserve() — should rollback since approval is still 'approved'
            with self.assertRaises(GuardianError) as cm:
                reserve_connector_operation(brain, "canva", "create", "key-wal-001")
            self.assertIn("unknown_outcome", str(cm.exception))

            # Verify entry was rolled back to unknown_outcome
            ledger2 = IdempotencyLedger.load(brain)
            self.assertEqual(ledger2[comp_key]["status"], "unknown_outcome")
            self.assertIn("rolled back", ledger2[comp_key].get("error_reason", "").lower())

            # Verify WAL fields were cleaned up
            self.assertNotIn("reconciling_resolution", ledger2[comp_key])

    def test_wal_recover_after_approval_completes_reconciliation(self) -> None:
        """Simulate crash AFTER Phase 2 (approval consumed) but BEFORE Phase 3 (ledger transition).

        Recovery should complete the reconciliation by transitioning to reconciled_*.
        """
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "WAL Test", "Recover after approval")
            comp_key = "canva:create:key-wal-002"

            # Reserve and mark unknown
            res = reserve_connector_operation(brain, "canva", "create", "key-wal-002")
            fail_connector_operation(
                brain, "canva", "create", "key-wal-002", "Timeout", owner_token=res["owner_token"],
            )

            # Manually consume the approval (simulating crash after Phase 2)
            rid = _setup_approval(brain, "create", comp_key)
            from guardian_agent.policy import consume_action_approval
            consumed = consume_action_approval(
                brain, request_id=rid, action="create", target=comp_key,
                after_evidence="WAL test",
                account_id="acc-test", connector_scope="canva",
            )
            self.assertEqual(consumed["status"], "consumed")

            # Manually inject reconciling_started WAL entry (simulating crash after Phase 2)
            ledger = IdempotencyLedger.load(brain)
            ledger[comp_key] = {
                "status": "reconciling_started",
                "reconciling_resolution": "cancelled",
                "reconciling_approval_id": rid,
                "reconciling_evidence": _minimal_evidence(
                    connector="canva", action="create",
                    idempotency_key=comp_key, approval_id=rid,
                ),
                "reconciling_started_at": time.time(),
            }
            IdempotencyLedger._save_under_lock(brain, ledger)

            # Trigger recovery via reserve() — recovery finds the consumed approval
            # and transitions the entry to reconciled_cancelled. Since cancelled
            # releases the lock, reserve() returns a fresh reservation.
            ledger_before = IdempotencyLedger.load(brain)
            self.assertEqual(ledger_before[comp_key]["status"], "reconciling_started")

            res2 = reserve_connector_operation(brain, "canva", "create", "key-wal-002")

            # Entry should have been recovered first (reconciled_cancelled),
            # then re-reserved since cancelled releases the lock
            ledger2 = IdempotencyLedger.load(brain)
            self.assertEqual(ledger2[comp_key]["status"], "reserved")
            self.assertTrue(res2.get("re_reserved"))

    def test_wal_reconciling_started_blocked_by_reserve(self) -> None:
        """Verify reserve() blocks on reconciling_started state before recovery."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "WAL Test", "Block reconciling")
            comp_key = "canva:create:key-wal-003"

            # Reserve and mark unknown
            res = reserve_connector_operation(brain, "canva", "create", "key-wal-003")
            fail_connector_operation(
                brain, "canva", "create", "key-wal-003", "Timeout", owner_token=res["owner_token"],
            )

            # Manually inject reconciling_started WITHOUT consuming approval
            # (so recovery will rollback, but before it does, reserve will block)
            # Here we inject a reconciling_started with a NON-EXISTENT approval
            ledger = IdempotencyLedger.load(brain)
            ledger[comp_key] = {
                "status": "reconciling_started",
                "reconciling_resolution": "cancelled",
                "reconciling_approval_id": "nonexistent-approval",
                "reconciling_evidence": _minimal_evidence(
                    connector="canva", action="create",
                    idempotency_key=comp_key, approval_id="nonexistent-approval",
                ),
                "reconciling_started_at": time.time(),
            }
            IdempotencyLedger._save_under_lock(brain, ledger)

            # Reserve triggers recovery, approval not found → rollback to unknown
            with self.assertRaises(GuardianError) as cm:
                reserve_connector_operation(brain, "canva", "create", "key-wal-003")
            self.assertIn("unknown_outcome", str(cm.exception).lower())

            # Verify rolled back
            ledger2 = IdempotencyLedger.load(brain)
            self.assertEqual(ledger2[comp_key]["status"], "unknown_outcome")

    def test_reconcile_mismatched_account_id_rejected(self) -> None:
        """Reconcile must reject when evidence account_id != approval account_id."""
        with tempfile.TemporaryDirectory() as tmp:
            brain = initialize(Path(tmp) / "demo", "Approval Test", "Mismatch account_id")

            res = reserve_connector_operation(brain, "canva", "create", "key-mismatch-acc")
            fail_connector_operation(
                brain, "canva", "create", "key-mismatch-acc",
                "Error", owner_token=res["owner_token"],
            )

            comp_key = "canva:create:key-mismatch-acc"
            # Create approval for a different account
            rid = _setup_approval(brain, "create", comp_key, account_id="different-account")

            evidence = _minimal_evidence(
                connector="canva", action="create",
                idempotency_key=comp_key, approval_id=rid,
            )
            # evidence has account_id="acc-test" (from _minimal_evidence) but approval is for "different-account"

            with self.assertRaises(GuardianError) as cm:
                reconcile_connector_outcome(
                    brain, "canva", "create", "key-mismatch-acc",
                    resolution="cancelled", resolution_reason="Test",
                    evidence=evidence, approval_id=rid,
                )
            self.assertIn("account_id", str(cm.exception).lower())


if __name__ == "__main__":
    unittest.main()
