"""Tests for the Hermes safe adapter (Phase 5 & 6)."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from guardian_agent.core import GuardianError, initialize
from guardian_agent.hermes import (
    _HERMES_RESTRICTIONS,
    _ALLOWED_TASK_TYPES,
    _ALLOWED_SCHEDULED_TASK_TYPES,
    create_hermes_handoff,
    execute_hermes_task,
    hermes_is_opted_in,
    hermes_opt_in,
    hermes_status,
    hermes_schedule_task,
    hermes_list_scheduled,
    hermes_unschedule_task,
    hermes_run_due_tasks,
    list_hermes_memory,
    import_hermes_lesson,
)


# =====================================================================
# Phase 5 — Binary detection and status
# =====================================================================

class HermesStatusTests(unittest.TestCase):
    """Tests for binary detection, version, and timeout handling."""

    @patch("guardian_agent.hermes._hermes_path", return_value=None)
    def test_binary_absence_reported_safely(self, _path) -> None:
        """Status must report available=False when binary is missing."""
        result = hermes_status()
        self.assertFalse(result["available"])
        self.assertIsNone(result["executable"])
        self.assertIsNone(result["version"])
        self.assertIn("not found", result["message"].lower())

    @patch("guardian_agent.hermes._hermes_path", return_value="/usr/bin/hermes")
    @patch("guardian_agent.hermes.subprocess.run")
    def test_version_read_with_timeout(self, run, _path) -> None:
        """Version is read successfully when binary responds."""
        run.return_value.stdout = "Hermes 0.2.0\n"
        run.return_value.returncode = 0
        result = hermes_status()
        self.assertTrue(result["available"])
        self.assertEqual(result["version"], "Hermes 0.2.0")

    @patch("guardian_agent.hermes._hermes_path", return_value="/usr/bin/hermes")
    @patch("guardian_agent.hermes.subprocess.run")
    def test_timeout_reported_safely(self, run, _path) -> None:
        """Timeout or subprocess error sets available=False gracefully."""
        run.side_effect = TimeoutError("timed out")
        result = hermes_status()
        self.assertFalse(result["available"])
        self.assertEqual(result["executable"], "/usr/bin/hermes")
        self.assertIsNone(result["version"])

    def test_restrictions_always_present(self) -> None:
        """Status always returns the full restrictions list."""
        result = hermes_status()
        self.assertIn("restrictions", result)
        self.assertGreater(len(result["restrictions"]), 0)
        self.assertIn("no-browser", result["restrictions"])
        self.assertIn("no-messaging-gateway", result["restrictions"])
        self.assertIn("no-external-actions", result["restrictions"])
        self.assertIn("no-self-development", result["restrictions"])


# =====================================================================
# Phase 5 — Handoff creation
# =====================================================================

class HermesHandoffTests(unittest.TestCase):
    """Tests for handoff creation, task types, and restrictions."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Hermes Demo", "Hermes test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_handoff_created_with_task(self) -> None:
        """Handoff file is created and contains the task description."""
        result = create_hermes_handoff(self.brain, "Research authentication methods", task_type="research")
        handoff = Path(result["handoff"])
        self.assertTrue(handoff.is_file())
        text = handoff.read_text(encoding="utf-8")
        self.assertIn("Research authentication methods", text)
        self.assertIn("Hermes Bounded Work Handoff", text)

    def test_handoff_includes_restrictions(self) -> None:
        """Handoff document lists all enforced restrictions."""
        result = create_hermes_handoff(self.brain, "Plan project structure", task_type="planning")
        text = Path(result["handoff"]).read_text(encoding="utf-8")
        for restriction in _HERMES_RESTRICTIONS:
            self.assertIn(restriction, text)

    def test_handoff_mentions_tools_disabled(self) -> None:
        """Handoff must mention tools-disabled profile."""
        result = create_hermes_handoff(self.brain, "Analyze code quality", task_type="skill-evaluation")
        text = Path(result["handoff"]).read_text(encoding="utf-8")
        self.assertIn("tools-disabled", text.lower())
        self.assertIn("no-browser", text.lower())

    def test_empty_task_rejected(self) -> None:
        """Empty task must raise GuardianError."""
        with self.assertRaises(GuardianError):
            create_hermes_handoff(self.brain, "")

    def test_invalid_task_type_rejected(self) -> None:
        """Unsupported task type must raise GuardianError."""
        with self.assertRaises(GuardianError) as cm:
            create_hermes_handoff(self.brain, "Do something", task_type="coding")
        self.assertIn("Unsupported", str(cm.exception))

    def test_all_allowed_task_types_work(self) -> None:
        """All allowed task types should produce valid handoffs."""
        for task_type in _ALLOWED_TASK_TYPES:
            result = create_hermes_handoff(
                self.brain, f"Test {task_type}", task_type=task_type
            )
            self.assertTrue(Path(result["handoff"]).is_file())
            self.assertEqual(result["task_type"], task_type)

    def test_handoff_includes_task_type(self) -> None:
        """Handoff should contain the task type."""
        result = create_hermes_handoff(self.brain, "Research security", task_type="research")
        self.assertEqual(result["task_type"], "research")
        text = Path(result["handoff"]).read_text(encoding="utf-8")
        self.assertIn("Task: research", text)

    def test_handoff_with_read_paths(self) -> None:
        """Read paths should be listed in the handoff when provided."""
        # Create a test file that can be referenced
        test_file = self.brain.root / "src" / "test.txt"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("test content", encoding="utf-8")

        result = create_hermes_handoff(
            self.brain, "Read and analyze",
            read_paths=["src/test.txt"],
        )
        text = Path(result["handoff"]).read_text(encoding="utf-8")
        self.assertIn("src/test.txt", text)


