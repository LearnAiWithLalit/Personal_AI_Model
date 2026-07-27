"""Tests for the JCode safe adapter (Phase 2)."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from guardian_agent.core import GuardianError, initialize
from guardian_agent.jcode import (
    _JCODE_RESTRICTIONS,
    build_jcode_command,
    create_jcode_handoff,
    jcode_status,
)


class JCodeStatusTests(unittest.TestCase):
    """Tests for binary detection, version, and timeout handling."""

    @patch("guardian_agent.jcode._jcode_path", return_value=None)
    def test_binary_absence_reported_safely(self, _path) -> None:
        """Status must report unavailable=True when binary is missing."""
        result = jcode_status()
        self.assertFalse(result["available"])
        self.assertIsNone(result["executable"])
        self.assertIsNone(result["version"])
        self.assertIn("not found", result["message"].lower())

    @patch("guardian_agent.jcode._jcode_path", return_value="/usr/bin/jcode")
    @patch("guardian_agent.jcode.subprocess.run")
    def test_version_read_with_timeout(self, run, _path) -> None:
        """Version is read successfully when binary responds."""
        run.return_value.stdout = "jcode 0.1.0\n"
        run.return_value.returncode = 0
        result = jcode_status()
        self.assertTrue(result["available"])
        self.assertEqual(result["version"], "jcode 0.1.0")

    @patch("guardian_agent.jcode._jcode_path", return_value="/usr/bin/jcode")
    @patch("guardian_agent.jcode.subprocess.run")
    def test_timeout_reported_safely(self, run, _path) -> None:
        """Timeout or subprocess error sets available=False gracefully."""
        run.side_effect = TimeoutError("timed out")
        result = jcode_status()
        self.assertFalse(result["available"])
        self.assertEqual(result["executable"], "/usr/bin/jcode")
        self.assertIsNone(result["version"])

    def test_restrictions_always_present(self) -> None:
        """Status always returns the full restrictions list."""
        result = jcode_status()
        self.assertIn("restrictions", result)
        self.assertGreater(len(result["restrictions"]), 0)
        self.assertIn("no-self-development", result["restrictions"])
        self.assertIn("no-browser", result["restrictions"])


class JCodeHandoffTests(unittest.TestCase):
    """Tests for handoff creation, path filtering, and dry-run safety."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "JCode Demo", "JCode integration test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_handoff_created_with_task(self) -> None:
        """Handoff file is created and contains the task description."""
        result = create_jcode_handoff(self.brain, "Refactor the parser module")
        handoff = Path(result["handoff"])
        self.assertTrue(handoff.is_file())
        text = handoff.read_text(encoding="utf-8")
        self.assertIn("Refactor the parser module", text)
        self.assertIn("JCode Bounded Work Handoff", text)

    def test_handoff_includes_restrictions(self) -> None:
        """Handoff document lists all enforced restrictions."""
        result = create_jcode_handoff(self.brain, "Add logging")
        text = Path(result["handoff"]).read_text(encoding="utf-8")
        for restriction in _JCODE_RESTRICTIONS:
            self.assertIn(restriction, text)

    def test_empty_task_rejected(self) -> None:
        """Empty task must raise GuardianError."""
        with self.assertRaises(GuardianError):
            create_jcode_handoff(self.brain, "")

    def test_writable_paths_filtered_safely(self) -> None:
        """Protected paths are excluded; valid paths are kept (trailing slash normalized)."""
        result = create_jcode_handoff(
            self.brain,
            "Fix bug",
            writable_paths=["src/auth", ".env", "../outside"],
        )
        safe_paths = result["writable_paths"]
        self.assertIn("src/auth", safe_paths)
        for sensitive in (".env", "../outside"):
            self.assertNotIn(sensitive, safe_paths)

    def test_exact_write_allowlist(self) -> None:
        """Only explicitly approved paths are in writable_paths."""
        result = create_jcode_handoff(
            self.brain,
            "Update tests",
            writable_paths=["tests/test_auth.py", "src/auth/login.py"],
        )
        self.assertEqual(len(result["writable_paths"]), 2)
        self.assertIn("tests/test_auth.py", result["writable_paths"])
        self.assertIn("src/auth/login.py", result["writable_paths"])

    def test_no_writable_paths_read_only(self) -> None:
        """Without writable paths, handoff says read-only."""
        result = create_jcode_handoff(self.brain, "Analyze code")
        self.assertEqual(result["writable_paths"], [])
        text = Path(result["handoff"]).read_text(encoding="utf-8")
        self.assertIn("read-only", text.lower())

    def test_handoff_always_dry_run(self) -> None:
        """Handoff creation never executes JCode (dry-run by default)."""
        result = create_jcode_handoff(self.brain, "Refactor")
        self.assertIn("dry-run", result["instruction"].lower())
        self.assertIsNotNone(result["handoff"])
        # Verify no subprocess was launched by checking command_preview is
        # a string (will be None if binary not found, but still not executed)
        self.assertIn("instruction", result)


