"""End-to-end smoke test for browser+connector idempotency ledger features.

Exercises the full lifecycle across both domains:
  - Connector: reserve -> complete, abort_preflight -> retry, fail -> reconcile -> retry
  - Browser:   reserve -> abort -> retry, reserve -> fail -> reconcile
  - Cross-domain: browser and connector entries are isolated in the same ledger
  - WAL recovery: reconciling_started state is recovered on next access
"""

import tempfile
import time
import unittest
from pathlib import Path

from guardian_agent.browser_operator import (
    _browser_ledger_key,
    abort_browser_preflight,
    complete_browser_operation,
    fail_browser_operation,
    reconcile_browser_unknown,
    reserve_browser_operation,
)
from guardian_agent.connectors import (
    IdempotencyLedger,
    complete_connector_operation,
    fail_connector_operation,
    reconcile_connector_outcome,
    reserve_connector_operation,
)
from guardian_agent.core import GuardianError, initialize
from guardian_agent.policy import approve_action_request, request_action_approval


def _setup_approval(brain, action: str, target: str, account_id: str = "smoke-test", connector_scope: str = "browser") -> str:
    """Create and approve a real approval, returning its request ID."""
    req = request_action_approval(
        brain, action, target, "smoke-test-reason",
        account_id=account_id, connector_scope=connector_scope,
    )
    rid = req["id"]
    approve_action_request(brain, rid)
    return rid


def _minimal_evidence(
    connector: str = "browser",
    action: str = "navigate",
    idempotency_key: str = "smoke-key",
    approval_id: str = "dummy",
) -> dict:
    return {
        "account_id": "smoke-test",
        "connector": connector,
        "action": action,
        "idempotency_key": idempotency_key,
        "approval_id": approval_id,
        "operator_identity": "smoke-tester",
        "evidence_type": "automated_smoke",
        "evidence_reference": "https://example.com/smoke",
        "timestamp": time.time(),
        "resolution_reason": "Smoke test evidence",
    }