# =====================================================================
# Phase 5 — Opt-in and consent
# =====================================================================

class HermesOptInTests(unittest.TestCase):
    """Tests for explicit user opt-in."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Hermes OptIn", "Opt-in tests")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_opt_in_not_granted_by_default(self) -> None:
        """Hermes execution should not be opted in by default."""
        self.assertFalse(hermes_is_opted_in(self.brain))

    def test_opt_in_records_consent(self) -> None:
        """Opt-in should record consent and return success."""
        result = hermes_opt_in(self.brain)
        self.assertEqual(result["status"], "opted_in")
        self.assertTrue(hermes_is_opted_in(self.brain))

    def test_opt_in_idempotent(self) -> None:
        """Calling opt-in twice should return 'already_opted_in'."""
        hermes_opt_in(self.brain)
        result = hermes_opt_in(self.brain)
        self.assertEqual(result["status"], "already_opted_in")

    def test_execution_blocked_without_opt_in(self) -> None:
        """execute_hermes_task must raise if opt-in not granted."""
        with self.assertRaises(GuardianError) as ctx:
            execute_hermes_task(self.brain, "Research auth")
        self.assertIn("opt-in", str(ctx.exception).lower())


# =====================================================================
# Phase 5 — Execution
# =====================================================================

class HermesExecutionTests(unittest.TestCase):
    """Tests for execution, timeout, stdout/stderr capture."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Hermes Exec", "Execution tests")
        hermes_opt_in(self.brain)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @patch("guardian_agent.hermes._hermes_path", return_value=None)
    def test_binary_not_found_raises(self, _path) -> None:
        """Execution should raise if Hermes binary is missing."""
        with self.assertRaises(GuardianError):
            execute_hermes_task(self.brain, "Research auth")

    @patch("guardian_agent.hermes._hermes_path", return_value="/usr/bin/hermes")
    @patch("guardian_agent.hermes.subprocess.run")
    def test_execution_captures_stdout_stderr(self, mock_run, _path) -> None:
        """Execution should capture stdout and stderr."""
        mock_run.return_value.stdout = "Research findings...\nKey insight: use OAuth2."
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0

        result = execute_hermes_task(
            self.brain, "Research auth methods",
            task_type="research", timeout=60,
        )
        self.assertEqual(result["execution"]["exit_code"], 0)
        self.assertIn("Research findings", result["execution"]["stdout"])
        self.assertIn("memory_output", result)
        self.assertIn("memory_path", result)

    @patch("guardian_agent.hermes._hermes_path", return_value="/usr/bin/hermes")
    @patch("guardian_agent.hermes.subprocess.run")
    def test_execution_saves_to_isolated_memory(self, mock_run, _path) -> None:
        """Execution output should be saved to Hermes isolated memory."""
        mock_run.return_value.stdout = "Planning output."
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0

        result = execute_hermes_task(
            self.brain, "Plan implementation",
            task_type="planning", timeout=60,
        )
        memory_file = Path(result["memory_output"])
        self.assertTrue(memory_file.is_file())
        content = memory_file.read_text(encoding="utf-8")
        self.assertIn("Hermes Output", content)
        self.assertIn("Planning output", content)
        self.assertIn("Plan implementation", content)

    @patch("guardian_agent.hermes._hermes_path", return_value="/usr/bin/hermes")
    @patch("guardian_agent.hermes.subprocess.run")
    def test_timeout_reported_gracefully(self, mock_run, _path) -> None:
        """Execution timeout should be reported gracefully."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="hermes", timeout=10, output="", stderr=""
        )

        result = execute_hermes_task(
            self.brain, "Research quick",
            task_type="research", timeout=10,
        )
        self.assertTrue(result["execution"]["timed_out"])
        self.assertIn("timed out", result["execution"]["stderr"].lower())

    @patch("guardian_agent.hermes._hermes_path", return_value="/usr/bin/hermes")
    @patch("guardian_agent.hermes.subprocess.run")
    def test_telemetry_disabled_by_default(self, mock_run, _path) -> None:
        """Hermes should run with HERMES_NO_TELEMETRY=1 and TOOLS_DISABLED=1."""
        from unittest.mock import MagicMock

        def _check_env(*args, **kwargs):
            env = kwargs.get("env", {})
            self.assertEqual(env.get("HERMES_NO_TELEMETRY"), "1")
            self.assertEqual(env.get("HERMES_TOOLS_DISABLED"), "1")
            self.assertNotIn("HERMES_API_KEY", env)
            return MagicMock(stdout="OK", stderr="", returncode=0)
        mock_run.side_effect = _check_env

        result = execute_hermes_task(
            self.brain, "Research", task_type="research", timeout=60,
        )
        self.assertEqual(result["execution"]["exit_code"], 0)


# =====================================================================
# Phase 5 — Memory isolation
# =====================================================================

class HermesMemoryIsolationTests(unittest.TestCase):
    """Tests for isolated Hermes memory and lesson import."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Hermes Mem", "Memory tests")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_memory_directory_created(self) -> None:
        """Hermes memory directory should be created when listed."""
        result = list_hermes_memory(self.brain)
        self.assertIn("memory_path", result)
        self.assertTrue(Path(result["memory_path"]).is_dir())
        self.assertEqual(result["file_count"], 0)

    def test_memory_stores_separate_from_guardian(self) -> None:
        """Hermes memory should be in a subdirectory of .agent/ named hermes_memory."""
        from guardian_agent.hermes import _hermes_memory_path
        mem_path = _hermes_memory_path(self.brain)
        self.assertEqual(mem_path.name, "hermes_memory")
        self.assertIn(".agent", str(mem_path))

    def test_import_lesson_without_source_raises(self) -> None:
        """Importing a non-existent memory file should raise GuardianError."""
        with self.assertRaises(GuardianError) as cm:
            import_hermes_lesson(
                self.brain, "nonexistent.md",
                sanitized_pattern="Use async/await for I/O",
                sanitized_prevention="Check for blocking I/O calls in hot paths",
                tags=["async", "performance"],
            )
        self.assertIn("not found", str(cm.exception))

    def test_import_lesson_creates_reusable_lesson(self) -> None:
        """Importing a sanitized lesson should create a reusable lesson in the library."""
        from guardian_agent.hermes import _hermes_memory_path
        mem_path = _hermes_memory_path(self.brain)
        source = mem_path / "research_output.md"
        source.write_text("# Test output\nSome research findings.\n", encoding="utf-8")

        result = import_hermes_lesson(
            self.brain, "research_output.md",
            sanitized_pattern="Use environment variables for configuration",
            sanitized_prevention="Check for hardcoded config values before deployment",
            tags=["config", "security"],
        )
        self.assertEqual(result["status"], "imported")
        self.assertIn("lesson_id", result)
        self.assertIn("hermes-import-", result["lesson_id"])