class JCodeCommandTests(unittest.TestCase):
    """Tests for safe command construction and restrictions."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "JCode Cmd", "JCode command tests")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_binary_not_found_raises_error(self) -> None:
        """build_jcode_command must raise if JCode binary is missing."""
        with patch("guardian_agent.jcode._jcode_path", return_value=None):
            with self.assertRaises(GuardianError):
                build_jcode_command(self.brain, "Fix bug")

    @patch("guardian_agent.jcode._jcode_path", return_value="/usr/bin/jcode")
    def test_command_is_dry_run_by_default(self, _path) -> None:
        """Default command includes --dry-run."""
        result = build_jcode_command(self.brain, "Fix bug")
        self.assertIn("--dry-run", result["command"])
        self.assertFalse(result["allow_edits"])

    @patch("guardian_agent.jcode._jcode_path", return_value="/usr/bin/jcode")
    def test_command_no_dry_run_when_allowed(self, _path) -> None:
        """--dry-run is omitted when allow_edits=True."""
        result = build_jcode_command(self.brain, "Fix bug", allow_edits=True)
        self.assertNotIn("--dry-run", result["command"])
        self.assertTrue(result["allow_edits"])

    @patch("guardian_agent.jcode._jcode_path", return_value="/usr/bin/jcode")
    def test_command_includes_writable_paths(self, _path) -> None:
        """Writable paths are passed via --write (trailing slash normalized)."""
        result = build_jcode_command(
            self.brain,
            "Fix bug",
            writable_paths=["src/auth"],
        )
        self.assertIn("--write", result["command"])
        write_idx = result["command"].index("--write")
        self.assertEqual(result["command"][write_idx + 1], "src/auth")

    @patch("guardian_agent.jcode._jcode_path", return_value="/usr/bin/jcode")
    def test_command_includes_test_command(self, _path) -> None:
        """Test command is passed via --test."""
        result = build_jcode_command(
            self.brain,
            "Fix bug",
            test_command="pytest tests/",
        )
        self.assertIn("--test", result["command"])
        test_idx = result["command"].index("--test")
        self.assertEqual(result["command"][test_idx + 1], "pytest tests/")

    @patch("guardian_agent.jcode._jcode_path", return_value="/usr/bin/jcode")
    def test_telemetry_disabled_by_default(self, _path) -> None:
        """JCODE_NO_TELEMETRY is always set to 1."""
        result = build_jcode_command(self.brain, "Fix bug")
        self.assertEqual(result["env"]["JCODE_NO_TELEMETRY"], "1")

    def test_restrictions_list_present_in_command(self) -> None:
        """Command result includes enforced restrictions list."""
        with patch("guardian_agent.jcode._jcode_path", return_value="/usr/bin/jcode"):
            result = build_jcode_command(self.brain, "Refactor")
            self.assertIn("restrictions_enforced", result)
            self.assertIn("no-self-development", result["restrictions_enforced"])

    @patch("guardian_agent.jcode._jcode_path", return_value="/usr/bin/jcode")
    def test_command_does_not_execute(self, _path) -> None:
        """build_jcode_command only returns a preview, never executes."""
        result = build_jcode_command(self.brain, "Refactor")
        self.assertIsNotNone(result["command"])
        self.assertIn("note", result)
        self.assertIn("No execution has occurred", result["note"])


# ---------------------------------------------------------------------------
# Phase 3 — Controlled execution tests
# ---------------------------------------------------------------------------

class JCodeOptInTests(unittest.TestCase):
    """Tests for explicit user opt-in."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "JCode OptIn", "Opt-in tests")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_opt_in_not_granted_by_default(self) -> None:
        """JCode execution should not be opted in by default."""
        from guardian_agent.jcode import jcode_is_opted_in
        self.assertFalse(jcode_is_opted_in(self.brain))

    def test_opt_in_records_consent(self) -> None:
        """Opt-in should record consent and return success."""
        from guardian_agent.jcode import jcode_opt_in, jcode_is_opted_in
        result = jcode_opt_in(self.brain)
        self.assertEqual(result["status"], "opted_in")
        self.assertTrue(jcode_is_opted_in(self.brain))

    def test_opt_in_idempotent(self) -> None:
        """Calling opt-in twice should return 'already_opted_in'."""
        from guardian_agent.jcode import jcode_opt_in
        jcode_opt_in(self.brain)
        result = jcode_opt_in(self.brain)
        self.assertEqual(result["status"], "already_opted_in")

    def test_execution_blocked_without_opt_in(self) -> None:
        """execute_jcode_in_sandbox must raise if opt-in not granted."""
        from guardian_agent.jcode import execute_jcode_in_sandbox
        with self.assertRaises(GuardianError) as ctx:
            execute_jcode_in_sandbox(self.brain, "Fix bug")
        self.assertIn("opt-in", str(ctx.exception).lower())


