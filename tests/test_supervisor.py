"""Tests for the bounded Guardian supervisor."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
            patch("guardian_agent.supervisor.time.sleep") as sleep,
        ):
            result = supervisor_run(
                self.brain,
                interval_seconds=60,
                max_cycles=3,
            )

        self.assertTrue(result["stopped"])
        self.assertEqual(len(result["cycles"]), 1)
        run_once.assert_called_once_with(self.brain)
        sleep.assert_not_called()

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

if __name__ == "__main__":
    unittest.main()