class SmokeTests(unittest.TestCase):
    """End-to-end smoke test for browser+connector ledger features."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Smoke Test", "End-to-end smoke test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    # ------------------------------------------------------------------
    # Connector: success lifecycle
    # ------------------------------------------------------------------

    def test_connector_success_lifecycle(self) -> None:
        """Connector: reserve -> complete -> idempotent re-reserve."""
        # Reserve
        res = reserve_connector_operation(self.brain, "canva", "create", "smoke-conn-success", ttl_seconds=600)
        self.assertFalse(res["already_completed"])
        token = res["owner_token"]
        self.assertTrue(token.startswith("otok-"))

        comp_key = "canva:create:smoke-conn-success"
        ledger = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger[comp_key]["status"], "reserved")

        # Complete
        complete_connector_operation(
            self.brain, "canva", "create", "smoke-conn-success",
            {"status": "completed", "asset_id": "smoke-asset-001"}, owner_token=token,
        )
        ledger2 = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger2[comp_key]["status"], "completed")
        self.assertEqual(ledger2[comp_key]["receipt"]["asset_id"], "smoke-asset-001")

        # Re-reserve returns receipt (idempotent)
        res2 = reserve_connector_operation(self.brain, "canva", "create", "smoke-conn-success")
        self.assertTrue(res2["already_completed"])
        self.assertEqual(res2["receipt"]["asset_id"], "smoke-asset-001")

        # Ledger should have exactly 1 entry
        self.assertEqual(len(IdempotencyLedger.load(self.brain)), 1)

    # ------------------------------------------------------------------
    # Connector: abort_preflight -> retry lifecycle
    # ------------------------------------------------------------------

    def test_connector_abort_preflight_then_retry(self) -> None:
        """Connector: reserve -> abort_preflight -> retry -> complete."""
        # Reserve
        res = reserve_connector_operation(self.brain, "adobe", "export", "smoke-abort-001", ttl_seconds=600)
        token1 = res["owner_token"]

        # Abort preflight (simulates preflight validation failure)
        IdempotencyLedger.abort_preflight(
            self.brain, "adobe:export:smoke-abort-001", "Selector not found", owner_token=token1,
        )

        comp_key = "adobe:export:smoke-abort-001"
        ledger = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger[comp_key]["status"], "preflight_aborted")
        self.assertIn("Selector not found", ledger[comp_key]["preflight_reason"])

        # Retry: re-reserve succeeds with new token
        res2 = reserve_connector_operation(self.brain, "adobe", "export", "smoke-abort-001", ttl_seconds=600)
        self.assertFalse(res2["already_completed"])
        self.assertTrue(res2.get("re_reserved"))
        self.assertNotEqual(res2["owner_token"], token1)

        # Complete the retry
        complete_connector_operation(
            self.brain, "adobe", "export", "smoke-abort-001",
            {"status": "completed", "file": "export.pdf"}, owner_token=res2["owner_token"],
        )
        ledger2 = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger2[comp_key]["status"], "completed")

    # ------------------------------------------------------------------
    # Connector: crash recovery lifecycle
    # ------------------------------------------------------------------

    def test_connector_crash_recovery_full_lifecycle(self) -> None:
        """Connector: reserve -> fail -> reconcile -> retry -> complete."""
        comp_key = "canva:create:smoke-crash-001"

        # Reserve
        res = reserve_connector_operation(self.brain, "canva", "create", "smoke-crash-001", ttl_seconds=600)
        token = res["owner_token"]

        # Simulate crash -> mark unknown
        fail_connector_operation(self.brain, "canva", "create", "smoke-crash-001", "API timeout", owner_token=token)
        ledger = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger[comp_key]["status"], "unknown_outcome")

        # Retry blocked
        with self.assertRaises(GuardianError) as cm:
            reserve_connector_operation(self.brain, "canva", "create", "smoke-crash-001")
        self.assertIn("unknown_outcome", str(cm.exception))

        # Create real approval and reconcile as cancelled
        rid = _setup_approval(self.brain, "create", comp_key, connector_scope="canva")
        evidence = _minimal_evidence(
            connector="canva", action="create",
            idempotency_key=comp_key, approval_id=rid,
        )
        rec_res = reconcile_connector_outcome(
            self.brain, "canva", "create", "smoke-crash-001",
            resolution="cancelled", resolution_reason="Confirmed no asset created",
            evidence=evidence, approval_id=rid,
        )
        self.assertTrue(rec_res["reconciled"])
        self.assertEqual(rec_res["status"], "reconciled_cancelled")
        self.assertTrue(rec_res["approval_consumed"])

        # Retry succeeds after reconciliation
        res2 = reserve_connector_operation(self.brain, "canva", "create", "smoke-crash-001", ttl_seconds=600)
        self.assertFalse(res2["already_completed"])
        self.assertTrue(res2.get("re_reserved"))

        # Complete the retry
        complete_connector_operation(
            self.brain, "canva", "create", "smoke-crash-001",
            {"status": "completed", "asset_id": "smoke-retry-001"}, owner_token=res2["owner_token"],
        )
        ledger2 = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger2[comp_key]["status"], "completed")

    # ------------------------------------------------------------------
    # Connector: WAL crash recovery
    # ------------------------------------------------------------------

    def test_connector_wal_recovery_after_approval_consumed(self) -> None:
        """Connector: inject reconciling_started with consumed approval -> reserve recovers."""
        comp_key = "canva:publish:smoke-wal-001"

        # Reserve and mark unknown
        res = reserve_connector_operation(self.brain, "canva", "publish", "smoke-wal-001")
        fail_connector_operation(self.brain, "canva", "publish", "smoke-wal-001", "Timeout", owner_token=res["owner_token"])

        # Manually consume the approval (simulating crash after Phase 2, before Phase 3)
        rid = _setup_approval(self.brain, "publish", comp_key, connector_scope="canva")
        from guardian_agent.policy import consume_action_approval
        consumed = consume_action_approval(
            self.brain, request_id=rid, action="publish", target=comp_key,
            after_evidence="WAL smoke test",
            account_id="smoke-test", connector_scope="canva",
        )
        self.assertEqual(consumed["status"], "consumed")

        # Manually inject reconciling_started WAL entry
        ledger = IdempotencyLedger.load(self.brain)
        ledger[comp_key] = {
            "status": "reconciling_started",
            "reconciling_resolution": "cancelled",
            "reconciling_approval_id": rid,
            "reconciling_evidence": _minimal_evidence(
                connector="canva", action="publish",
                idempotency_key=comp_key, approval_id=rid,
            ),
            "reconciling_started_at": time.time(),
        }
        IdempotencyLedger._save_under_lock(self.brain, ledger)

        # Trigger recovery via reserve() -> should recover and re-reserve
        res2 = reserve_connector_operation(self.brain, "canva", "publish", "smoke-wal-001")
        self.assertTrue(res2.get("re_reserved"))

        # Complete the recovered operation
        complete_connector_operation(
            self.brain, "canva", "publish", "smoke-wal-001",
            {"status": "completed"}, owner_token=res2["owner_token"],
        )
        ledger2 = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger2[comp_key]["status"], "completed")

    # ------------------------------------------------------------------
    # Browser: abort_preflight -> retry lifecycle
    # ------------------------------------------------------------------

    def test_browser_abort_preflight_then_retry(self) -> None:
        """Browser: reserve -> abort_preflight -> retry -> complete."""
        url = "https://example.com/page"
        action = "click_readonly"

        # Reserve
        res = reserve_browser_operation(self.brain, "acc-br", action, url, ttl_seconds=600)
        token1 = res["owner_token"]

        # Abort preflight
        abort_browser_preflight(
            self.brain, "acc-br", action, url,
            preflight_reason="Selector not visible: #submit-btn", owner_token=token1,
        )

        br_key = _browser_ledger_key("acc-br", action, url)
        ledger = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger[br_key]["status"], "preflight_aborted")
        self.assertIn("Selector not visible", ledger[br_key]["preflight_reason"])

        # Retry with new token
        res2 = reserve_browser_operation(self.brain, "acc-br", action, url, ttl_seconds=600)
        self.assertFalse(res2["already_completed"])
        self.assertTrue(res2.get("re_reserved"))
        self.assertNotEqual(res2["owner_token"], token1)

        # Complete the retry
        complete_browser_operation(
            self.brain, "acc-br", action, url,
            {"status": "completed", "action": action, "url": url}, owner_token=res2["owner_token"],
        )
        ledger2 = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger2[br_key]["status"], "completed")

    # ------------------------------------------------------------------
    # Browser: crash recovery lifecycle
    # ------------------------------------------------------------------

    def test_browser_crash_recovery(self) -> None:
        """Browser: reserve -> fail -> reconcile -> retry."""
        url = "https://canva.com/design/doc3"
        action = "publish"

        # Reserve
        res = reserve_browser_operation(self.brain, "acc-br2", action, url, ttl_seconds=600)
        token = res["owner_token"]

        # Simulate crash
        fail_browser_operation(self.brain, "acc-br2", action, url, "Playwright disconnected", owner_token=token)

        br_key = _browser_ledger_key("acc-br2", action, url)
        ledger = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger[br_key]["status"], "unknown_outcome")

        # Retry blocked
        with self.assertRaises(GuardianError) as cm:
            reserve_browser_operation(self.brain, "acc-br2", action, url)
        self.assertIn("unknown_outcome", str(cm.exception))

        # Create real approval and reconcile as cancelled
        rid = _setup_approval(self.brain, action, br_key, connector_scope="browser")
        evidence = _minimal_evidence(
            connector="browser", action=action,
            idempotency_key=br_key, approval_id=rid,
        )
        rec_res = reconcile_browser_unknown(
            self.brain, "acc-br2", action, url,
            resolution="cancelled", resolution_reason="Confirmed publish did not go through",
            evidence=evidence, approval_id=rid,
        )
        self.assertTrue(rec_res["reconciled"])
        self.assertEqual(rec_res["status"], "reconciled_cancelled")

        # Retry after reconciliation
        res2 = reserve_browser_operation(self.brain, "acc-br2", action, url, ttl_seconds=600)
        self.assertFalse(res2["already_completed"])
        self.assertTrue(res2.get("re_reserved"))

        # Complete the retry
        complete_browser_operation(
            self.brain, "acc-br2", action, url,
            {"status": "completed", "action": action, "url": url}, owner_token=res2["owner_token"],
        )
        ledger2 = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger2[br_key]["status"], "completed")

    # ------------------------------------------------------------------
    # Cross-domain: browser and connector entries are isolated
    # ------------------------------------------------------------------

    def test_cross_domain_isolation(self) -> None:
        """Browser and connector entries have different key prefixes and don't interfere."""
        # Browser operation
        br_res = reserve_browser_operation(self.brain, "acc-isol", "navigate", "https://example.com", ttl_seconds=600)
        br_key = _browser_ledger_key("acc-isol", "navigate", "https://example.com")

        # Connector operation
        conn_res = reserve_connector_operation(self.brain, "canva", "create_asset", "smoke-isol-001", ttl_seconds=600)
        conn_key = "canva:create_asset:smoke-isol-001"

        # Keys are different
        self.assertNotEqual(br_key, conn_key)
        self.assertTrue(br_key.startswith("browser:"))
        self.assertTrue(conn_key.startswith("canva:"))

        # Both in the same ledger
        ledger = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger[br_key]["status"], "reserved")
        self.assertEqual(ledger[conn_key]["status"], "reserved")

        # Complete one, the other stays reserved
        complete_browser_operation(
            self.brain, "acc-isol", "navigate", "https://example.com",
            {"status": "completed"}, owner_token=br_res["owner_token"],
        )
        ledger2 = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger2[br_key]["status"], "completed")
        self.assertEqual(ledger2[conn_key]["status"], "reserved")

        # Complete the connector independently
        complete_connector_operation(
            self.brain, "canva", "create_asset", "smoke-isol-001",
            {"status": "completed"}, owner_token=conn_res["owner_token"],
        )
        ledger3 = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger3[br_key]["status"], "completed")
        self.assertEqual(ledger3[conn_key]["status"], "completed")

    # ------------------------------------------------------------------
    # Browser: wrong-owner-token enforcement on abort_preflight
    # ------------------------------------------------------------------

    def test_browser_wrong_token_rejected_on_abort(self) -> None:
        """Browser: abort_preflight with wrong owner token is rejected (fail-closed)."""
        res = reserve_browser_operation(self.brain, "acc-tok", "fill", "https://example.com/form", ttl_seconds=600)
        with self.assertRaises(GuardianError) as cm:
            abort_browser_preflight(
                self.brain, "acc-tok", "fill", "https://example.com/form",
                preflight_reason="Simulated failure", owner_token="wrong_token",
            )
        self.assertIn("owner token mismatch", str(cm.exception).lower())

        # Verify still reserved (not aborted)
        ledger = IdempotencyLedger.load(self.brain)
        br_key = _browser_ledger_key("acc-tok", "fill", "https://example.com/form")
        self.assertEqual(ledger[br_key]["status"], "reserved")

    # ------------------------------------------------------------------
    # Browser: abort_preflight does NOT create unknown_outcome
    # ------------------------------------------------------------------

    def test_browser_abort_does_not_create_unknown(self) -> None:
        """Browser: abort_preflight never creates unknown_outcome entry."""
        res = reserve_browser_operation(self.brain, "acc-unk", "screenshot", "https://example.com/page", ttl_seconds=600)
        abort_browser_preflight(
            self.brain, "acc-unk", "screenshot", "https://example.com/page",
            preflight_reason="Element not interactive", owner_token=res["owner_token"],
        )

        br_key = _browser_ledger_key("acc-unk", "screenshot", "https://example.com/page")
        ledger = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger[br_key]["status"], "preflight_aborted")
        self.assertNotEqual(ledger[br_key]["status"], "unknown_outcome")

        # list_browser_unknown_outcomes should be empty
        from guardian_agent.browser_operator import list_browser_unknown_outcomes
        unknowns = list_browser_unknown_outcomes(self.brain)
        self.assertEqual(len(unknowns), 0)

    # ------------------------------------------------------------------
    # Connector: complete() rejects preflight_aborted state
    # ------------------------------------------------------------------

    def test_connector_complete_rejects_preflight_aborted(self) -> None:
        """Connector: complete() fails-closed on preflight_aborted entry."""
        res = reserve_connector_operation(self.brain, "lovable", "create_app", "smoke-reject-001", ttl_seconds=600)
        IdempotencyLedger.abort_preflight(
            self.brain, "lovable:create_app:smoke-reject-001", "Preflight validation failed", owner_token=res["owner_token"],
        )
        with self.assertRaises(GuardianError) as cm:
            complete_connector_operation(
                self.brain, "lovable", "create_app", "smoke-reject-001",
                {"status": "should fail"}, owner_token=res["owner_token"],
            )
        self.assertIn("preflight-aborted", str(cm.exception).lower())

    # ------------------------------------------------------------------
    # Connector: mark_unknown() rejects reconciling_started state
    # ------------------------------------------------------------------

    def test_connector_mark_unknown_rejects_reconciling_started(self) -> None:
        """Connector: mark_unknown() recovers reconciling_started entry then rejects.

        The recovery runs first (rolls back to unknown_outcome since the approval
        doesn't exist), then the state check sees unknown_outcome and rejects.
        """
        comp_key = "canva:update:smoke-recon-001"
        res = reserve_connector_operation(self.brain, "canva", "update", "smoke-recon-001")
        fail_connector_operation(self.brain, "canva", "update", "smoke-recon-001", "Error", owner_token=res["owner_token"])

        # Manually set reconciling_started (non-existent approval so recovery rolls back)
        ledger = IdempotencyLedger.load(self.brain)
        ledger[comp_key] = {"status": "reconciling_started", "reconciling_approval_id": "dummy"}
        IdempotencyLedger._save_under_lock(self.brain, ledger)

        with self.assertRaises(GuardianError) as cm:
            fail_connector_operation(self.brain, "canva", "update", "smoke-recon-001", "Should fail", owner_token=res["owner_token"])
        # Recovery runs first -> rolls back to unknown_outcome -> mark_unknown rejects
        # as already unknown_outcome. The key insight: recovery IS triggered through
        # mark_unknown(), confirming wider WAL coverage.
        self.assertIn("already in 'unknown_outcome'", str(cm.exception).lower())


if __name__ == "__main__":
    unittest.main()