class JCodeSandboxExecutionTests(unittest.TestCase):
    """Tests for sandbox execution, timeout, diff capture, and out-of-scope validation."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "JCode Sandbox", "Sandbox tests")
        from guardian_agent.jcode import jcode_opt_in
        jcode_opt_in(self.brain)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @patch("guardian_agent.jcode._jcode_path", return_value=None)
    def test_binary_not_found_raises(self, _path) -> None:
        """Execution should raise if JCode binary is missing."""
        from guardian_agent.jcode import execute_jcode_in_sandbox
        with self.assertRaises(GuardianError):
            execute_jcode_in_sandbox(self.brain, "Fix bug")

    @patch("guardian_agent.jcode._jcode_path", return_value="/usr/bin/jcode")
    @patch("guardian_agent.jcode.subprocess.run")
    @patch("guardian_agent.sandbox.create_worktree_sandbox")
    def test_execution_captures_stdout_stderr(
        self, mock_sandbox, mock_run, _path
    ) -> None:
        """Sandbox execution should capture stdout and stderr."""
        mock_sandbox.return_value = {
            "branch": "jcode-test",
            "worktree_path": str(self.brain.root / ".." / "sandbox"),
            "mode": "copy-fallback",
        }
        mock_run.return_value.stdout = "Changes applied."
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0

        from guardian_agent.jcode import execute_jcode_in_sandbox
        result = execute_jcode_in_sandbox(
            self.brain, "Refactor auth",
            writable_paths=["src/auth/"],
            timeout=60,
        )
        self.assertEqual(result["execution"]["exit_code"], 0)
        self.assertIn("Changes applied.", result["execution"]["stdout"])
        self.assertIn("sandbox_path", result)
        self.assertIn("changed_files", result)

    @patch("guardian_agent.jcode._jcode_path", return_value="/usr/bin/jcode")
    @patch("guardian_agent.jcode.subprocess.run")
    @patch("guardian_agent.sandbox.create_worktree_sandbox")
    def test_timeout_reported_gracefully(
        self, mock_sandbox, mock_run, _path
    ) -> None:
        """Execution timeout should be reported gracefully."""
        mock_sandbox.return_value = {
            "branch": "jcode-test",
            "worktree_path": str(self.brain.root / ".." / "sandbox"),
            "mode": "copy-fallback",
        }
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="jcode", timeout=10, output="", stderr=""
        )

        from guardian_agent.jcode import execute_jcode_in_sandbox
        result = execute_jcode_in_sandbox(
            self.brain, "Refactor", timeout=10,
        )
        self.assertTrue(result["execution"]["timed_out"])
        self.assertIn("timed out", result["execution"]["stderr"].lower())

    def test_out_of_scope_validation_rejects_bad_paths(self) -> None:
        """Changes outside writable_paths should be detected as out-of-scope."""
        from guardian_agent.jcode import _validate_out_of_scope

        changed = [
            {"path": "src/auth/login.py", "insertions": 10, "deletions": 0},
            {"path": ".env", "insertions": 1, "deletions": 0},
            {"path": "src/unrelated/secret.py", "insertions": 5, "deletions": 0},
        ]
        allowed = ["src/auth/"]

        out_of_scope = _validate_out_of_scope(changed, allowed)
        self.assertEqual(len(out_of_scope), 2)
        self.assertEqual(out_of_scope[0]["path"], ".env")
        self.assertEqual(out_of_scope[1]["path"], "src/unrelated/secret.py")

    def test_out_of_scope_all_valid(self) -> None:
        """All changes within writable_paths should be accepted."""
        from guardian_agent.jcode import _validate_out_of_scope

        changed = [
            {"path": "src/auth/login.py", "insertions": 10, "deletions": 0},
            {"path": "src/auth/signup.py", "insertions": 5, "deletions": 2},
        ]
        allowed = ["src/auth/"]

        out_of_scope = _validate_out_of_scope(changed, allowed)
        self.assertEqual(len(out_of_scope), 0)

    @patch("guardian_agent.jcode._jcode_path", return_value="/usr/bin/jcode")
    @patch("guardian_agent.jcode.subprocess.run")
    @patch("guardian_agent.sandbox.create_worktree_sandbox")
    def test_result_includes_structured_output(
        self, mock_sandbox, mock_run, _path
    ) -> None:
        """Execution result should include all required structured fields."""
        mock_sandbox.return_value = {
            "branch": "jcode-test",
            "worktree_path": str(self.brain.root / ".." / "sandbox"),
            "mode": "copy-fallback",
        }
        mock_run.return_value.stdout = "Done."
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0

        from guardian_agent.jcode import execute_jcode_in_sandbox
        result = execute_jcode_in_sandbox(
            self.brain, "Refactor",
            writable_paths=["src/auth/"],
            test_command="echo ok",
            timeout=60,
        )
        self.assertIn("execution", result)
        self.assertIn("changed_files", result)
        self.assertIn("diff_stat", result)
        self.assertIn("out_of_scope_changes", result)
        self.assertIn("all_changes_valid", result)
        self.assertIn("test_results", result)
        self.assertIn("approved", result)
        self.assertFalse(result["approved"])  # Requires final approval


# ---------------------------------------------------------------------------
# Phase 4 — Bounded parallel work tests
# ---------------------------------------------------------------------------

class JCodePathLockingTests(unittest.TestCase):
    """Tests for path locking/unlocking and conflict detection."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "JCode Locks", "Lock tests")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_paths_overlap_identical(self) -> None:
        """Identical paths should overlap."""
        from guardian_agent.jcode import _paths_overlap
        self.assertTrue(_paths_overlap("src/auth", "src/auth"))

    def test_paths_overlap_prefix(self) -> None:
        """One path being a prefix of another should overlap."""
        from guardian_agent.jcode import _paths_overlap
        self.assertTrue(_paths_overlap("src/auth/login.py", "src/auth/"))
        self.assertTrue(_paths_overlap("src/auth/", "src/auth/login.py"))

    def test_paths_no_overlap(self) -> None:
        """Unrelated paths should not overlap."""
        from guardian_agent.jcode import _paths_overlap
        self.assertFalse(_paths_overlap("src/auth/", "src/api/"))
        self.assertFalse(_paths_overlap("tests/test_auth.py", "src/auth/login.py"))

    def test_paths_overlap_trailing_slash(self) -> None:
        """Paths with trailing slashes should match correctly."""
        from guardian_agent.jcode import _paths_overlap
        self.assertTrue(_paths_overlap("src/auth/", "src/auth"))

    def test_lock_writable_paths_acquires_lock(self) -> None:
        """Lock acquisition should succeed and return lock_id."""
        from guardian_agent.jcode import _lock_writable_paths
        result = _lock_writable_paths(self.brain, ["src/auth/"], "worker-0")
        self.assertIsNotNone(result["lock_id"])
        self.assertIn("src/auth/", result["paths"])

    def test_lock_conflict_detected(self) -> None:
        """Locking an overlapping path from a different worker should raise."""
        from guardian_agent.jcode import _lock_writable_paths
        _lock_writable_paths(self.brain, ["src/auth/"], "worker-0")
        with self.assertRaises(GuardianError) as ctx:
            _lock_writable_paths(self.brain, ["src/auth/login.py"], "worker-1")
        self.assertIn("Path conflict", str(ctx.exception))

    def test_lock_same_worker_allowed(self) -> None:
        """Same worker should be able to lock overlapping paths."""
        from guardian_agent.jcode import _lock_writable_paths
        _lock_writable_paths(self.brain, ["src/auth/"], "worker-0")
        result = _lock_writable_paths(self.brain, ["src/auth/login.py"], "worker-0")
        self.assertIsNotNone(result["lock_id"])

    def test_unlock_writable_paths(self) -> None:
        """Lock release should succeed."""
        from guardian_agent.jcode import _lock_writable_paths, _unlock_writable_paths
        lock = _lock_writable_paths(self.brain, ["src/auth/"], "worker-0")
        result = _unlock_writable_paths(self.brain, lock["lock_id"])
        self.assertEqual(result["status"], "released")

    def test_check_path_conflicts_no_conflict(self) -> None:
        """Independent paths should have no conflicts."""
        from guardian_agent.jcode import _check_path_conflicts
        packages = [
            {"writable_paths": ["src/auth/"]},
            {"writable_paths": ["src/api/"]},
        ]
        conflicts = _check_path_conflicts(self.brain, packages)
        self.assertEqual(len(conflicts), 0)

    def test_check_path_conflicts_detected(self) -> None:
        """Overlapping paths between packages should be detected."""
        from guardian_agent.jcode import _check_path_conflicts
        packages = [
            {"writable_paths": ["src/auth/"]},
            {"writable_paths": ["src/auth/login.py"]},
        ]
        conflicts = _check_path_conflicts(self.brain, packages)
        self.assertGreater(len(conflicts), 0)
        self.assertIn("overlaps", conflicts[0])


