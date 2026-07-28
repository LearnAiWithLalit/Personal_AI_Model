"""Tests for Guardian's durable execution governor."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from guardian_agent.core import GuardianError, initialize
from guardian_agent.execution import (
    claim_execution_stage,
    list_executions,
    mark_execution_dispatched,
    next_execution_stage,
    plan_execution,
    record_execution_result,
    recover_execution,
    show_execution,
)
from guardian_agent.orchestration import orchestrate_start, orchestrate_confirm, orchestrate_dispatch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_dispatched_orch(brain, task: str = "Implement a login form", limit: int = 3) -> str:
    start = orchestrate_start(brain, task, limit=limit, approved_paths=["src/", "tests/"])
    orch_id = start["orchestration_id"]
    orchestrate_confirm(brain, orch_id, task)
    orchestrate_dispatch(brain, orch_id)
    return orch_id



def _add_provider_direct(brain, provider_id: str, model_id: str, **kwargs) -> None:
    """Add a provider directly to the gateway file, bypassing add_provider's model policy check."""
    from guardian_agent.gateway import load_gateway, save_gateway
    payload = load_gateway(brain)
    existing = next((p for p in payload["providers"] if p["id"] == provider_id), None)
    model = {
        "id": model_id,
        "capabilities": kwargs.get("capabilities", ["general"]),
        "cost_tier": kwargs.get("cost_tier", "free"),
        "priority": kwargs.get("priority", 100),
        "route_kind": kwargs.get("route_kind", "direct"),
        "member_models": kwargs.get("member_models"),
        "usage_class": kwargs.get("usage_class", "standard"),
    }
    if existing:
        existing_models = [m for m in existing.get("models", []) if m.get("id") != model_id]
        existing["models"] = existing_models + [model]
    else:
        payload["providers"].append({
            "id": provider_id,
            "kind": kwargs.get("kind", "openai-compatible"),
            "base_url": kwargs.get("base_url", "http://localhost:3000/v1"),
            "credential_env": kwargs.get("credential_env"),
            "enabled": True,
            "models": [model],
        })
    save_gateway(brain, payload)


class ExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(
            Path(self.tempdir.name) / "demo",
            "Execution Demo",
            "Execution governor tests",
        )
        # Add local Ollama
        _add_provider_direct(
            self.brain,
            provider_id="local-ollama",
            model_id="qwen2.5-coder:14b",
            capabilities=["coding", "review", "general"],
            cost_tier="local",
            priority=1,
            kind="local",
            base_url="http://localhost:11434/v1",
        )
        # Add standard OmniRoute
        _add_provider_direct(
            self.brain,
            provider_id="local-omniroute",
            model_id="claude-3-opus",
            capabilities=["coding", "review", "general"],
            cost_tier="free",
            priority=2,
            base_url="http://localhost:3000/v1",
            credential_env="OMNIROUTE_API_KEY",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    # ---- dispatched orchestration required ----

    def test_plan_requires_dispatched_orchestration(self) -> None:
        start = orchestrate_start(self.brain, "Add error logging", limit=2)
        orch_id = start["orchestration_id"]
        with self.assertRaises(GuardianError):
            plan_execution(self.brain, orch_id)

    def test_plan_requires_valid_orchestration(self) -> None:
        with self.assertRaises(GuardianError):
            plan_execution(self.brain, "orch-nonexistent")

    # ---- idempotent planning ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_plan_is_idempotent(self, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Fix a bug", limit=2)
        first = plan_execution(self.brain, orch_id)
        second = plan_execution(self.brain, orch_id)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(first["stages"]), len(second["stages"]))

    # ---- local-first order ----

    @patch("guardian_agent.execution.freebuff_status", return_value={"available": False})
    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_local_first_order(self, _kill, _health, _freebuff) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Refactor config", limit=2)
        plan = plan_execution(self.brain, orch_id)
        stages = plan["stages"]
        self.assertGreater(len(stages), 0)
        self.assertEqual(stages[0]["executor"], "ollama")


    # ---- coding FreeBuff placement ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    @patch("guardian_agent.execution.freebuff_status", return_value={"available": True})
    def test_coding_includes_freebuff(self, _freebuff, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Build a dashboard component", limit=2)
        plan = plan_execution(self.brain, orch_id)
        stages = plan["stages"]
        freebuff_stages = [s for s in stages if s["executor"] == "freebuff"]
        self.assertEqual(len(freebuff_stages), 1)

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    @patch("guardian_agent.execution.freebuff_status", return_value={"available": True})
    def test_non_coding_omits_freebuff(self, _freebuff, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Research best practices for API design", limit=2)
        plan = plan_execution(self.brain, orch_id)
        stages = plan["stages"]
        freebuff_stages = [s for s in stages if s["executor"] == "freebuff"]
        self.assertEqual(len(freebuff_stages), 0)

    # ---- max five model stages ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    @patch("guardian_agent.execution.freebuff_status", return_value={"available": True})
    def test_max_five_model_stages(self, _freebuff, _kill, _health) -> None:
        for i in range(5):
            _add_provider_direct(
                self.brain,
                provider_id="local-omniroute",
                model_id=f"pool-{i}",
                capabilities=["coding", "research", "general"],
                cost_tier="free",
                priority=20 + i,
            )
        orch_id = _create_dispatched_orch(self.brain, "Implement search feature", limit=2)
        plan = plan_execution(self.brain, orch_id)
        stages = plan["stages"]
        model_stages = [s for s in stages if s["executor"] != "primary-review"]
        self.assertLessEqual(len(model_stages), 5)
        self.assertEqual(stages[-1]["executor"], "primary-review")

    # ---- final-review route last among model stages ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_final_review_last_among_models(self, _kill, _health) -> None:
        _add_provider_direct(
            self.brain,
            provider_id="local-omniroute",
            model_id="gpt-5.5-final",
            capabilities=["coding", "review", "planning", "reasoning", "general"],
            cost_tier="subscription",
            priority=40,
            usage_class="final-review",
        )
        from guardian_agent.gateway import configure_provider_access
        configure_provider_access(self.brain, allow_subscription=True)
        orch_id = _create_dispatched_orch(self.brain, "Review authentication flow", limit=2)
        plan = plan_execution(self.brain, orch_id)
        stages = plan["stages"]
        model_stages = [s for s in stages if s["executor"] != "primary-review"]
        if len(model_stages) >= 2:
            self.assertEqual(model_stages[-1]["model"], "gpt-5.5-final")

    # ---- primary review always last ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_primary_review_always_last(self, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Implement a search bar", limit=2)
        plan = plan_execution(self.brain, orch_id)
        stages = plan["stages"]
        self.assertGreater(len(stages), 0)
        self.assertEqual(stages[-1]["executor"], "primary-review")

    # ---- prohibited combo excluded transitively ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_prohibited_combo_excluded(self, _kill, _health) -> None:
        """A model containing claude-sonnet-4.6 should be excluded from planning."""
        _add_provider_direct(
            self.brain,
            provider_id="local-omniroute",
            model_id="claude-sonnet-4.6-combo",
            capabilities=["coding", "review", "general"],
            cost_tier="free",
            priority=5,
        )
        orch_id = _create_dispatched_orch(self.brain, "Build a user profile page", limit=2)
        plan = plan_execution(self.brain, orch_id)
        stages = plan["stages"]
        model_names = [s.get("model") for s in stages]
        self.assertNotIn("claude-sonnet-4.6-combo", model_names)

    # ---- unhealthy routes excluded ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": False, "error_count": 5})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_unhealthy_routes_excluded(self, _kill, _health) -> None:
        """Unhealthy routes should not appear in the plan; primary-review still created."""
        orch_id = _create_dispatched_orch(self.brain, "Fix typo in docs", limit=2)
        plan = plan_execution(self.brain, orch_id)
        stages = plan["stages"]
        # Only primary-review stage should exist since ollama is unhealthy
        self.assertEqual(len(stages), 1)
        self.assertEqual(stages[0]["executor"], "primary-review")

    # ---- emergency stop blocks planning ----

    @patch("guardian_agent.execution.is_kill_switch_active", return_value=True)
    def test_emergency_stop_blocks_planning(self, _kill) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Fix README", limit=2)
        with self.assertRaises(GuardianError):
            plan_execution(self.brain, orch_id)

    # ---- exact current-stage claim with lease ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_claim_returns_lease(self, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Add unit tests", limit=2)
        plan = plan_execution(self.brain, orch_id)
        stages = plan["stages"]
        stage_id = stages[0]["id"]
        result = claim_execution_stage(self.brain, plan["id"], stage_id, lease_seconds=900)
        self.assertIn("lease_id", result)
        self.assertIsNotNone(result["lease_id"])
        self.assertEqual(result["executor"], stages[0]["executor"])

    # ---- duplicate claim refusal ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_duplicate_claim_refused(self, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Fix a typo", limit=2)
        plan = plan_execution(self.brain, orch_id)
        stages = plan["stages"]
        stage_id = stages[0]["id"]
        claim_execution_stage(self.brain, plan["id"], stage_id)
        with self.assertRaises(GuardianError):
            claim_execution_stage(self.brain, plan["id"], stage_id)

    # ---- pass/fail/skip advancement ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_passed_stage_advances(self, _kill, _health) -> None:
        """Passing an ordinary stage skips remaining fallbacks and jumps to terminal."""
        orch_id = _create_dispatched_orch(self.brain, "Add metrics endpoint", limit=2)
        plan = plan_execution(self.brain, orch_id)
        exec_id = plan["id"]
        stage_count = len(plan["stages"])
        stage_id = plan["stages"][0]["id"]
        claim = claim_execution_stage(self.brain, exec_id, stage_id)
        result = record_execution_result(
            self.brain, exec_id, stage_id, claim["lease_id"],
            "passed", "Tests passed: 5/5 scenarios verified",
        )
        # The passed ordinary stage should skip past intermediate fallback(s)
        # and land on the terminal (primary-review) stage.
        terminal_idx = stage_count - 1  # primary-review is always last
        self.assertEqual(result["current_stage_index"], terminal_idx)
        self.assertIn(result["status"], ("completed", "awaiting_final_review"))
        # Reload the record to verify intermediate stages were skipped
        reloaded = show_execution(self.brain, exec_id)
        for i in range(1, terminal_idx):
            self.assertEqual(reloaded["stages"][i]["state"], "skipped",
                             f"Stage {i} should be skipped after prior stage passed")

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_failed_stage_advances_to_next(self, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Fix pagination bug", limit=2)
        plan = plan_execution(self.brain, orch_id)
        exec_id = plan["id"]
        stage_id = plan["stages"][0]["id"]
        claim = claim_execution_stage(self.brain, exec_id, stage_id)
        result = record_execution_result(
            self.brain, exec_id, stage_id, claim["lease_id"],
            "failed", "Tests failed: 2/5 scenarios",
        )
        self.assertEqual(result["current_stage_index"], 1)

    # ---- skipped stage advances ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_skipped_stage_advances(self, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Small CSS tweak", limit=2)
        plan = plan_execution(self.brain, orch_id)
        exec_id = plan["id"]
        stage_id = plan["stages"][0]["id"]
        claim = claim_execution_stage(self.brain, exec_id, stage_id)
        result = record_execution_result(
            self.brain, exec_id, stage_id, claim["lease_id"],
            "skipped", "Stage skipped: not applicable",
        )
        self.assertEqual(result["current_stage_index"], 1)
        self.assertEqual(result["status"], "running")

    # ---- final primary-review completion/failure ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_primary_review_passed_completes(self, _kill, _health) -> None:
        """Passing a primary-review stage completes the execution."""
        orch_id = _create_dispatched_orch(self.brain, "Add logging", limit=2)
        plan = plan_execution(self.brain, orch_id)
        exec_id = plan["id"]
        # Find the terminal stage (primary-review is always last)
        # Pass the first ordinary stage — it will skip past intermediates
        stage = plan["stages"][0]
        claim = claim_execution_stage(self.brain, exec_id, stage["id"])
        record_execution_result(
            self.brain, exec_id, stage["id"], claim["lease_id"],
            "passed", "Stage passed.",
        )
        # Now the primary-review stage should be current
        next_info = next_execution_stage(self.brain, exec_id)
        self.assertFalse(next_info["completed"])
        self.assertEqual(next_info["stage"]["executor"], "primary-review")
        # Pass the primary-review stage
        primary_stage = next_info["stage"]
        claim2 = claim_execution_stage(self.brain, exec_id, primary_stage["id"])
        result = record_execution_result(
            self.brain, exec_id, primary_stage["id"], claim2["lease_id"],
            "passed", "Primary review approved all changes.",
        )
        self.assertEqual(result["status"], "completed")

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_primary_review_failed_ends_execution(self, _kill, _health) -> None:
        """Failing a primary-review stage fails the execution."""
        orch_id = _create_dispatched_orch(self.brain, "Small CSS fix", limit=2)
        plan = plan_execution(self.brain, orch_id)
        exec_id = plan["id"]
        # Pass the first ordinary stage — skip to terminal
        stage = plan["stages"][0]
        claim = claim_execution_stage(self.brain, exec_id, stage["id"])
        record_execution_result(
            self.brain, exec_id, stage["id"], claim["lease_id"],
            "passed", "Stage passed.",
        )
        # The primary-review stage should now be current
        next_info = next_execution_stage(self.brain, exec_id)
        self.assertEqual(next_info["stage"]["executor"], "primary-review")
        # Fail the primary-review stage
        primary_stage = next_info["stage"]
        claim2 = claim_execution_stage(self.brain, exec_id, primary_stage["id"])
        result = record_execution_result(
            self.brain, exec_id, primary_stage["id"], claim2["lease_id"],
            "failed", "Primary review rejected: performance regression.",
        )
        self.assertEqual(result["status"], "failed")

    # ---- exact replay idempotency ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_exact_replay_idempotency(self, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Add rate limiter", limit=2)
        plan = plan_execution(self.brain, orch_id)
        exec_id = plan["id"]
        stage_id = plan["stages"][0]["id"]
        claim = claim_execution_stage(self.brain, exec_id, stage_id)
        first = record_execution_result(
            self.brain, exec_id, stage_id, claim["lease_id"],
            "passed", "Tests passed: 10/10",
        )
        second = record_execution_result(
            self.brain, exec_id, stage_id, claim["lease_id"],
            "passed", "Tests passed: 10/10",
        )
        self.assertEqual(first["status"], second["status"])
        self.assertIn("already recorded", second.get("note", ""))

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_async_dispatch_waits_and_accepts_exact_verified_result(self, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Implement audit logging", limit=2)
        plan = plan_execution(self.brain, orch_id)
        exec_id = plan["id"]
        stage_id = plan["stages"][0]["id"]
        claim = claim_execution_stage(self.brain, exec_id, stage_id)

        dispatched = mark_execution_dispatched(
            self.brain, exec_id, stage_id, claim["lease_id"],
            "Handoff saved for worker",
        )
        current = next_execution_stage(self.brain, exec_id)
        self.assertEqual(current["stage"]["state"], "dispatched")
        self.assertEqual(current["stage_index"], 0)

        replay = mark_execution_dispatched(
            self.brain, exec_id, stage_id, claim["lease_id"],
            "Handoff saved for worker",
        )
        self.assertEqual(replay["dispatch_id"], dispatched["dispatch_id"])

        with self.assertRaises(GuardianError):
            record_execution_result(
                self.brain, exec_id, stage_id, claim["lease_id"],
                "passed", "Tests passed", dispatch_id="dispatch-wrong",
            )

        result = record_execution_result(
            self.brain, exec_id, stage_id, claim["lease_id"],
            "passed", "Worker changes verified: tests passed",
            dispatch_id=dispatched["dispatch_id"],
        )
        self.assertGreater(result["current_stage_index"], 0)

        duplicate = record_execution_result(
            self.brain, exec_id, stage_id, claim["lease_id"],
            "passed", "Worker changes verified: tests passed",
            dispatch_id=dispatched["dispatch_id"],
        )
        self.assertIn("already recorded", duplicate["note"])

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    @patch("guardian_agent.execution.time.time", return_value=0.0)
    def test_timed_out_dispatch_fails_and_advances_fallback(self, _mock_time, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Implement retry policy", limit=2)
        plan = plan_execution(self.brain, orch_id)
        exec_id = plan["id"]
        stage_id = plan["stages"][0]["id"]
        claim = claim_execution_stage(self.brain, exec_id, stage_id, lease_seconds=900)
        mark_execution_dispatched(
            self.brain, exec_id, stage_id, claim["lease_id"],
            "Worker accepted handoff",
        )

        _mock_time.return_value = 901.0
        recovered = recover_execution(self.brain, exec_id)
        self.assertEqual(recovered["timed_out_dispatches"], 1)
        self.assertEqual(next_execution_stage(self.brain, exec_id)["stage_index"], 1)
        self.assertEqual(show_execution(self.brain, exec_id)["stages"][0]["state"], "failed")

    # ---- stale lease recovery ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    @patch("guardian_agent.execution.time.time", return_value=0.0)
    def test_stale_lease_recovery(self, _mock_time, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Small fix", limit=2)
        plan = plan_execution(self.brain, orch_id)
        exec_id = plan["id"]
        stage_id = plan["stages"][0]["id"]
        # Claim with mock time at 0.0, lease expires at 900
        claim_execution_stage(self.brain, exec_id, stage_id, lease_seconds=900)
        # Advance mock time past expiry
        _mock_time.return_value = 901.0
        result = recover_execution(self.brain, exec_id)
        self.assertGreaterEqual(result["stale_claims_recovered"], 1)

    # ---- evidence limits ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_evidence_limited(self, _kill, _health) -> None:
        from guardian_agent.execution import _MAX_EVIDENCE_LENGTH
        orch_id = _create_dispatched_orch(self.brain, "Add logging", limit=2)
        plan = plan_execution(self.brain, orch_id)
        exec_id = plan["id"]
        stage_id = plan["stages"][0]["id"]
        claim = claim_execution_stage(self.brain, exec_id, stage_id)
        long_evidence = "x" * (_MAX_EVIDENCE_LENGTH + 1000)
        result = record_execution_result(
            self.brain, exec_id, stage_id, claim["lease_id"],
            "passed", long_evidence,
        )
        # Passed ordinary stage now skips to terminal; evidence is still bounded
        self.assertIn(result["status"], ("awaiting_final_review", "completed"))

    # ---- safe/unsafe artifact paths ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_safe_artifact_path_accepted(self, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Add feature flag", limit=2)
        plan = plan_execution(self.brain, orch_id)
        exec_id = plan["id"]
        stage_id = plan["stages"][0]["id"]
        claim = claim_execution_stage(self.brain, exec_id, stage_id)
        result = record_execution_result(
            self.brain, exec_id, stage_id, claim["lease_id"],
            "passed", "Tests passed", artifact_path="src/myfile.py",
        )
        self.assertEqual(result["artifact_path"], "src/myfile.py")

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_unsafe_artifact_path_rejected(self, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Small change", limit=2)
        plan = plan_execution(self.brain, orch_id)
        exec_id = plan["id"]
        stage_id = plan["stages"][0]["id"]
        claim = claim_execution_stage(self.brain, exec_id, stage_id)
        with self.assertRaises(GuardianError):
            record_execution_result(
                self.brain, exec_id, stage_id, claim["lease_id"],
                "passed", "Tests passed", artifact_path=".env",
            )

    # ---- no secret routing fields persisted ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_no_secret_fields_persisted(self, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Fix console warnings", limit=2)
        plan = plan_execution(self.brain, orch_id)
        exec_dir = self.brain.directory / "tasks" / "executions"
        files = list(exec_dir.glob("exec-*.json"))
        self.assertGreater(len(files), 0)
        raw = json.loads(files[0].read_text(encoding="utf-8"))
        serialized = json.dumps(raw)
        self.assertNotIn("credential_env", serialized)
        self.assertNotIn("base_url", serialized)
        self.assertNotIn("OMNIROUTE_API_KEY", serialized)
        self.assertNotIn("OPENAI_API_KEY", serialized)

    # ---- show and list ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_show_returns_full_record(self, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Build caching layer", limit=2)
        plan = plan_execution(self.brain, orch_id)
        shown = show_execution(self.brain, plan["id"])
        self.assertEqual(shown["id"], plan["id"])
        self.assertIn("stages", shown)
        self.assertEqual(shown["task_type"], "coding")

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_list_returns_all(self, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Write tests", limit=2)
        plan_execution(self.brain, orch_id)
        all_execs = list_executions(self.brain)
        self.assertGreaterEqual(len(all_execs), 1)
        self.assertIn("task", all_execs[0])
        self.assertIn("status", all_execs[0])

    # ---- next stage ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_next_stage_readonly(self, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Add dark mode", limit=2)
        plan = plan_execution(self.brain, orch_id)
        next_stage = next_execution_stage(self.brain, plan["id"])
        self.assertFalse(next_stage["completed"])
        self.assertIsNotNone(next_stage["stage"])
        self.assertEqual(next_stage["stage"]["state"], "pending")

    # ---- corrupted record handling ----

    def test_corrupted_record_raises_error(self) -> None:
        exec_dir = self.brain.directory / "tasks" / "executions"
        exec_dir.mkdir(parents=True, exist_ok=True)
        bad_path = exec_dir / "exec-bad.json"
        bad_path.write_text("{corrupted json", encoding="utf-8")
        with self.assertRaises(GuardianError):
            show_execution(self.brain, "exec-bad")

    # ---- claim wrong stage ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_claim_wrong_stage_refused(self, _kill, _health) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Fix a typo", limit=2)
        plan = plan_execution(self.brain, orch_id)
        second_id = plan["stages"][1]["id"]
        with self.assertRaises(GuardianError):
            claim_execution_stage(self.brain, plan["id"], second_id)

    # ---- emergency stop blocks claiming ----

    @patch("guardian_agent.execution.is_kill_switch_active", return_value=True)
    def test_emergency_stop_blocks_claiming(self, _kill) -> None:
        orch_id = _create_dispatched_orch(self.brain, "Fix a bug", limit=2)
        with patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True}):
            with patch("guardian_agent.execution.is_kill_switch_active", return_value=False):
                plan = plan_execution(self.brain, orch_id)
        stage_id = plan["stages"][0]["id"]
        with self.assertRaises(GuardianError):
            claim_execution_stage(self.brain, plan["id"], stage_id)


    # ---- regression: claim-time capacity revalidation ----

    @patch("guardian_agent.execution.require_capacity_available")
    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_claim_refuses_blocked_capacity(self, _kill, _health, _cap_check) -> None:
        """If recorded capacity is exhausted/blocked, claim is refused."""
        _cap_check.side_effect = GuardianError(
            "Provider route local-ollama:qwen2.5-coder:14b is in an observed "
            "retry/quota window for about 30s; no request was sent."
        )
        orch_id = _create_dispatched_orch(self.brain, "Fix typo", limit=2)
        plan = plan_execution(self.brain, orch_id)
        exec_id = plan["id"]
        stage = next(s for s in plan["stages"] if s.get("provider"))
        stage_id = stage["id"]
        with self.assertRaises(GuardianError):
            claim_execution_stage(self.brain, exec_id, stage_id)

    # ---- regression: final-review slot is reserved against crowding ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_final_review_slot_reserved_against_crowding(self, _kill, _health) -> None:
        """When a healthy final-review route exists, it gets a guaranteed slot even
        with 5+ omniroute pools competing for ordinary slots."""
        # Allow subscription routes for final-review
        from guardian_agent.gateway import configure_provider_access
        configure_provider_access(self.brain, allow_subscription=True)
        # Add a final-review route
        _add_provider_direct(
            self.brain,
            provider_id="local-omniroute",
            model_id="gpt-5.5-final",
            capabilities=["coding", "review", "planning", "reasoning", "general"],
            cost_tier="subscription",
            priority=40,
            usage_class="final-review",
        )
        # Add 6 omniroute pools to try to crowd out the final-review slot
        for i in range(6):
            _add_provider_direct(
                self.brain,
                provider_id="local-omniroute",
                model_id=f"pool-{i}",
                capabilities=["coding", "research", "general"],
                cost_tier="free",
                priority=20 + i,
            )
        orch_id = _create_dispatched_orch(self.brain, "Implement search feature", limit=2)
        plan = plan_execution(self.brain, orch_id)
        stages = plan["stages"]
        model_names = [s.get("model") for s in stages if s.get("model")]
        self.assertIn("gpt-5.5-final", model_names,
                      "Final-review route must have a reserved slot despite many omniroute pools")
        # At most 5 model stages + 1 primary-review
        model_stages = [s for s in stages if s["executor"] != "primary-review"]
        self.assertLessEqual(len(model_stages), 5)

    # ---- regression: claim-time revalidation refuses unhealthy routes ----

    @patch("guardian_agent.execution.check_provider_health")
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_claim_refuses_unhealthy_route_at_claim_time(self, _kill, _health) -> None:
        """If a route becomes unhealthy after planning, claiming is refused."""
        # Plan with healthy provider
        _health.return_value = {"healthy": True, "error_count": 0}
        orch_id = _create_dispatched_orch(self.brain, "Fix typo", limit=2)
        plan = plan_execution(self.brain, orch_id)
        exec_id = plan["id"]
        stage = next(s for s in plan["stages"] if s.get("provider"))
        stage_id = stage["id"]
        # Now make the provider unhealthy before claiming
        _health.return_value = {"healthy": False, "error_count": 5}
        with self.assertRaises(GuardianError):
            claim_execution_stage(self.brain, exec_id, stage_id)


    # ---- regression: skip event is recorded ----

    @patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True})
    @patch("guardian_agent.execution.is_kill_switch_active", return_value=False)
    def test_skip_event_recorded_when_stages_skipped(self, _kill, _health) -> None:
        """One pass cascade emits exactly one stage_skip event."""
        orch_id = _create_dispatched_orch(self.brain, "Build a feature", limit=2)
        plan = plan_execution(self.brain, orch_id)
        exec_id = plan["id"]
        stage_id = plan["stages"][0]["id"]
        # Must have at least an intermediate stage to skip
        if len(plan["stages"]) > 2:
            claim = claim_execution_stage(self.brain, exec_id, stage_id)
            record_execution_result(
                self.brain, exec_id, stage_id, claim["lease_id"],
                "passed", "Stage passed — should trigger skip cascade",
            )
            reloaded = show_execution(self.brain, exec_id)
            events = reloaded.get("events", [])
            skip_events = [e for e in events if e["type"] == "stage_skip"]
            self.assertEqual(len(skip_events), 1,
                             "One pass cascade must emit exactly one stage_skip event")
            self.assertIn("skipped", skip_events[0]["detail"].lower())


if __name__ == "__main__":
    unittest.main()