# =====================================================================
# Phase 6 — Scheduled tasks
# =====================================================================

class HermesScheduleTests(unittest.TestCase):
    """Tests for Phase 6 scheduled background tasks."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Hermes Sched", "Schedule tests")
        # Create and approve a real approval for scheduling
        from guardian_agent.policy import request_action_approval, approve_action_request
        req = request_action_approval(
            self.brain, "hermes_schedule", "hermes:health-check",
            "Test schedule approval", account_id="test", connector_scope="hermes",
        )
        self.approval_id = req["id"]
        approve_action_request(self.brain, self.approval_id)
        hermes_opt_in(self.brain)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_schedule_requires_approved_task_type(self) -> None:
        """Scheduling an unsupported task type should raise GuardianError."""
        with self.assertRaises(GuardianError) as cm:
            hermes_schedule_task(
                self.brain, "coding-task", "Do some coding",
                interval_seconds=3600, approval_id=self.approval_id,
            )
        self.assertIn("Unsupported", str(cm.exception))

    def test_all_scheduled_types_allowed(self) -> None:
        """All scheduled task types should be schedulable."""
        for sched_type in _ALLOWED_SCHEDULED_TASK_TYPES:
            from guardian_agent.policy import request_action_approval, approve_action_request
            req = request_action_approval(
                self.brain, "hermes_schedule", f"hermes:{sched_type}",
                f"Test {sched_type} schedule",
                account_id="test", connector_scope="hermes",
            )
            approve_action_request(self.brain, req["id"])
            result = hermes_schedule_task(
                self.brain, sched_type, f"Run {sched_type}",
                interval_seconds=3600, approval_id=req["id"],
            )
            self.assertEqual(result["type"], sched_type)
            self.assertTrue(result["enabled"])

    def test_schedule_requires_minimum_interval(self) -> None:
        """Interval must be at least 300 seconds."""
        from guardian_agent.policy import request_action_approval, approve_action_request
        req = request_action_approval(
            self.brain, "hermes_schedule", "hermes:health-check",
            "Short interval test",
            account_id="test", connector_scope="hermes",
        )
        approve_action_request(self.brain, req["id"])
        with self.assertRaises(GuardianError) as cm:
            hermes_schedule_task(
                self.brain, "health-check", "Quick check",
                interval_seconds=30, approval_id=req["id"],
            )
        self.assertIn("at least 300 seconds", str(cm.exception))

    def test_list_scheduled_tasks(self) -> None:
        """Listing scheduled tasks should return added tasks."""
        result = hermes_schedule_task(
            self.brain, "health-check", "Check system health",
            interval_seconds=3600, approval_id=self.approval_id,
        )
        task_id = result["id"]

        lst = hermes_list_scheduled(self.brain)
        self.assertGreaterEqual(lst["task_count"], 1)
        self.assertIn(task_id, [t["id"] for t in lst["tasks"]])

    def test_unschedule_task(self) -> None:
        """Unschedule should disable the task."""
        from guardian_agent.policy import request_action_approval, approve_action_request
        req2 = request_action_approval(
            self.brain, "hermes_schedule", "hermes:research-summary",
            "Test unschedule", account_id="test", connector_scope="hermes",
        )
        approve_action_request(self.brain, req2["id"])

        result = hermes_schedule_task(
            self.brain, "research-summary", "Summarize latest",
            interval_seconds=7200, approval_id=req2["id"],
        )
        task_id = result["id"]

        unsched = hermes_unschedule_task(self.brain, task_id)
        self.assertEqual(unsched["status"], "disabled")

        lst = hermes_list_scheduled(self.brain)
        task = next(t for t in lst["tasks"] if t["id"] == task_id)
        self.assertFalse(task["enabled"])

    def test_unschedule_unknown_task_raises(self) -> None:
        """Unschedule an unknown task should raise GuardianError."""
        with self.assertRaises(GuardianError):
            hermes_unschedule_task(self.brain, "nonexistent-task-id")


class HermesRunDueTests(unittest.TestCase):
    """Tests for running due scheduled tasks."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Hermes Due", "Due tasks tests")
        from guardian_agent.policy import request_action_approval, approve_action_request
        req = request_action_approval(
            self.brain, "hermes_schedule", "hermes:skill-evaluation",
            "Test run-due", account_id="test", connector_scope="hermes",
        )
        approve_action_request(self.brain, req["id"])
        hermes_opt_in(self.brain)

        # Add a task with past next_run_epoch (due immediately)
        from guardian_agent.hermes import _schedule_path, _load_schedule, _save_schedule
        payload = _load_schedule(self.brain)
        payload["tasks"].append({
            "id": "hermes-sched-test-due",
            "type": "skill-evaluation",
            "description": "Evaluate current skill quality",
            "interval_seconds": 86400,
            "enabled": True,
            "created_at": "now",
            "approval_id": req["id"],
            "last_run_epoch": None,
            "next_run_epoch": 0,  # Due immediately
            "failure_count": 0,
            "last_status": "never",
            "last_error": None,
        })
        _save_schedule(self.brain, payload)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @patch("guardian_agent.hermes._hermes_path", return_value=None)
    def test_run_due_handles_binary_not_found(self, _path) -> None:
        """Running due tasks with no Hermes binary should report failure."""
        result = hermes_run_due_tasks(self.brain, force=True)
        self.assertGreaterEqual(result["executed"], 1)
        for record in result["records"]:
            if record["type"] == "skill-evaluation":
                self.assertEqual(record["status"], "failed")

    def test_run_due_no_tasks(self) -> None:
        """Running with no due tasks should return zero executed."""
        # Create a brain with no due tasks
        tmp2 = tempfile.TemporaryDirectory()
        brain2 = initialize(Path(tmp2.name) / "demo2", "No Tasks", "No tasks test")
        result = hermes_run_due_tasks(brain2)
        self.assertEqual(result["executed"], 0)
        tmp2.cleanup()

    def test_run_due_returns_no_automatic_changes(self) -> None:
        """Due task results should never propose automatic changes."""
        @patch("guardian_agent.hermes._hermes_path", return_value="/usr/bin/hermes")
        @patch("guardian_agent.hermes.subprocess.run")
        def _test(mock_run, _path):
            mock_run.return_value.stdout = "Skill evaluation: all skills are current."
            mock_run.return_value.stderr = ""
            mock_run.return_value.returncode = 0

            result = hermes_run_due_tasks(self.brain, force=True)
            for record in result["records"]:
                self.assertIn("change_proposed", record)
                self.assertFalse(record["change_proposed"])
            return result

        _test()


if __name__ == "__main__":
    unittest.main()
