"""Unit tests for Phase 8: FreeBuff-First Coding and Two-Layer QA Pipeline."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from guardian_agent.core import GuardianError, initialize
from guardian_agent.execution import plan_execution
from guardian_agent.freebuff import launch_freebuff
from guardian_agent.orchestration import orchestrate_confirm, orchestrate_dispatch, orchestrate_start
from guardian_agent.qa_pipeline import (
    VALID_QA1_STATUSES,
    build_qa1_payload,
    evaluate_qa1_result,
    should_escalate_to_qa2,
)


def _create_dispatched_orch(brain, task: str = "Implement login form") -> str:
    start = orchestrate_start(brain, task, limit=3, approved_paths=["src/", "tests/"])
    orch_id = start["orchestration_id"]
    orchestrate_confirm(brain, orch_id, task)
    orchestrate_dispatch(brain, orch_id)
    return orch_id


class Phase8FreeBuffQATests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Phase 8 Demo", "Phase 8 coverage")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_freebuff_is_before_local_ollama(self) -> None:
        """Verify FreeBuff stage is placed BEFORE local Ollama fallback stage in execution planning."""
        orch_id = _create_dispatched_orch(self.brain, "Refactor authentication layer")
        with (
            patch("guardian_agent.execution.freebuff_status", return_value={"available": True}),
            patch(
                "guardian_agent.execution.list_routes_for_task",
                return_value=[
                    {
                        "provider": "local-ollama",
                        "model": "qwen3-coder:30b",
                        "cost_tier": "local",
                        "route_priority": 100,
                    }
                ],
            ),
            patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True}),
        ):
            record = plan_execution(self.brain, orch_id)

            stages = record["stages"]
            self.assertGreaterEqual(len(stages), 2)
            self.assertEqual(stages[0]["executor"], "freebuff")
            self.assertEqual(stages[1]["executor"], "ollama")

    def test_freebuff_failure_triggers_qwen_aider(self) -> None:
        """Verify when FreeBuff is unavailable, planning falls back to local Ollama (Aider + Qwen)."""
        orch_id = _create_dispatched_orch(self.brain, "Fix bug in auth handler")
        with (
            patch("guardian_agent.execution.freebuff_status", return_value={"available": False}),
            patch(
                "guardian_agent.execution.list_routes_for_task",
                return_value=[
                    {
                        "provider": "local-ollama",
                        "model": "qwen3-coder:30b",
                        "cost_tier": "local",
                        "route_priority": 100,
                    }
                ],
            ),
            patch("guardian_agent.execution.check_provider_health", return_value={"healthy": True}),
        ):
            record = plan_execution(self.brain, orch_id)

            stages = record["stages"]
            self.assertEqual(stages[0]["executor"], "ollama")
            self.assertEqual(stages[0]["model"], "qwen3-coder:30b")

    def test_freebuff_never_continues_old_session(self) -> None:
        """Verify automated session continuation (conversation_id reuse) is strictly prohibited."""
        with self.assertRaises(GuardianError) as cm:
            launch_freebuff(self.brain, conversation_id="conv-old-123", allow_interactive_resume=False)
        self.assertIn("FreeBuff session continuation is prohibited", str(cm.exception))

    def test_clear_qa1_skips_expensive_qa2(self) -> None:
        """Verify QA1 result status 'clear' returns should_escalate_to_qa2 == False."""
        payload = build_qa1_payload(self.brain, "Fix syntax error", diff_text="+ return True")
        res = evaluate_qa1_result({"status": "clear", "summary": "All tests pass cleanly"})
        self.assertEqual(res["status"], "clear")
        self.assertFalse(should_escalate_to_qa2(res))

    def test_flagged_qa1_reaches_qa2(self) -> None:
        """Verify non-clear QA1 outcomes (flagged, uncertain, failed_tests, security_sensitive) escalate to QA2."""
        for status in ("flagged", "uncertain", "failed_tests", "security_sensitive"):
            res = evaluate_qa1_result({"status": status, "summary": f"Issue detected: {status}"})
            self.assertTrue(should_escalate_to_qa2(res), f"Status {status!r} should escalate to QA2")

    def test_final_approval_cannot_be_skipped(self) -> None:
        """Verify primary-review / user final approval stage is always present at the end of execution plan."""
        orch_id = _create_dispatched_orch(self.brain, "Implement security gate")
        with patch("guardian_agent.execution.freebuff_status", return_value={"available": False}):
            record = plan_execution(self.brain, orch_id)

            stages = record["stages"]
            final_stage = stages[-1]
            self.assertEqual(final_stage["executor"], "primary-review")
            self.assertIn("Mandatory final authority", final_stage["selection_reason"])


if __name__ == "__main__":
    unittest.main()
