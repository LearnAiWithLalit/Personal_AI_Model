import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from guardian_agent.core import GuardianError, initialize
from guardian_agent.orchestration import orchestrate_start, orchestrate_confirm, orchestrate_dispatch
from guardian_agent.execution import plan_execution, show_execution, _load_record, _save_record
from guardian_agent.supervisor import supervisor_run_once
from guardian_agent.runtime import kill_switch
from guardian_agent.executor_worker import (
    execute_ticket,
    list_ready_tickets,
    process_ready_tickets,
)


class ExecutorWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Executor Demo", "Testing ticket executor worker")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _setup_tickets(self) -> dict:
        start = orchestrate_start(self.brain, "Refactor auth module", limit=3, approved_paths=["src/", "tests/"])
        orch_id = start["orchestration_id"]

        orchestrate_confirm(self.brain, orch_id, "Refactor auth module")
        orchestrate_dispatch(self.brain, orch_id)
        plan = plan_execution(self.brain, orch_id)
        sup = supervisor_run_once(self.brain)
        return {"orch_id": orch_id, "plan": plan, "sup": sup}

    def test_list_ready_tickets(self) -> None:
        self._setup_tickets()
        ready = list_ready_tickets(self.brain)
        self.assertTrue(len(ready) >= 1)
        self.assertTrue(all(t["state"] == "ready" for t in ready))

    def test_dry_run_does_not_mutate_execution_state(self) -> None:
        """Verify dry_run=True returns simulation preview without claiming lease or recording result."""
        self._setup_tickets()
        ready = list_ready_tickets(self.brain)
        ticket = ready[0]

        res = execute_ticket(self.brain, ticket, dry_run=True)
        self.assertTrue(res.get("dry_run"))
        self.assertEqual(res.get("status"), "simulated")

        ex_record = show_execution(self.brain, ticket["execution_id"])
        stage = next(s for s in ex_record["stages"] if s["id"] == ticket["stage_id"])
        self.assertEqual(stage["state"], "pending")
        self.assertIsNone(stage.get("lease_id"))

    @patch("guardian_agent.executor_worker.complete_task_with_model")
    def test_dispatched_handoff_stage_waits_for_verified_result(self, mock_model) -> None:
        """A handoff remains current and returns credentials for its later result."""
        mock_model.return_value = {"model": "test-mock-model", "response": "Mocked completion text"}
        self._setup_tickets()
        ready = list_ready_tickets(self.brain)
        ticket = ready[0]

        res = execute_ticket(self.brain, ticket, dry_run=False)
        self.assertEqual(res["outcome"], "dispatched")
        self.assertTrue(res["dispatch_id"].startswith("dispatch-"))
        self.assertTrue(res["lease_id"])
        self.assertIn("DISPATCHED", res["evidence"])
        record = show_execution(self.brain, ticket["execution_id"])
        self.assertEqual(record["current_stage_index"], 0)
        self.assertEqual(record["stages"][0]["state"], "dispatched")
        self.assertEqual(list_ready_tickets(self.brain), [])

        stale_copy = dict(ticket)
        with self.assertRaises(GuardianError):
            execute_ticket(self.brain, stale_copy, dry_run=False)

    def test_refuse_stale_or_mismatched_stage_ticket(self) -> None:
        """Verify ticket execution is refused if ticket stage ID or metadata does not match current pending stage."""
        self._setup_tickets()
        ready = list_ready_tickets(self.brain)
        
        # Mismatched stage_id
        bad_id_ticket = dict(ready[0])
        bad_id_ticket["stage_id"] = "non-existent-stage-id"
        with self.assertRaises(GuardianError):
            execute_ticket(self.brain, bad_id_ticket, dry_run=False)

        # Mismatched executor metadata
        bad_exec_ticket = dict(ready[0])
        bad_exec_ticket["executor"] = "mismatched_executor_kind"
        with self.assertRaises(GuardianError):
            execute_ticket(self.brain, bad_exec_ticket, dry_run=False)

    def test_ticket_task_tampering_refused(self) -> None:
        """Verify ticket with tampered task prompt is strictly refused against canonical execution task."""
        self._setup_tickets()
        ready = list_ready_tickets(self.brain)
        tampered_ticket = dict(ready[0])
        tampered_ticket["task"] = "MALICIOUS TAMPERED TASK PROMPT"

        with self.assertRaises(GuardianError) as ctx:
            execute_ticket(self.brain, tampered_ticket, dry_run=False)
        self.assertIn("does not match canonical execution task", str(ctx.exception))

    @patch("guardian_agent.executor_worker.resolve_configured_route")
    def test_exact_route_failure_fails_closed(self, mock_resolve) -> None:
        """Verify ticket fails closed if exact route resolution fails when provider/model are set."""
        mock_resolve.side_effect = GuardianError("Configured route is unavailable")
        self._setup_tickets()
        ready = list_ready_tickets(self.brain)
        ticket = dict(ready[0])

        rec = _load_record(self.brain, ticket["execution_id"])
        stage = next(s for s in rec.stages if s.id == ticket["stage_id"])
        stage.executor = "ollama"
        stage.provider = "local-ollama"
        stage.model = "llama3"
        _save_record(self.brain, rec)

        ticket["executor"] = "ollama"
        ticket["provider"] = "local-ollama"
        ticket["model"] = "llama3"

        res = execute_ticket(self.brain, ticket, dry_run=False)
        self.assertEqual(res["outcome"], "failed")
        self.assertIn("failed closed", res["evidence"])

    @patch("guardian_agent.executor_worker.complete_task_with_model")
    @patch("guardian_agent.executor_worker.resolve_configured_route")
    def test_exact_route_success_uses_requested_provider_and_model(self, mock_resolve, mock_complete) -> None:
        """Verify exact route resolution is called with requested provider and model."""
        mock_resolve.return_value = {"provider_id": "local-ollama", "model_id": "llama3"}
        mock_complete.return_value = {"model": "llama3", "response": "Valid model response for coding"}
        self._setup_tickets()
        ready = list_ready_tickets(self.brain)
        ticket = dict(ready[0])

        rec = _load_record(self.brain, ticket["execution_id"])
        stage = next(s for s in rec.stages if s.id == ticket["stage_id"])
        stage.executor = "ollama"
        stage.provider = "local-ollama"
        stage.model = "llama3"
        _save_record(self.brain, rec)

        ticket["executor"] = "ollama"
        ticket["provider"] = "local-ollama"
        ticket["model"] = "llama3"

        res = execute_ticket(self.brain, ticket, dry_run=False)
        mock_resolve.assert_called_once_with(self.brain, "coding", "local-ollama", "llama3")
        self.assertEqual(res["outcome"], "dispatched")

    def test_max_tickets_out_of_bounds_validation(self) -> None:
        with self.assertRaises(GuardianError):
            process_ready_tickets(self.brain, max_tickets=0)
        with self.assertRaises(GuardianError):
            process_ready_tickets(self.brain, max_tickets=150)

    def test_kill_switch_blocks_execution(self) -> None:
        self._setup_tickets()
        ready = list_ready_tickets(self.brain)
        ticket = ready[0]

        kill_switch(self.brain)
        with self.assertRaises(GuardianError):
            execute_ticket(self.brain, ticket, dry_run=False)

    @patch("guardian_agent.executor_worker.complete_task_with_model")
    def test_process_ready_tickets(self, mock_model) -> None:
        mock_model.return_value = {"model": "test-mock-model", "response": "Mocked completion text"}
        self._setup_tickets()
        res = process_ready_tickets(self.brain, max_tickets=2, dry_run=False)
        self.assertTrue(res["executed_count"] >= 1)

    @patch("guardian_agent.executor_worker.list_ready_tickets")
    @patch("guardian_agent.executor_worker.execute_ticket")
    def test_process_ready_tickets_concurrency_timing(self, mock_execute, mock_list) -> None:
        """Verify process_ready_tickets processes tickets concurrently using timing.

        With max_workers=4 and 4 tickets each simulating 0.2s work, the total
        time should be ~0.2s (parallel) rather than ~0.8s (sequential).
        """
        import time as _time

        # Create 4 mock tickets
        mock_tickets = []
        for i in range(4):
            mock_tickets.append({
                "version": 1,
                "execution_id": f"exec-concur-{i}",
                "stage_id": "stage-1",
                "executor": "deterministic",
                "state": "ready",
                "task": "Implement feature",
                "purpose": f"Mock ticket {i}",
            })
        mock_list.return_value = mock_tickets

        exec_times = []

        def _timed_execute(brain, ticket, dry_run=False):
            exec_times.append(_time.time())
            _time.sleep(0.2)
            return {
                "execution_id": ticket.get("execution_id", "exec-unknown"),
                "stage_id": ticket.get("stage_id", "stage-1"),
                "executor": "deterministic",
                "outcome": "dispatched",
            }

        mock_execute.side_effect = _timed_execute

        start = _time.time()
        res = process_ready_tickets(self.brain, max_tickets=4, dry_run=True, max_workers=4)
        elapsed = _time.time() - start

        # Should have processed all tickets
        self.assertEqual(res["executed_count"], 4)

        # Timing proof: 4 tickets × 0.2s should take < 1.0s with parallelism
        # (generous threshold accounting for thread pool overhead)
        self.assertLess(
            elapsed,
            1.0,
            f"4 tickets × 0.2s sleep took {elapsed:.2f}s — likely sequential, not parallel",
        )

        # Verify execution timestamps overlap (proof of concurrency)
        if len(exec_times) >= 2:
            sorted_times = sorted(exec_times)
            spread = sorted_times[-1] - sorted_times[0]
            self.assertLess(
                spread,
                0.5,
                f"Ticket start times span {spread:.2f}s — likely sequential",
            )


if __name__ == "__main__":
    unittest.main()