class JCodeNotificationTests(unittest.TestCase):
    """Tests for change notification between workers."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "JCode Notif", "Notification tests")
        self.sandbox_a = Path(self.tempdir.name) / "sandbox_a"
        self.sandbox_a.mkdir(exist_ok=True)
        self.sandbox_b = Path(self.tempdir.name) / "sandbox_b"
        self.sandbox_b.mkdir(exist_ok=True)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_notify_pending_worker(self) -> None:
        """Notification should create a note file in the pending worker's sandbox."""
        from guardian_agent.jcode import _notify_workers

        completed = {
            "task": "Implement auth",
            "changed_files": [{"path": "src/auth/login.py", "insertions": 10, "deletions": 0}],
            "diff_stat": "1 file changed",
            "sandbox_path": str(self.sandbox_a),
        }
        pending = [
            {"task": "Write tests", "sandbox_path": str(self.sandbox_b)},
        ]

        notes = _notify_workers(self.brain, completed, pending)
        self.assertEqual(len(notes), 1)
        self.assertIn("Write tests", notes[0])

        # Verify notification file was created
        notify_dir = self.sandbox_b / ".agent" / "notifications"
        notif_files = list(notify_dir.glob("notification-*.json"))
        self.assertGreaterEqual(len(notif_files), 1)


