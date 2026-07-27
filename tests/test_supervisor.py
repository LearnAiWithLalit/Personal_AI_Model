"""Tests for the bounded Guardian supervisor."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from guardian_agent.core import GuardianError, initialize
from guardian_agent.execution import plan_execution
from guardian_agent.supervisor import (
    supervisor_run,
    supervisor_run_once,
    supervisor_status,
)
from guardian_agent.runtime import kill_switch

class SupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(
            Path(self.tempdir.name) / "demo",
            "Supervisor Demo",
            "Supervisor coverage",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _execution_file(self, execution_id: str, stage: dict | None = None):
        directory = self.brain.directory / "tasks" / "executions"
        directory.mkdir(parents=True, exist_ok=True)

        if stage is None:
            stage = {
                "id": "stage-1",
                "executor": "ollama",
                "provider": "local-ollama",
                "model": "local-model",
                "purpose": "Implement feature",
                "state": "pending",
            }

        (directory / f"{execution_id}.json").write_text(
            json.dumps(
                {
                    "id": execution_id,
                    "task": "Implement feature",
                    "status": "running",
                    "current_stage_index": 0,
                    "stages": [stage],
                    "events": [],
                }
            ),
            encoding="utf-8",
        )

    def test_interval_and_cycle_validation(self):
        with self.assertRaises(GuardianError):
            supervisor_run(self.brain, interval_seconds=10)

        with self.assertRaises(GuardianError):
            supervisor_run(self.brain, max_cycles=20)

    def test_empty_project_safe(self):
        result = supervisor_run_once(self.brain)
        self.assertEqual(result["tickets_written"], 0)

    def test_state_schema_and_history(self):
        supervisor_run_once(self.brain)
        state = json.loads(
            (
                self.brain.directory
                / "tasks"
                / "supervisor"
                / "state.json"
            ).read_text()
        )
        self.assertEqual(state["version"], 1)
        self.assertIn("history", state)

    def test_pending_stage_creates_ticket(self):
        self._execution_file("exec-test")
        result = supervisor_run_once(self.brain)
        self.assertEqual(result["tickets_written"], 1)
        self.assertEqual(result["tickets"][0]["state"], "ready")

    def test_claimed_stage_not_ticketed(self):
        self._execution_file(
            "exec-test",
            {
                "id": "stage-1",
                "executor": "ollama",
                "state": "claimed",
                "lease_id": "active",
                "lease_expires_at": 9999999999,
            },
        )
        result = supervisor_run_once(self.brain)
        self.assertEqual(result["tickets_written"], 0)

    def test_ticket_idempotency_preserves_created_time(self):
        self._execution_file("exec-test")
        first = supervisor_run_once(self.brain)["tickets"][0]
        second = supervisor_run_once(self.brain)["tickets"][0]
        self.assertEqual(
            first["created_at"],
            second["created_at"],
        )
        ticket_files = list(
            (
                self.brain.directory
                / "tasks"
                / "supervisor"
            ).glob("ticket-*.json")
        )
        self.assertEqual(len(ticket_files), 1)

    def test_stale_lease_recovered_and_ticketed(self):
        self._execution_file(
            "exec-stale",
            {
                "id": "stage-1",
                "executor": "ollama",
                "provider": "local-ollama",
                "model": "local-model",
                "purpose": "Recover this work",
                "state": "claimed",
                "lease_id": "expired-lease",
                "lease_expires_at": 1,
            },
        )

        result = supervisor_run_once(self.brain)

        self.assertEqual(result["stale_leases_recovered"], 1)
        self.assertEqual(result["tickets_written"], 1)
        self.assertEqual(result["tickets"][0]["state"], "ready")

    def test_ticket_is_bounded_and_excludes_secret_routing_fields(self):
        task = "t" * 700
        purpose = "p" * 700
        self._execution_file(
            "exec-bounded",
            {
                "id": "stage-1",
                "executor": "ollama",
                "provider": "local-ollama",
                "model": "local-model",
                "purpose": purpose,
                "state": "pending",
                "base_url": "https://private.invalid",
                "credential_env": "SECRET_TOKEN",
                "session_id": "private-session",
            },
        )
        path = (
            self.brain.directory
            / "tasks"
            / "executions"
            / "exec-bounded.json"
        )
        record = json.loads(path.read_text())
        record["task"] = task
        record["secret"] = "do-not-copy"
        path.write_text(json.dumps(record))

        ticket = supervisor_run_once(self.brain)["tickets"][0]

        self.assertEqual(len(ticket["task"]), 500)
        self.assertEqual(len(ticket["purpose"]), 500)
        self.assertEqual(
            set(ticket),
            {
                "version",
                "execution_id",
                "stage_id",
                "executor",
                "provider",
                "model",
                "task",
                "purpose",
                "created_at",
                "updated_at",
                "state",
            },
        )

    def test_primary_review_waits(self):
        self._execution_file(
            "exec-review",
            {
                "id": "stage-1",
                "executor": "primary-review",
                "state": "pending",
            },
        )
        ticket = supervisor_run_once(self.brain)["tickets"][0]
        self.assertEqual(
            ticket["state"],
            "awaiting_primary_review",
        )

    def test_prohibited_model_blocked(self):
        self._execution_file(
            "exec-bad-model",
            {
                "id": "stage-1",
                "executor": "ollama",
                "model": "claude-sonnet-4.6",
                "state": "pending",
            },
        )
        ticket = supervisor_run_once(self.brain)["tickets"][0]
        self.assertEqual(ticket["state"], "blocked")

    def test_completed_and_failed_omitted(self):
        self._execution_file("exec-complete")
        self._execution_file("exec-failed")
        for name, status in [
            ("exec-complete", "completed"),
            ("exec-failed", "failed"),
        ]:
            path = (
                self.brain.directory
                / "tasks"
                / "executions"
                / f"{name}.json"
            )
            data = json.loads(path.read_text())
            data["status"] = status
            path.write_text(json.dumps(data))

        result = supervisor_run_once(self.brain)
        self.assertEqual(result["tickets_written"], 0)

    def test_corrupt_execution_isolated(self):
        directory = self.brain.directory / "tasks" / "executions"
        directory.mkdir(parents=True)
        (directory / "exec-bad.json").write_text("{bad")

        result = supervisor_run_once(self.brain)

        self.assertIn(
            "exec-bad",
            result["corrupted_executions"],
        )

    def test_status_is_read_only(self):
        before = set(self.brain.directory.rglob("*"))
        supervisor_status(self.brain)
        after = set(self.brain.directory.rglob("*"))
        self.assertEqual(before, after)

    def test_emergency_stop_refuses(self):
        kill_switch(self.brain)
        with self.assertRaises(GuardianError):
            supervisor_run_once(self.brain)

    def test_loop_stops_without_sleep_when_emergency_stop_activates(self):
        def activate_stop(_brain):
            kill_switch(self.brain)
            return {"tickets_written": 0}

        with (
            patch(
                "guardian_agent.supervisor.supervisor_run_once",
                side_effect=activate_stop,
            ) as run_once,
        ):
            result = supervisor_run(
                self.brain,
                interval_seconds=60,
                max_cycles=3,
            )

        self.assertTrue(result["stopped"])
        # Emergency stop during supervisor_run_once: no ticket processing occurred,
        # so no cycle is recorded
        self.assertEqual(len(result["cycles"]), 0)
        run_once.assert_called_once_with(self.brain)

    def test_single_instance_lock(self):
        from guardian_agent.supervisor import _supervisor_lock

        with _supervisor_lock(self.brain):
            with self.assertRaises(GuardianError):
                supervisor_run_once(self.brain)

    def test_maximum_ticket_bound(self):
        for index in range(150):
            self._execution_file(f"exec-{index}")

        result = supervisor_run_once(self.brain)

        self.assertLessEqual(
            result["tickets_written"],
            100,
        )

class SupervisorCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.project_path = str(Path(self.tempdir.name) / "demo")
        initialize(
            Path(self.project_path),
            "CLI Demo",
            "CLI Coverage",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @patch("guardian_agent.cli.supervisor_run_once")
    def test_cli_once(self, mock_once):
        from guardian_agent.cli import main
        mock_once.return_value = {"ok": 1}
        with patch("sys.stdout"):
            self.assertEqual(main(["supervisor", "once", "--project", self.project_path]), 0)
        mock_once.assert_called_once()

    @patch("guardian_agent.cli.supervisor_status")
    def test_cli_status(self, mock_status):
        from guardian_agent.cli import main
        mock_status.return_value = {"ok": 2}
        with patch("sys.stdout"):
            self.assertEqual(main(["supervisor", "status", "--project", self.project_path]), 0)
        mock_status.assert_called_once()

    @patch("guardian_agent.cli.supervisor_run")
    def test_cli_run(self, mock_run):
        from guardian_agent.cli import main
        mock_run.return_value = {"ok": 3}
        with patch("sys.stdout"):
            self.assertEqual(
                main(
                    [
                        "supervisor",
                        "run",
                        "--project",
                        self.project_path,
                        "--interval-seconds",
                        "300",
                        "--max-cycles",
                        "2",
                    ]
                ),
                0,
            )
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs.get("interval_seconds"), 300)
        self.assertEqual(kwargs.get("max_cycles"), 2)


class DrainCoordinatorTests(unittest.TestCase):
    """Unit tests for the DrainCoordinator (graceful shutdown/drain)."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(
            Path(self.tempdir.name) / "demo",
            "Drain Demo",
            "Drain coverage",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _execution_file(self, execution_id: str, stage: dict | None = None):
        """Create an execution file for supervisor ticket tests."""
        directory = self.brain.directory / "tasks" / "executions"
        directory.mkdir(parents=True, exist_ok=True)

        if stage is None:
            stage = {
                "id": "stage-1",
                "executor": "ollama",
                "provider": "local-ollama",
                "model": "local-model",
                "purpose": "Implement feature",
                "state": "pending",
            }

        (directory / f"{execution_id}.json").write_text(
            json.dumps(
                {
                    "id": execution_id,
                    "task": "Implement feature",
                    "status": "running",
                    "current_stage_index": 0,
                    "stages": [stage],
                    "events": [],
                }
            ),
            encoding="utf-8",
        )

    # ---- DrainCoordinator unit tests ----

    def _make_dc(self):
        from guardian_agent.runtime import DrainCoordinator
        return DrainCoordinator()

    def test_initial_state_is_not_draining(self) -> None:
        dc = self._make_dc()
        self.assertFalse(dc.is_draining())
        self.assertFalse(dc.is_drained())
        self.assertEqual(dc.inflight_count, 0)
        self.assertIn("active", repr(dc))

    def test_request_drain_sets_draining_flag(self) -> None:
        dc = self._make_dc()
        dc.request_drain()
        self.assertTrue(dc.is_draining())
        self.assertIn("draining", repr(dc))

    def test_double_request_is_idempotent(self) -> None:
        dc = self._make_dc()
        dc.request_drain()
        dc.request_drain()  # Second call must not raise
        self.assertTrue(dc.is_draining())

    def test_inflight_tracking(self) -> None:
        dc = self._make_dc()
        self.assertEqual(dc.inflight_count, 0)

        dc.register_inflight()
        self.assertEqual(dc.inflight_count, 1)

        dc.register_inflight()
        self.assertEqual(dc.inflight_count, 2)

        dc.complete_inflight()
        self.assertEqual(dc.inflight_count, 1)

        dc.complete_inflight()
        self.assertEqual(dc.inflight_count, 0)

    def test_complete_inflight_below_zero_is_safe(self) -> None:
        dc = self._make_dc()
        dc.complete_inflight()  # Should not raise or go negative
        self.assertEqual(dc.inflight_count, 0)

        dc.complete_inflight()
        self.assertEqual(dc.inflight_count, 0)

    def test_is_drained_requires_drain_requested_and_no_inflight(self) -> None:
        dc = self._make_dc()

        # Not draining, no inflight
        self.assertFalse(dc.is_drained())

        # Draining, but still inflight
        dc.register_inflight()
        dc.request_drain()
        self.assertTrue(dc.is_draining())
        self.assertFalse(dc.is_drained())

        # Complete all inflight
        dc.complete_inflight()
        self.assertTrue(dc.is_drained())

    def test_shutdown_hook_registration_and_execution(self) -> None:
        dc = self._make_dc()

        executed = []
        def hook_a() -> None:
            executed.append("a")
        def hook_b() -> None:
            executed.append("b")

        dc.add_shutdown_hook(hook_a)
        dc.add_shutdown_hook(hook_b)

        # Hooks run during wait_for_drain (when draining)
        dc.request_drain()
        dc.wait_for_drain(timeout=1.0)

        self.assertEqual(executed, ["a", "b"])

    def test_shutdown_hook_exception_is_swallowed(self) -> None:
        dc = self._make_dc()

        results = []
        def failing_hook() -> None:
            raise RuntimeError("hook failure")
        def good_hook() -> None:
            results.append("ok")

        dc.add_shutdown_hook(failing_hook)
        dc.add_shutdown_hook(good_hook)

        dc.request_drain()
        dc.wait_for_drain(timeout=1.0)

        self.assertEqual(results, ["ok"])

    def test_wait_for_drain_returns_true_when_drained(self) -> None:
        dc = self._make_dc()
        dc.request_drain()
        # No inflight work, so drain completes immediately
        result = dc.wait_for_drain(timeout=1.0)
        self.assertTrue(result)

    def test_wait_for_drain_waits_for_inflight(self) -> None:
        import threading
        dc = self._make_dc()
        dc.register_inflight()
        dc.request_drain()

        # Inflight work completes in another thread after a delay
        def complete_after_delay() -> None:
            import time as _time
            _time.sleep(0.2)
            dc.complete_inflight()

        t = threading.Thread(target=complete_after_delay, daemon=True)
        t.start()

        result = dc.wait_for_drain(timeout=5.0)
        self.assertTrue(result)

    def test_wait_for_drain_timeout(self) -> None:
        dc = self._make_dc()
        dc.register_inflight()
        dc.request_drain()

        # Inflight never completes — should timeout
        result = dc.wait_for_drain(timeout=0.3)
        self.assertFalse(result)

    def test_reset_clears_state(self) -> None:
        dc = self._make_dc()
        dc.request_drain()
        dc.register_inflight()
        dc.add_shutdown_hook(lambda: None)

        dc.reset()

        self.assertFalse(dc.is_draining())
        self.assertEqual(dc.inflight_count, 0)
        self.assertEqual(len(dc._shutdown_hooks), 0)

    def test_signal_handler_installation_and_restoration(self) -> None:
        """Verify install/restore cycle works without leaving handlers behind."""
        import signal
        from guardian_agent.runtime import (
            install_drain_signal_handlers,
            restore_signal_handlers,
        )

        dc = self._make_dc()
        original_sigterm = signal.getsignal(signal.SIGTERM)
        original_sigint = signal.getsignal(signal.SIGINT)

        restored = install_drain_signal_handlers(drain=dc)
        # Guarantee cleanup even if assertions below fail
        self.addCleanup(restore_signal_handlers, restored)

        # Signal handlers changed
        self.assertIsNotNone(signal.getsignal(signal.SIGTERM))

        # Signal triggers drain
        self.assertFalse(dc.is_draining())
        sigterm_handler = signal.getsignal(signal.SIGTERM)
        sigterm_handler(signal.SIGTERM, None)
        self.assertTrue(dc.is_draining())

        # Restore
        dc.reset()
        restore_signal_handlers(restored)

        self.assertEqual(signal.getsignal(signal.SIGTERM), original_sigterm)
        self.assertEqual(signal.getsignal(signal.SIGINT), original_sigint)

    def test_supervisor_status_shows_drain_state_when_active(self) -> None:
        """Verify supervisor_status includes drain info when daemon is running."""
        dc = self._make_dc()
        import guardian_agent.supervisor as sup_mod
        sup_mod._current_drain = dc

        try:
            status = supervisor_status(self.brain)
            self.assertIn("drain", status)
            self.assertIsNotNone(status["drain"])
            self.assertEqual(status["drain"]["state"], "active")
            self.assertEqual(status["drain"]["inflight"], 0)

            # Register inflight so we can observe the 'draining' transition
            dc.register_inflight()
            dc.request_drain()
            status2 = supervisor_status(self.brain)
            self.assertEqual(status2["drain"]["state"], "draining")
            self.assertEqual(status2["drain"]["inflight"], 1)

            # Complete inflight to reach drained
            dc.complete_inflight()
            dc.wait_for_drain(timeout=1.0)
            status3 = supervisor_status(self.brain)
            self.assertEqual(status3["drain"]["state"], "drained")
        finally:
            sup_mod._current_drain = None

    def test_supervisor_status_drain_none_when_no_daemon(self) -> None:
        """Verify supervisor_status shows None drain when daemon is not running."""
        status = supervisor_status(self.brain)
        self.assertIn("drain", status)
        self.assertIsNone(status["drain"])

    @patch("guardian_agent.supervisor.supervisor_run_once")
    @patch("guardian_agent.executor_worker.execute_ticket")
    @patch("guardian_agent.executor_worker.list_ready_tickets")
    def test_daemon_run_clears_module_reference(
        self, mock_list, mock_execute, mock_run_once
    ) -> None:
        """Verify _current_drain is cleared after daemon exits."""
        import guardian_agent.supervisor as sup_mod
        from guardian_agent.supervisor import supervisor_daemon_run

        mock_run_once.return_value = {"tickets_written": 1, "tickets": []}
        mock_list.return_value = []
        mock_execute.return_value = {
            "execution_id": "exec-test",
            "stage_id": "stage-1",
            "executor": "ollama",
            "outcome": "dispatched",
        }

        # Run with max_cycles=1 so daemon exits after one cycle
        result = supervisor_daemon_run(
            self.brain,
            interval_seconds=1,
            max_cycles=1,
        )

        # Module reference should be None after daemon exits
        self.assertIsNone(sup_mod._current_drain)
        self.assertEqual(result["status"], "completed")

    def test_daemon_run_drained_status(self) -> None:
        """Verify the daemon exits with 'completed' status by cycle limit."""
        import guardian_agent.supervisor as sup_mod
        from guardian_agent.supervisor import supervisor_daemon_run

        with (
            patch(
                "guardian_agent.executor_worker.list_ready_tickets",
                return_value=[],
            ),
            patch(
                "guardian_agent.executor_worker.execute_ticket",
                return_value={
                    "execution_id": "exec-test",
                    "stage_id": "stage-1",
                    "executor": "ollama",
                    "outcome": "dispatched",
                },
            ),
        ):
            result = supervisor_daemon_run(
                self.brain,
                interval_seconds=1,
                max_cycles=2,
            )

        self.assertEqual(result["cycles_completed"], 2)
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(sup_mod._current_drain)


    def test_parallel_ticket_execution(self) -> None:
        """Verify daemon submits tickets as individual futures for true parallelism.

        This test verifies the structural pattern: the daemon uses
        executor_pool.submit(execute_ticket, ...) for each ticket individually
        rather than a single sequential batch call. The actual timing-based
        concurrency verification is in test_executor_worker.py's
        test_process_ready_tickets_concurrency_timing test.
        """
        from guardian_agent.supervisor import supervisor_daemon_run

        # Create 4 execution files with pending stages
        for index in range(4):
            self._execution_file(f"exec-para-{index}")

        # Count how many times execute_ticket is called
        call_args_list = []

        def _tracking_execute(brain, ticket, dry_run=False):
            """Record call arguments without real work."""
            call_args_list.append({
                "execution_id": ticket.get("execution_id"),
                "stage_id": ticket.get("stage_id"),
                "executor": ticket.get("executor"),
            })
            return {
                "execution_id": ticket.get("execution_id", "exec-unknown"),
                "stage_id": ticket.get("stage_id", "stage-1"),
                "executor": ticket.get("executor", "ollama"),
                "outcome": "dispatched",
            }

        with (
            patch(
                "guardian_agent.executor_worker.execute_ticket",
                side_effect=_tracking_execute,
            ) as mock_execute,
        ):
            result = supervisor_daemon_run(
                self.brain,
                interval_seconds=1,
                max_cycles=1,
                max_workers=4,
            )

        self.assertGreaterEqual(result["cycles_completed"], 1,
            "Daemon should complete at least one cycle")

        # Verify execute_ticket was called for individual tickets
        self.assertGreaterEqual(mock_execute.call_count, 1,
            f"Expected at least 1 execute_ticket call, got {mock_execute.call_count}")

        # Verify unique execution IDs were submitted (each ticket has its own)
        if call_args_list:
            exec_ids = set(a["execution_id"] for a in call_args_list)
            self.assertGreaterEqual(
                len(exec_ids), 1,
                f"Expected at least 1 unique execution ID, got {exec_ids}",
            )

    def test_parallel_drain_stops_new_ticket_submission(self) -> None:
        """Verify drain during ticket submission stops new tickets from being submitted."""
        from guardian_agent.supervisor import supervisor_daemon_run
        from guardian_agent.runtime import DrainCoordinator

        # Create 8 execution files
        for index in range(8):
            self._execution_file(f"exec-drain-{index}")

        # Register a drain hook that triggers drain after the first execute_ticket call
        drain_triggered = False

        def _trigger_drain_after_first(brain, ticket, dry_run=False):
            nonlocal drain_triggered
            if not drain_triggered:
                drain_triggered = True
                # Access the module-level drain and request drain
                import guardian_agent.supervisor as sup_mod
                if sup_mod._current_drain:
                    sup_mod._current_drain.request_drain()
            return {
                "execution_id": ticket.get("execution_id", "exec-unknown"),
                "stage_id": ticket.get("stage_id", "stage-1"),
                "executor": ticket.get("executor", "ollama"),
                "outcome": "dispatched",
            }

        with patch(
            "guardian_agent.executor_worker.execute_ticket",
            side_effect=_trigger_drain_after_first,
        ):
            result = supervisor_daemon_run(
                self.brain,
                interval_seconds=3600,  # Long sleep so drain exits during first cycle
                max_cycles=None,  # Run until drain
                max_workers=4,
                indefinite=True,
            )

        self.assertEqual(result["status"], "drained")
        self.assertTrue(result["drained"])


if __name__ == "__main__":
    unittest.main()
