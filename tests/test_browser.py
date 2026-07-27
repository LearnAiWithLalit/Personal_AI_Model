"""Unit tests for Computer Operator Browser Controller (browser_operator.py)."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from guardian_agent.accounts import register_account
from guardian_agent.browser_operator import (
    _browser_ledger_key,
    abort_browser_preflight,
    cancel_takeover,
    check_playwright_available,
    complete_browser_operation,
    execute_browser_action,
    fail_browser_operation,
    get_takeover_status,
    inspect_web_page,
    list_browser_unknown_outcomes,
    pause_for_takeover,
    reconcile_browser_unknown,
    reserve_browser_operation,
    resume_takeover,
)
from guardian_agent.connectors import IdempotencyLedger
from guardian_agent.core import GuardianError, initialize
from guardian_agent.policy import approve_action_request, request_action_approval


def _setup_browser_approval(brain, action: str, target: str, account_id: str = None) -> str:
    """Create and approve a real approval for browser reconciliation tests.

    If account_id is provided, the approval is scoped to that account;
    if None, the approval has no account scope, allowing it to be used
    with any account_id in the evidence (for test flexibility).
    """
    kwargs = {}
    if account_id is not None:
        kwargs["account_id"] = account_id
    req = request_action_approval(
        brain, action, target, "browser-recon-test",
        connector_scope="browser", **kwargs,
    )
    rid = req["id"]
    approve_action_request(brain, rid)
    return rid


class BrowserOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Browser Demo", "Browser operator test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    # ---- Existing tests ----

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

    # ---- Browser ledger bridge tests ----

    def test_browser_ledger_key_format(self) -> None:
        """Verify the ledger key format isolates browser operations."""
        key = _browser_ledger_key("acc-001", "navigate", "https://canva.com/design/123")
        self.assertTrue(key.startswith("browser:"))
        self.assertIn("acc-001", key)
        self.assertIn("navigate", key)

    def test_browser_ledger_key_different_urls_differ(self) -> None:
        """Verify different URLs produce different ledger keys."""
        k1 = _browser_ledger_key("acc-001", "click_readonly", "https://site1.com/page")
        k2 = _browser_ledger_key("acc-001", "click_readonly", "https://site2.com/page")
        self.assertNotEqual(k1, k2)

    def test_browser_ledger_key_different_actions_differ(self) -> None:
        """Verify different actions produce different ledger keys."""
        k1 = _browser_ledger_key("acc-001", "navigate", "https://canva.com")
        k2 = _browser_ledger_key("acc-001", "fill", "https://canva.com")
        self.assertNotEqual(k1, k2)

    def test_reserve_browser_operation_success(self) -> None:
        """Verify a fresh browser operation can be reserved in the ledger."""
        res = reserve_browser_operation(
            self.brain, "acc-001", "navigate", "https://canva.com", ttl_seconds=300
        )
        self.assertFalse(res["already_completed"])
        self.assertTrue(res["owner_token"].startswith("otok-"))

    def test_reserve_browser_operation_twice_same_key_rejected(self) -> None:
        """Verify reserving the same key while another reservation is active is rejected."""
        res1 = reserve_browser_operation(
            self.brain, "acc-001", "fill", "https://canva.com", ttl_seconds=300
        )
        self.assertTrue(res1["owner_token"].startswith("otok-"))

        # Re-reserve without an owner token (e.g. from a different process) must be rejected
        with self.assertRaises(GuardianError) as cm:
            reserve_browser_operation(
                self.brain, "acc-001", "fill", "https://canva.com", ttl_seconds=300
            )
        self.assertIn("locked", str(cm.exception).lower())

    def test_complete_browser_operation(self) -> None:
        """Verify a browser operation can be completed successfully."""
        res = reserve_browser_operation(
            self.brain, "acc-002", "click_readonly", "https://example.com", ttl_seconds=300
        )
        token = res["owner_token"]

        receipt = {"status": "completed", "action": "click_readonly", "url": "https://example.com"}
        complete_browser_operation(self.brain, "acc-002", "click_readonly", "https://example.com", receipt, owner_token=token)

        # Verify ledger entry is now completed
        key = _browser_ledger_key("acc-002", "click_readonly", "https://example.com")
        ledger = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger[key]["status"], "completed")

    def test_complete_browser_operation_with_wrong_token_rejected(self) -> None:
        """Verify completing with wrong owner token is rejected."""
        res = reserve_browser_operation(
            self.brain, "acc-003", "fill", "https://example.com", ttl_seconds=300
        )
        with self.assertRaises(GuardianError) as cm:
            complete_browser_operation(
                self.brain, "acc-003", "fill", "https://example.com",
                {}, owner_token="wrong_token"
            )
        self.assertIn("owner token mismatch", str(cm.exception))

    def test_fail_browser_operation_creates_unknown_outcome(self) -> None:
        """Verify failing a browser operation creates an unknown_outcome entry."""
        res = reserve_browser_operation(
            self.brain, "acc-004", "publish", "https://canva.com/design/abc", ttl_seconds=300
        )
        token = res["owner_token"]

        fail_browser_operation(
            self.brain, "acc-004", "publish", "https://canva.com/design/abc",
            "Playwright crashed", owner_token=token,
        )

        key = _browser_ledger_key("acc-004", "publish", "https://canva.com/design/abc")
        ledger = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger[key]["status"], "unknown_outcome")
        self.assertIn("Playwright crashed", ledger[key]["error_reason"])

    def test_fail_browser_operation_with_wrong_token_rejected(self) -> None:
        """Verify marking unknown with wrong owner token is rejected."""
        res = reserve_browser_operation(
            self.brain, "acc-005", "delete", "https://example.com", ttl_seconds=300
        )
        with self.assertRaises(GuardianError) as cm:
            fail_browser_operation(
                self.brain, "acc-005", "delete", "https://example.com",
                "Error", owner_token="wrong_token",
            )
        self.assertIn("owner token mismatch", str(cm.exception))

    # ---- Browser unknown-outcome listing tests ----

    def test_list_browser_unknown_outcomes_empty(self) -> None:
        """Verify listing unknown outcomes returns empty when none exist."""
        results = list_browser_unknown_outcomes(self.brain)
        self.assertEqual(results, [])

    def test_list_browser_unknown_outcomes_finds_entries(self) -> None:
        """Verify listing finds browser entries in unknown_outcome state."""
        # Create a browser unknown outcome
        res = reserve_browser_operation(
            self.brain, "acc-010", "publish", "https://canva.com/doc1", ttl_seconds=300
        )
        fail_browser_operation(
            self.brain, "acc-010", "publish", "https://canva.com/doc1",
            "Network timeout", owner_token=res["owner_token"],
        )

        # Create a non-browser entry (connector) that should NOT appear
        from guardian_agent.connectors import reserve_connector_operation, fail_connector_operation
        cres = reserve_connector_operation(self.brain, "canva", "create_asset", "idem-unknown-001")
        fail_connector_operation(
            self.brain, "canva", "create_asset", "idem-unknown-001",
            "API error", owner_token=cres["owner_token"],
        )

        results = list_browser_unknown_outcomes(self.brain)
        self.assertEqual(len(results), 1)
        self.assertIn("composite_key", results[0])
        self.assertIn("acc-010", results[0]["composite_key"])
        self.assertEqual(results[0]["status"], "unknown_outcome")

    def test_list_browser_unknown_outcomes_filtered_by_account(self) -> None:
        """Verify account_id filtering works."""
        # Create two browser unknown outcomes for different accounts
        r1 = reserve_browser_operation(self.brain, "acc-011", "submit", "https://site1.com", ttl_seconds=300)
        fail_browser_operation(self.brain, "acc-011", "submit", "https://site1.com", "Err", owner_token=r1["owner_token"])

        r2 = reserve_browser_operation(self.brain, "acc-012", "submit", "https://site2.com", ttl_seconds=300)
        fail_browser_operation(self.brain, "acc-012", "submit", "https://site2.com", "Err", owner_token=r2["owner_token"])

        results_all = list_browser_unknown_outcomes(self.brain)
        self.assertEqual(len(results_all), 2)

        results_acc11 = list_browser_unknown_outcomes(self.brain, account_id="acc-011")
        self.assertEqual(len(results_acc11), 1)
        self.assertIn("acc-011", results_acc11[0]["composite_key"])

    # ---- Browser unknown-outcome reconciliation tests (with real approvals) ----

    def test_reconcile_browser_unknown_cancelled(self) -> None:
        """Verify a browser unknown_outcome can be reconciled as cancelled."""
        # Create unknown outcome
        res = reserve_browser_operation(
            self.brain, "acc-020", "publish", "https://canva.com/doc1", ttl_seconds=300
        )
        token = res["owner_token"]
        fail_browser_operation(
            self.brain, "acc-020", "publish", "https://canva.com/doc1",
            "Timeout", owner_token=token,
        )

        # Create real approval
        comp_key = _browser_ledger_key("acc-020", "publish", "https://canva.com/doc1")
        rid = _setup_browser_approval(self.brain, "publish", comp_key)

        # Reconcile as cancelled with evidence
        evidence = {
            "account_id": "acc-020",
            "connector": "browser",
            "action": "publish",
            "idempotency_key": comp_key,
            "approval_id": rid,
            "operator_identity": "human-reviewer",
            "evidence_type": "visual_inspection",
            "evidence_reference": "https://canva.com/audit/review-001",
            "timestamp": time.time(),
            "resolution_reason": "Human verified nothing was published",
        }
        rec_res = reconcile_browser_unknown(
            self.brain, "acc-020", "publish", "https://canva.com/doc1",
            resolution="cancelled", resolution_reason="Human verified nothing was published",
            evidence=evidence, approval_id=rid,
        )
        self.assertTrue(rec_res["reconciled"])
        self.assertEqual(rec_res["status"], "reconciled_cancelled")

        # After cancellation, new reservation is allowed
        res2 = reserve_browser_operation(
            self.brain, "acc-020", "publish", "https://canva.com/doc1", ttl_seconds=300
        )
        self.assertFalse(res2["already_completed"])
        self.assertTrue(res2.get("re_reserved"))

    def test_reconcile_browser_unknown_completed(self) -> None:
        """Verify a browser unknown_outcome can be reconciled as completed."""
        res = reserve_browser_operation(
            self.brain, "acc-021", "fill", "https://example.com/form", ttl_seconds=300
        )
        token = res["owner_token"]
        fail_browser_operation(
            self.brain, "acc-021", "fill", "https://example.com/form",
            "Unknown error", owner_token=token,
        )

        comp_key = _browser_ledger_key("acc-021", "fill", "https://example.com/form")
        rid = _setup_browser_approval(self.brain, "fill", comp_key)

        evidence = {
            "account_id": "acc-021",
            "connector": "browser",
            "action": "fill",
            "idempotency_key": comp_key,
            "approval_id": rid,
            "operator_identity": "admin",
            "evidence_type": "browser_check",
            "evidence_reference": "https://example.com/form/verify",
            "timestamp": time.time(),
            "resolution_reason": "Verified form was submitted successfully",
        }
        rec_res = reconcile_browser_unknown(
            self.brain, "acc-021", "fill", "https://example.com/form",
            resolution="completed", resolution_reason="Verified form was submitted successfully",
            evidence=evidence, approval_id=rid,
        )
        self.assertTrue(rec_res["reconciled"])
        self.assertEqual(rec_res["status"], "reconciled_completed")

        # After completed reconciliation, re-reservation returns receipt
        res2 = reserve_browser_operation(
            self.brain, "acc-021", "fill", "https://example.com/form", ttl_seconds=300
        )
        self.assertTrue(res2["already_completed"])

    def test_reconcile_browser_unknown_without_evidence_rejected(self) -> None:
        """Verify reconciliation without evidence is rejected."""
        res = reserve_browser_operation(
            self.brain, "acc-022", "screenshot", "https://example.com", ttl_seconds=300
        )
        token = res["owner_token"]
        fail_browser_operation(
            self.brain, "acc-022", "screenshot", "https://example.com",
            "Crash", owner_token=token,
        )

        with self.assertRaises(GuardianError) as cm:
            reconcile_browser_unknown(
                self.brain, "acc-022", "screenshot", "https://example.com",
                resolution="cancelled", resolution_reason="Test",
                evidence={}, approval_id="approval-br-003",
            )
        self.assertIn("evidence", str(cm.exception).lower())

    # ---- Browser preflight abort tests ----

    def test_abort_browser_preflight_releases_reservation(self) -> None:
        """Verify abort_browser_preflight transitions reserved → preflight_aborted."""
        res = reserve_browser_operation(
            self.brain, "acc-040", "click_readonly", "https://example.com/button", ttl_seconds=300
        )
        token = res["owner_token"]

        abort_browser_preflight(
            self.brain, "acc-040", "click_readonly", "https://example.com/button",
            preflight_reason="Selector not visible", owner_token=token,
        )

        key = _browser_ledger_key("acc-040", "click_readonly", "https://example.com/button")
        ledger = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger[key]["status"], "preflight_aborted")
        self.assertIn("Selector not visible", ledger[key]["preflight_reason"])

    def test_abort_browser_preflight_no_unknown_outcome(self) -> None:
        """Verify abort does NOT create an unknown_outcome entry (no side effect occurred)."""
        res = reserve_browser_operation(
            self.brain, "acc-041", "fill", "https://example.com/form", ttl_seconds=300
        )
        token = res["owner_token"]

        abort_browser_preflight(
            self.brain, "acc-041", "fill", "https://example.com/form",
            preflight_reason="Form field disabled", owner_token=token,
        )

        # Verify NOT unknown_outcome
        results = list_browser_unknown_outcomes(self.brain)
        unknown_keys = [r["composite_key"] for r in results]
        key = _browser_ledger_key("acc-041", "fill", "https://example.com/form")
        self.assertNotIn(key, unknown_keys)

    def test_abort_browser_preflight_wrong_token_rejected(self) -> None:
        """Verify abort with wrong owner token is rejected (fail-closed)."""
        res = reserve_browser_operation(
            self.brain, "acc-042", "submit", "https://example.com/submit", ttl_seconds=300
        )
        with self.assertRaises(GuardianError) as cm:
            abort_browser_preflight(
                self.brain, "acc-042", "submit", "https://example.com/submit",
                preflight_reason="Preflight failed", owner_token="wrong_token",
            )
        self.assertIn("owner token mismatch", str(cm.exception).lower())

    def test_abort_browser_preflight_then_retry_receives_new_token(self) -> None:
        """Verify that after abort, a fresh reservation gets a new owner token."""
        res = reserve_browser_operation(
            self.brain, "acc-043", "navigate", "https://example.com", ttl_seconds=300
        )
        token1 = res["owner_token"]

        abort_browser_preflight(
            self.brain, "acc-043", "navigate", "https://example.com",
            preflight_reason="URL validation failed", owner_token=token1,
        )

        # Re-reserve must succeed with a new token
        res2 = reserve_browser_operation(
            self.brain, "acc-043", "navigate", "https://example.com", ttl_seconds=300
        )
        self.assertFalse(res2["already_completed"])
        self.assertTrue(res2["owner_token"].startswith("otok-"))
        self.assertNotEqual(res2["owner_token"], token1)

    def test_execute_browser_action_fails_closed_on_abort_write_failure(self) -> None:
        """Verify execute_browser_action raises when abort_browser_preflight ledger write fails.

        Patches check_playwright_available to bypass the playwright availability gate
        and abort_browser_preflight to simulate a ledger write failure.
        The ImportError from the missing playwright (inside _run_action) triggers
        the preflight-failure handler, which calls abort_browser_preflight.
        Since abort_browser_preflight is mocked to raise, the error must propagate
        (fail-closed) — not be silently swallowed.

        Uses https://example.com (a valid HTTPS domain) so URL validation passes
        before the playwright import fails inside _run_action().
        """
        with (
            patch(
                "guardian_agent.browser_operator.check_playwright_available",
                return_value=True,
            ),
            patch(
                "guardian_agent.browser_operator.abort_browser_preflight",
                side_effect=GuardianError("Simulated ledger write failure in abort_preflight"),
            ),
        ):
            with self.assertRaises(GuardianError) as cm:
                execute_browser_action(
                    self.brain,
                    url="https://example.com",
                    action="click_readonly",
                    selector="#nonexistent-button",
                    allow_offline=True,
                )
        # The error must mention the ledger write failure, proving it propagated
        self.assertIn("ledger write failure", str(cm.exception).lower())

    def test_abort_browser_preflight_immutable_states_rejected(self) -> None:
        """Verify abort on completed or already-aborted entries is rejected."""
        # Complete first
        res = reserve_browser_operation(
            self.brain, "acc-044", "click_readonly", "https://example.com/done", ttl_seconds=300
        )
        token = res["owner_token"]
        complete_browser_operation(
            self.brain, "acc-044", "click_readonly", "https://example.com/done",
            {"status": "completed"}, owner_token=token,
        )

        with self.assertRaises(GuardianError) as cm:
            abort_browser_preflight(
                self.brain, "acc-044", "click_readonly", "https://example.com/done",
                preflight_reason="Can't abort completed", owner_token=token,
            )
        self.assertIn("immutable", str(cm.exception).lower())

    def test_reconcile_browser_unknown_without_approval_rejected(self) -> None:
        """Verify reconciliation without approval_id is rejected."""
        res = reserve_browser_operation(
            self.brain, "acc-023", "navigate", "https://example.com", ttl_seconds=300
        )
        token = res["owner_token"]
        fail_browser_operation(
            self.brain, "acc-023", "navigate", "https://example.com",
            "Error", owner_token=token,
        )

        evidence = {
            "account_id": "acc-023",
            "connector": "browser",
            "action": "navigate",
            "idempotency_key": _browser_ledger_key("acc-023", "navigate", "https://example.com"),
            "approval_id": "",
            "operator_identity": "admin",
            "evidence_type": "manual",
            "evidence_reference": "https://example.com/check",
            "timestamp": time.time(),
            "resolution_reason": "Test",
        }
        with self.assertRaises(GuardianError) as cm:
            reconcile_browser_unknown(
                self.brain, "acc-023", "navigate", "https://example.com",
                resolution="cancelled", resolution_reason="Test",
                evidence=evidence, approval_id="",
            )
        self.assertIn("approval_id", str(cm.exception).lower())

    # ---- Full lifecycle: reserve → complete (simulated execution) ----

    def test_browser_ledger_full_lifecycle_success(self) -> None:
        """Verify the full browser ledger lifecycle: reserve → complete."""
        res = reserve_browser_operation(
            self.brain, "acc-030", "click_readonly", "https://example.com/button", ttl_seconds=300
        )
        token = res["owner_token"]

        receipt = {
            "status": "completed",
            "action": "click_readonly",
            "url": "https://example.com/button",
            "title": "Example Page",
        }
        complete_browser_operation(
            self.brain, "acc-030", "click_readonly", "https://example.com/button",
            receipt, owner_token=token,
        )

        # Verify completed
        key = _browser_ledger_key("acc-030", "click_readonly", "https://example.com/button")
        ledger = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger[key]["status"], "completed")
        self.assertEqual(ledger[key]["receipt"]["title"], "Example Page")

    def test_browser_ledger_full_lifecycle_failure(self) -> None:
        """Verify the full browser ledger lifecycle: reserve → fail → reconcile → retry."""
        # Step 1: Reserve
        res = reserve_browser_operation(
            self.brain, "acc-031", "publish", "https://canva.com/doc2", ttl_seconds=300
        )
        token = res["owner_token"]

        # Step 2: Fail (simulate crash)
        fail_browser_operation(
            self.brain, "acc-031", "publish", "https://canva.com/doc2",
            "Playwright disconnected", owner_token=token,
        )

        # Step 3: Verify unknown_outcome
        key = _browser_ledger_key("acc-031", "publish", "https://canva.com/doc2")
        ledger = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger[key]["status"], "unknown_outcome")

        # Step 4: Create real approval and reconcile as cancelled
        rid = _setup_browser_approval(self.brain, "publish", key)
        evidence = {
            "account_id": "acc-031",
            "connector": "browser",
            "action": "publish",
            "idempotency_key": key,
            "approval_id": rid,
            "operator_identity": "reviewer",
            "evidence_type": "visual_inspection",
            "evidence_reference": "https://canva.com/audit/doc2-check",
            "timestamp": time.time(),
            "resolution_reason": "Confirmed publish did not go through",
        }
        rec_res = reconcile_browser_unknown(
            self.brain, "acc-031", "publish", "https://canva.com/doc2",
            resolution="cancelled", resolution_reason="Confirmed publish did not go through",
            evidence=evidence, approval_id=rid,
        )
        self.assertTrue(rec_res["reconciled"])

        # Step 5: Retry succeeds
        res2 = reserve_browser_operation(
            self.brain, "acc-031", "publish", "https://canva.com/doc2", ttl_seconds=300
        )
        self.assertFalse(res2["already_completed"])
        self.assertTrue(res2.get("re_reserved"))

        # Step 6: Complete the retry
        receipt2 = {"status": "completed", "action": "publish", "url": "https://canva.com/doc2"}
        complete_browser_operation(
            self.brain, "acc-031", "publish", "https://canva.com/doc2",
            receipt2, owner_token=res2["owner_token"],
        )

        # Step 7: Verify terminal state
        ledger2 = IdempotencyLedger.load(self.brain)
        self.assertEqual(ledger2[key]["status"], "completed")


# =====================================================================
# Priority 2 — Browser Reliability Function Tests
# =====================================================================


class BrowserReliabilityTests(unittest.TestCase):
    """Unit tests for the browser reliability helper functions.

    These functions (_check_overlay_blocking, _wait_for_page_settled,
    _check_element_stable, _create_submission_fingerprint, and
    _reconcile_submission_state) operate on page objects or plain dicts.
    Since Playwright is not available in the test environment, we use
    mock page objects via MagicMock when a Playwright page is required.
    """

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Browser Demo", "Browser reliability test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    # -------------------------------------------------------------------
    # _check_overlay_blocking tests
    # -------------------------------------------------------------------

    def test_check_overlay_blocking_detects_overlay(self) -> None:
        """Verify overlay detection identifies a blocking element."""
        from unittest.mock import MagicMock
        from guardian_agent.browser_operator import _check_overlay_blocking

        mock_page = MagicMock()
        # Simulate an overlay covering the target element
        mock_page.evaluate.return_value = [
            {
                "type": "overlay",
                "tag": "div",
                "id": "cookie-banner",
                "class": "banner",
                "text": "Accept cookies",
                "description": "Covered by <div>#cookie-banner.banner",
            }
        ]

        result = _check_overlay_blocking(mock_page, "#submit-button")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "overlay")
        self.assertIn("cookie-banner", str(result))
        mock_page.evaluate.assert_called_once()

    def test_check_overlay_blocking_no_overlay(self) -> None:
        """Verify no overlay is reported when element is unobstructed."""
        from unittest.mock import MagicMock
        from guardian_agent.browser_operator import _check_overlay_blocking

        mock_page = MagicMock()
        mock_page.evaluate.return_value = []

        result = _check_overlay_blocking(mock_page, "#visible-button")
        self.assertEqual(result, [])

    def test_check_overlay_blocking_element_missing(self) -> None:
        """Verify a missing element is reported as such, not as an overlay."""
        from unittest.mock import MagicMock
        from guardian_agent.browser_operator import _check_overlay_blocking

        mock_page = MagicMock()
        mock_page.evaluate.return_value = [
            {"type": "missing", "description": "Element not found in DOM"}
        ]

        result = _check_overlay_blocking(mock_page, "#nonexistent")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "missing")

    def test_check_overlay_blocking_js_exception_returns_empty(self) -> None:
        """Verify a JavaScript exception returns an empty list (graceful degradation)."""
        from unittest.mock import MagicMock
        from guardian_agent.browser_operator import _check_overlay_blocking

        mock_page = MagicMock()
        mock_page.evaluate.side_effect = Exception("JS error")

        result = _check_overlay_blocking(mock_page, "#some-element")
        self.assertEqual(result, [])

    # -------------------------------------------------------------------
    # _wait_for_page_settled tests
    # -------------------------------------------------------------------

    def test_wait_for_page_settled_success(self) -> None:
        """Verify page settlement detects a stable DOM."""
        from unittest.mock import MagicMock
        from guardian_agent.browser_operator import _wait_for_page_settled

        mock_page = MagicMock()
        # Simulate DOM stability check returning True
        mock_page.evaluate.return_value = True

        result = _wait_for_page_settled(mock_page, timeout=5_000)
        self.assertTrue(result["settled"])
        self.assertIn("network_idle_and_dom_stable", result["method"])
        self.assertIn("elapsed_ms", result)

    def test_wait_for_page_settled_unstable(self) -> None:
        """Verify an unsettled page returns settled=False."""
        from unittest.mock import MagicMock
        from guardian_agent.browser_operator import _wait_for_page_settled

        mock_page = MagicMock()
        # Simulate DOM never stabilizing
        mock_page.evaluate.return_value = False

        result = _wait_for_page_settled(mock_page, timeout=1_000)
        self.assertFalse(result["settled"])

    def test_wait_for_page_settled_exception_returns_graceful(self) -> None:
        """Verify an exception during settlement returns settled=False with error info."""
        from unittest.mock import MagicMock
        from guardian_agent.browser_operator import _wait_for_page_settled

        mock_page = MagicMock()
        mock_page.wait_for_load_state.side_effect = Exception("Navigation timeout")

        result = _wait_for_page_settled(mock_page, timeout=5_000)
        self.assertFalse(result["settled"])
        self.assertEqual(result["method"], "timeout_or_error")
        self.assertIn("Navigation timeout", result["error"])

    # -------------------------------------------------------------------
    # _check_element_stable tests
    # -------------------------------------------------------------------

    def test_check_element_stable_found_and_visible(self) -> None:
        """Verify a visible, enabled element is reported as stable."""
        from unittest.mock import MagicMock, PropertyMock
        from guardian_agent.browser_operator import _check_element_stable

        mock_page = MagicMock()
        mock_locator = MagicMock()
        # locator.count() returns 1 (element found)
        mock_locator.count.return_value = 1
        mock_locator.first = mock_locator
        mock_locator.is_disabled.return_value = False
        mock_page.locator.return_value = mock_locator

        result = _check_element_stable(mock_page, "#visible-btn")
        self.assertTrue(result["stable"])
        self.assertIn("visible and enabled", result["reason"])

    def test_check_element_stable_not_found(self) -> None:
        """Verify a missing element is reported as stale."""
        from unittest.mock import MagicMock
        from guardian_agent.browser_operator import _check_element_stable

        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.count.return_value = 0
        mock_page.locator.return_value = mock_locator

        result = _check_element_stable(mock_page, "#missing-element")
        self.assertFalse(result["stable"])
        self.assertTrue(result["stale"])
        self.assertIn("not found", result["reason"].lower())

    def test_check_element_stable_disabled(self) -> None:
        """Verify a disabled element is reported as unstable but not stale."""
        from unittest.mock import MagicMock, PropertyMock
        from guardian_agent.browser_operator import _check_element_stable

        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.count.return_value = 1
        mock_locator.first = mock_locator
        mock_locator.is_disabled.return_value = True
        mock_page.locator.return_value = mock_locator

        result = _check_element_stable(mock_page, "#disabled-input")
        self.assertFalse(result["stable"])
        self.assertFalse(result["stale"])
        self.assertIn("disabled", result["reason"].lower())

    def test_check_element_stable_exception_returns_stale(self) -> None:
        """Verify an exception during stability check is reported as stale."""
        from unittest.mock import MagicMock
        from guardian_agent.browser_operator import _check_element_stable

        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.count.side_effect = Exception("DOM error")
        mock_page.locator.return_value = mock_locator

        result = _check_element_stable(mock_page, "#broken")
        self.assertFalse(result["stable"])
        self.assertTrue(result["stale"])

    # -------------------------------------------------------------------
    # _create_submission_fingerprint tests
    # -------------------------------------------------------------------

    def test_create_submission_fingerprint_captures_success(self) -> None:
        """Verify a submission fingerprint captures success indicators."""
        from unittest.mock import MagicMock, PropertyMock
        from guardian_agent.browser_operator import _create_submission_fingerprint

        mock_page = MagicMock()
        type(mock_page).url = PropertyMock(return_value="https://example.com/success")
        mock_page.title.return_value = "Payment Successful"
        # Page body contains success keywords
        body_text = "Your payment has been submitted successfully. Thank you for your order!"
        mock_page.evaluate.return_value = body_text

        result = _create_submission_fingerprint(mock_page, "submit")

        self.assertEqual(result["action_type"], "submit")
        self.assertEqual(result["current_url"], "https://example.com/success")
        self.assertEqual(result["page_title"], "Payment Successful")
        self.assertTrue(result["has_success_indicator"])
        self.assertFalse(result["has_error_indicator"])
        self.assertIn("success", result["success_keywords"])
        self.assertIn("submitted", result["success_keywords"])
        self.assertEqual(result["version"], 1)

    def test_create_submission_fingerprint_captures_error(self) -> None:
        """Verify a submission fingerprint captures error indicators."""
        from unittest.mock import MagicMock, PropertyMock
        from guardian_agent.browser_operator import _create_submission_fingerprint

        mock_page = MagicMock()
        type(mock_page).url = PropertyMock(return_value="https://example.com/error")
        mock_page.title.return_value = "Error Page"
        body_text = "Something went wrong. The transaction was declined. Please try again."
        mock_page.evaluate.return_value = body_text

        result = _create_submission_fingerprint(mock_page, "publish")

        self.assertTrue(result["has_error_indicator"])
        self.assertFalse(result["has_success_indicator"])
        self.assertIn("declined", result["error_keywords"])
        self.assertIn("declined", result["error_keywords"])
        self.assertIn("try again", result["error_keywords"])

    def test_create_submission_fingerprint_handles_js_failure(self) -> None:
        """Verify fingerprint handles JS evaluation failure gracefully."""
        from unittest.mock import MagicMock, PropertyMock
        from guardian_agent.browser_operator import _create_submission_fingerprint

        mock_page = MagicMock()
        type(mock_page).url = PropertyMock(return_value="https://example.com/page")
        mock_page.title.return_value = "Test"
        mock_page.evaluate.side_effect = Exception("JS context destroyed")

        result = _create_submission_fingerprint(mock_page, "click_readonly")

        # Should still have basic fields even if JS fails
        self.assertEqual(result["action_type"], "click_readonly")
        self.assertEqual(result["current_url"], "https://example.com/page")
        self.assertFalse(result["has_success_indicator"])
        self.assertFalse(result["has_error_indicator"])
        self.assertEqual(result["visible_text_snippet"], "")

    # -------------------------------------------------------------------
    # _reconcile_submission_state tests (pure dict logic, no mocks needed)
    # -------------------------------------------------------------------

    def test_reconcile_submission_url_change_and_success(self) -> None:
        """URL change + success keywords → likely_success with high confidence."""
        from guardian_agent.browser_operator import _reconcile_submission_state

        before = {
            "current_url": "https://example.com/checkout",
            "has_success_indicator": False,
            "has_error_indicator": False,
            "success_keywords": [],
            "error_keywords": [],
        }
        after = {
            "current_url": "https://example.com/order-confirmation",
            "has_success_indicator": True,
            "has_error_indicator": False,
            "success_keywords": ["success", "confirmed", "complete"],
            "error_keywords": [],
        }

        result = _reconcile_submission_state(self.brain, before, after)
        self.assertEqual(result["outcome"], "likely_success")
        self.assertEqual(result["confidence"], 0.9)
        self.assertTrue(result["url_changed"])
        self.assertTrue(result["has_success"])
        self.assertFalse(result["has_error"])

    def test_reconcile_submission_url_change_no_error(self) -> None:
        """URL change without error keywords → likely_success at 0.7 confidence."""
        from guardian_agent.browser_operator import _reconcile_submission_state

        before = {"current_url": "https://example.com/form", "has_success_indicator": False, "has_error_indicator": False}
        after = {"current_url": "https://example.com/thanks", "has_success_indicator": False, "has_error_indicator": False}

        result = _reconcile_submission_state(self.brain, before, after)
        self.assertEqual(result["outcome"], "likely_success")
        self.assertEqual(result["confidence"], 0.7)
        self.assertTrue(result["url_changed"])

    def test_reconcile_submission_success_keywords_only(self) -> None:
        """Success keywords without URL change → likely_success at 0.6 confidence."""
        from guardian_agent.browser_operator import _reconcile_submission_state

        before = {"current_url": "https://example.com/page", "has_success_indicator": False, "has_error_indicator": False}
        after = {"current_url": "https://example.com/page", "has_success_indicator": True, "has_error_indicator": False, "success_keywords": ["success"], "error_keywords": []}

        result = _reconcile_submission_state(self.brain, before, after)
        self.assertEqual(result["outcome"], "likely_success")
        self.assertEqual(result["confidence"], 0.6)
        self.assertFalse(result["url_changed"])

    def test_reconcile_submission_error_detected(self) -> None:
        """Error keywords → likely_failed at 0.8 confidence."""
        from guardian_agent.browser_operator import _reconcile_submission_state

        before = {"current_url": "https://example.com/pay", "has_success_indicator": False, "has_error_indicator": False}
        after = {"current_url": "https://example.com/pay", "has_success_indicator": False, "has_error_indicator": True, "success_keywords": [], "error_keywords": ["declined", "error"]}

        result = _reconcile_submission_state(self.brain, before, after)
        self.assertEqual(result["outcome"], "likely_failed")
        self.assertEqual(result["confidence"], 0.8)
        self.assertTrue(result["has_error"])

    def test_reconcile_submission_uncertain(self) -> None:
        """No signals → uncertain at 0.3 confidence."""
        from guardian_agent.browser_operator import _reconcile_submission_state

        before = {"current_url": "https://example.com/page", "has_success_indicator": False, "has_error_indicator": False}
        after = {"current_url": "https://example.com/page", "has_success_indicator": False, "has_error_indicator": False}

        result = _reconcile_submission_state(self.brain, before, after)
        self.assertEqual(result["outcome"], "uncertain")
        self.assertEqual(result["confidence"], 0.3)

    def test_reconcile_submission_missing_fields_defaults(self) -> None:
        """Verify reconciliation handles missing fields gracefully."""
        from guardian_agent.browser_operator import _reconcile_submission_state

        before = {}
        after = {}

        result = _reconcile_submission_state(self.brain, before, after)
        self.assertEqual(result["outcome"], "uncertain")
        self.assertEqual(result["confidence"], 0.3)

    # -------------------------------------------------------------------
    # pause_for_takeover page-context tests
    # -------------------------------------------------------------------

    def test_pause_for_takeover_stores_page_context_in_meta(self) -> None:
        """Verify pause_for_takeover stores current_page_url and current_page_title in metadata."""
        from guardian_agent.browser_operator import pause_for_takeover, _takeover_meta_path

        register_account(
            self.brain,
            account_id="acc-tk-pagectx",
            service_name="canva",
            account_label="Takeover Page Context Test",
            vault_ref="vault:canva_key",
            allowed_domains=["canva.com"],
        )

        # Use a unique signal file path
        sig_file = Path(self.tempdir.name) / "takeover_signal_pagectx.txt"
        sig_file.write_text("initial", encoding="utf-8")

        result = pause_for_takeover(
            self.brain,
            account_id="acc-tk-pagectx",
            timeout_seconds=1,  # Short timeout so test completes quickly
            signal_file=sig_file,
            current_page_url="https://canva.com/design/test-design-123",
            current_page_title="My Canva Design",
        )

        # Should have timed out since we don't remove the signal
        self.assertIn(result["status"], ("cancelled_timeout", "resumed"))

        # Verify metadata contains page context
        meta_p = _takeover_meta_path(self.brain, "acc-tk-pagectx")
        self.assertTrue(meta_p.is_file())
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        self.assertEqual(meta.get("page_url"), "https://canva.com/design/test-design-123")
        self.assertEqual(meta.get("page_title"), "My Canva Design")

    def test_pause_for_takeover_without_page_context(self) -> None:
        """Verify pause_for_takeover works without page context (backward compatible)."""
        from guardian_agent.browser_operator import pause_for_takeover, _takeover_meta_path

        register_account(
            self.brain,
            account_id="acc-tk-noctx",
            service_name="canva",
            account_label="Takeover No Context Test",
            vault_ref="vault:canva_key",
            allowed_domains=["canva.com"],
        )

        sig_file = Path(self.tempdir.name) / "takeover_signal_noctx.txt"
        sig_file.write_text("initial", encoding="utf-8")

        result = pause_for_takeover(
            self.brain,
            account_id="acc-tk-noctx",
            timeout_seconds=1,
            signal_file=sig_file,
            # No current_page_url or current_page_title
        )

        self.assertIn(result["status"], ("cancelled_timeout", "resumed"))

        # Verify metadata shows null for page context
        meta_p = _takeover_meta_path(self.brain, "acc-tk-noctx")
        self.assertTrue(meta_p.is_file())
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        self.assertIsNone(meta.get("page_url"))
        self.assertIsNone(meta.get("page_title"))


if __name__ == "__main__":
    unittest.main()