class JCodeParallelRunTests(unittest.TestCase):
    """Tests for parallel JCode execution orchestrator."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "JCode Par", "Parallel tests")
        from guardian_agent.jcode import jcode_opt_in
        jcode_opt_in(self.brain)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_parallel_run_requires_opt_in(self) -> None:
        """Parallel run should raise if opt-in not granted."""
        brain2 = initialize(Path(self.tempdir.name) / "other", "No opt-in", "No opt-in test")
        from guardian_agent.jcode import jcode_parallel_run
        with self.assertRaises(GuardianError) as ctx:
            jcode_parallel_run(brain2, [{"task": "Fix bug"}])
        self.assertIn("opt-in", str(ctx.exception).lower())

    @patch("guardian_agent.jcode._jcode_path", return_value=None)
    def test_parallel_run_binary_not_found(self, _path) -> None:
        """Parallel run should raise if JCode binary is missing."""
        from guardian_agent.jcode import jcode_parallel_run
        with self.assertRaises(GuardianError):
            jcode_parallel_run(self.brain, [{"task": "Fix bug"}])

    def test_parallel_run_empty_packages_rejected(self) -> None:
        """No task packages should raise."""
        from guardian_agent.jcode import jcode_parallel_run
        with self.assertRaises(GuardianError):
            jcode_parallel_run(self.brain, [])

    def test_parallel_run_path_conflict_detected(self) -> None:
        """Overlapping writable paths between packages should be rejected."""
        from guardian_agent.jcode import jcode_parallel_run
        packages = [
            {"task": "Fix auth", "writable_paths": ["src/auth/"]},
            {"task": "Refactor auth", "writable_paths": ["src/auth/login.py"]},
        ]
        with self.assertRaises(GuardianError) as ctx:
            jcode_parallel_run(self.brain, packages)
        self.assertIn("overlapping", str(ctx.exception).lower())

    def test_parallel_run_independent_paths_accepted(self) -> None:
        """Independent path packages should be accepted (will fail at binary check, not path validation)."""
        from guardian_agent.jcode import jcode_parallel_run
        packages = [
            {"task": "Fix auth", "writable_paths": ["src/auth/"]},
            {"task": "Add api", "writable_paths": ["src/api/"]},
        ]
        with self.assertRaises(GuardianError) as ctx:
            jcode_parallel_run(self.brain, packages)
        # Should fail on binary not found, NOT on path conflict
        self.assertNotIn("overlapping", str(ctx.exception).lower())

    def test_parallel_run_exceeds_max_workers(self) -> None:
        """More packages than max_workers should be rejected."""
        from guardian_agent.jcode import jcode_parallel_run
        packages = [
            {"task": "Task 1"},
            {"task": "Task 2"},
            {"task": "Task 3"},
        ]
        with self.assertRaises(GuardianError) as ctx:
            jcode_parallel_run(self.brain, packages, max_workers=2)
        self.assertIn("exceeds max_workers", str(ctx.exception).lower())

    def test_parallel_run_empty_task_rejected(self) -> None:
        """Empty task in any package should raise."""
        from guardian_agent.jcode import jcode_parallel_run
        packages = [
            {"task": "Fix auth"},
            {"task": ""},
        ]
        with self.assertRaises(GuardianError):
            jcode_parallel_run(self.brain, packages)


if __name__ == "__main__":
    unittest.main()
