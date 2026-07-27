import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from guardian_agent.aider import (
    aider_status,
    build_aider_command,
    classify_task_size,
    collect_aider_execution_evidence,
    create_aider_handoff,
    launch_aider,
)
from guardian_agent.core import GuardianError, initialize


class AiderAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Aider", "Adapter tests")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @patch("guardian_agent.aider._aider_path", return_value="/usr/bin/aider")
    @patch("guardian_agent.aider.subprocess.run")
    def test_status_is_structured(self, run, _path) -> None:
        run.return_value.stdout = "aider 0.86.2\n"
        with patch("guardian_agent.aider._port_open", return_value=True):
            result = aider_status()
        self.assertTrue(result["available"])
        self.assertIn("ollama", result["backends"])
        self.assertIn("omniroute", result["backends"])
        self.assertIn("jcode_available", result)
        self.assertIn("hermes_available", result)

    def test_prepare_embeds_only_routed_profile_handoff(self) -> None:
        result = create_aider_handoff(self.brain, "Write unit tests", limit=3)
        text = Path(result["handoff"]).read_text(encoding="utf-8")
        self.assertIn("Unit-test writer", text)
        self.assertNotIn("150 specialist", text)
        self.assertGreater(result["context"]["estimated_savings_percent"], 90)

    @patch("guardian_agent.aider._aider_path", return_value="/usr/bin/aider")
    def test_command_defaults_to_dry_run_and_disables_analytics(self, _path) -> None:
        result = build_aider_command(
            self.brain,
            "Review the API",
            "ollama",
            "qwen2.5-coder",
        )
        self.assertIn("--dry-run", result["command"])
        self.assertIn("--no-analytics", result["command"])
        self.assertIn("--no-auto-commits", result["command"])
        self.assertIn("--no-gitignore", result["command"])
        self.assertEqual(result["command"][result["command"].index("--map-tokens") + 1], "0")
        self.assertNotIn("local-ollama", " ".join(result["command"]))

    @patch("guardian_agent.aider._aider_path", return_value="/usr/bin/aider")
    def test_prohibited_model_is_rejected(self, _path) -> None:
        with self.assertRaises(GuardianError):
            build_aider_command(
                self.brain,
                "Review",
                "omniroute",
                "claude-sonnet-4.6",
            )

    @patch("guardian_agent.aider._aider_path", return_value="/usr/bin/aider")
    @patch("guardian_agent.aider.subprocess.run")
    @patch("guardian_agent.aider._port_open", return_value=True)
    def test_loopback_omniroute_can_launch_without_api_key(self, _port, run, _path) -> None:
        import os
        os.environ.pop("OMNIROUTE_API_KEY", None)
        run.return_value.returncode = 0
        result = launch_aider(
            self.brain,
            "Review",
            "omniroute",
            "allowed-free-combo",
        )
        self.assertEqual(result, 0)
        child_env = run.call_args.kwargs["env"]
        self.assertEqual(child_env["OPENAI_API_KEY"], "local-omniroute")

    @patch("guardian_agent.aider._aider_path", return_value="/usr/bin/aider")
    @patch("guardian_agent.aider._port_open", return_value=False)
    def test_launch_requires_reachable_backend(self, _port, _path) -> None:
        with self.assertRaises(GuardianError):
            launch_aider(
                self.brain,
                "Review",
                "ollama",
                "qwen2.5-coder",
            )

    # --- Phase 1: Task-size classification tests ---

    def test_classify_empty_task_defaults_to_small(self) -> None:
        result = classify_task_size("")
        self.assertEqual(result["category"], "small")
        self.assertEqual(result["recommended_worker"], "aider")

    def test_classify_small_task(self) -> None:
        result = classify_task_size("Fix the button alignment in login form")
        self.assertEqual(result["category"], "small")
        self.assertEqual(result["recommended_worker"], "aider")

    def test_classify_research_task(self) -> None:
        result = classify_task_size("Research the best authentication library for Python")
        self.assertEqual(result["category"], "research")

    def test_classify_large_task_by_keyword(self) -> None:
        result = classify_task_size("Refactor the entire user module to use new database schema")
        self.assertEqual(result["category"], "large")

    def test_classify_large_task_by_length(self) -> None:
        long_task = "Implement a complete new feature for user management. " * 20
        result = classify_task_size(long_task)
        self.assertEqual(result["category"], "large")

    def test_classify_returns_worker_availability(self) -> None:
        result = classify_task_size("Fix a small bug")
        self.assertIn("workers_available", result)
        self.assertIn("aider", result["workers_available"])
        self.assertIn("jcode", result["workers_available"])
        self.assertIn("hermes", result["workers_available"])

    # --- Phase 1: Enhanced handoff tests ---

    def test_enhanced_handoff_includes_acceptance_criteria(self) -> None:
        result = create_aider_handoff(
            self.brain,
            "Fix login bug",
            acceptance_criteria=["All tests pass", "Login flow works"],
        )
        text = Path(result["handoff"]).read_text(encoding="utf-8")
        self.assertIn("Acceptance criteria", text)
        self.assertIn("All tests pass", text)
        self.assertIn("Login flow works", text)
        self.assertEqual(len(result["acceptance_criteria"]), 2)

    def test_enhanced_handoff_includes_writable_paths(self) -> None:
        result = create_aider_handoff(
            self.brain,
            "Fix login bug",
            writable_paths=["src/auth/login.py", "src/auth/"],
        )
        text = Path(result["handoff"]).read_text(encoding="utf-8")
        self.assertIn("Writable paths", text)
        self.assertIn("src/auth/login.py", text)
        self.assertGreater(len(result["writable_paths"]), 0)

    def test_enhanced_handoff_includes_test_command(self) -> None:
        result = create_aider_handoff(
            self.brain,
            "Fix login bug",
            test_command="python -m pytest tests/test_auth.py",
        )
        text = Path(result["handoff"]).read_text(encoding="utf-8")
        self.assertIn("Test command", text)
        self.assertIn("python -m pytest", text)
        self.assertEqual(result["test_command"], "python -m pytest tests/test_auth.py")

    def test_enhanced_handoff_includes_risks(self) -> None:
        result = create_aider_handoff(
            self.brain,
            "Fix login bug",
            risks=["May affect existing sessions", "Database migration required"],
        )
        text = Path(result["handoff"]).read_text(encoding="utf-8")
        self.assertIn("Known risks", text)
        self.assertIn("May affect existing sessions", text)

    def test_enhanced_handoff_includes_stop_conditions(self) -> None:
        result = create_aider_handoff(
            self.brain,
            "Fix login bug",
            stop_conditions=["All tests must pass", "No new lint warnings"],
        )
        text = Path(result["handoff"]).read_text(encoding="utf-8")
        self.assertIn("Stop conditions", text)
        self.assertIn("All tests must pass", text)

    def test_enhanced_handoff_all_params_together(self) -> None:
        result = create_aider_handoff(
            self.brain,
            "Refactor auth module",
            limit=3,
            acceptance_criteria=["Passes CI", "No regressions"],
            writable_paths=["src/auth/"],
            test_command="python -m pytest tests/",
            risks=["Breaking API change"],
            stop_conditions=["Failing tests", "API incompatibility"],
        )
        self.assertEqual(len(result["acceptance_criteria"]), 2)
        self.assertGreater(len(result["writable_paths"]), 0)
        self.assertIsNotNone(result["test_command"])
        self.assertEqual(len(result["risks"]), 1)
        self.assertEqual(len(result["stop_conditions"]), 2)
        text = Path(result["handoff"]).read_text(encoding="utf-8")
        self.assertIn("Acceptance criteria", text)
        self.assertIn("Writable paths", text)
        self.assertIn("Test command", text)
        self.assertIn("Known risks", text)
        self.assertIn("Stop conditions", text)
        self.assertIn("Specialist handoff", text)

    # --- Phase 1: Execution evidence tests ---

    @patch("guardian_agent.aider._git_diff_summary")
    def test_collect_evidence_without_git_repo(self, mock_diff) -> None:
        mock_diff.return_value = {
            "files_changed": [],
            "insertions": 0,
            "deletions": 0,
            "diff_stat": "",
            "error": "Not a git repository.",
        }
        evidence = collect_aider_execution_evidence(
            self.brain, "Fix bug", test_command=None,
        )
        self.assertEqual(len(evidence["errors"]), 1)
        self.assertIn("Not a git repository", evidence["errors"][0])
        self.assertIn("No test command", evidence["remaining_risks"][0])
        self.assertIn("No files were changed", evidence["remaining_risks"][1])

    @patch("guardian_agent.aider._git_diff_summary")
    def test_collect_evidence_with_changed_files(self, mock_diff) -> None:
        mock_diff.return_value = {
            "files_changed": [
                {"path": "src/auth/login.py", "insertions": 10, "deletions": 2},
            ],
            "insertions": 10,
            "deletions": 2,
            "diff_stat": "1 file changed, 10 insertions(+), 2 deletions(-)",
            "error": None,
        }
        evidence = collect_aider_execution_evidence(
            self.brain, "Fix bug", test_command=None,
        )
        self.assertEqual(len(evidence["changed_files"]), 1)
        self.assertEqual(evidence["insertions"], 10)
        self.assertEqual(evidence["deletions"], 2)

    @patch("guardian_agent.aider._git_diff_summary")
    def test_collect_evidence_with_test_command(self, mock_diff) -> None:
        mock_diff.return_value = {
            "files_changed": [],
            "insertions": 0,
            "deletions": 0,
            "diff_stat": "",
            "error": None,
        }
        # The test command won't actually run because we mock _run_tests via
        # patching _git_diff_summary only. Let's test that evidence is collected.
        evidence = collect_aider_execution_evidence(
            self.brain, "Fix bug", test_command="echo ok",
        )
        self.assertIn("diff_stat", evidence)
        self.assertEqual(evidence["task"], "Fix bug")

    @patch("guardian_agent.aider._git_diff_summary")
    def test_collect_evidence_risk_identification(self, mock_diff) -> None:
        mock_diff.return_value = {
            "files_changed": [],
            "insertions": 0,
            "deletions": 0,
            "diff_stat": "",
            "error": None,
        }
        evidence = collect_aider_execution_evidence(
            self.brain, "Fix bug", test_command=None,
        )
        self.assertGreater(len(evidence["remaining_risks"]), 0)
        # Should mention no test command and no files changed
        self.assertTrue(
            any("No test command" in r for r in evidence["remaining_risks"])
        )
        self.assertTrue(
            any("No files were changed" in r for r in evidence["remaining_risks"])
        )

    # --- Phase 1: build_aider_command with enhanced handoff ---

    @patch("guardian_agent.aider._aider_path", return_value="/usr/bin/aider")
    def test_build_command_with_enhanced_handoff_params(self, _path) -> None:
        """Test that enhanced parameters flow through build_aider_command."""
        result = build_aider_command(
            self.brain,
            "Fix login bug",
            "ollama",
            "qwen2.5-coder",
            acceptance_criteria=["All tests pass"],
            writable_paths=["src/auth/"],
            test_command="pytest tests/",
            risks=["Edge cases"],
            stop_conditions=["Test failure"],
        )
        self.assertIsNotNone(result["handoff"])
        handoff_data = result["handoff"]
        self.assertEqual(len(handoff_data["acceptance_criteria"]), 1)
        self.assertGreater(len(handoff_data["writable_paths"]), 0)
        self.assertEqual(handoff_data["test_command"], "pytest tests/")

    @patch("guardian_agent.aider._aider_path", return_value="/usr/bin/aider")
    def test_build_command_writable_paths_excludes_sensitive(self, _path) -> None:
        result = build_aider_command(
            self.brain,
            "Fix bug",
            "ollama",
            "qwen2.5-coder",
            writable_paths=["src/auth", ".env", "../outside"],
        )
        # Protected paths should be filtered out; src/auth is valid
        handoff_paths = result["handoff"]["writable_paths"]
        self.assertIn("src/auth", handoff_paths)
        for sensitive in (".env", "../outside"):
            self.assertNotIn(sensitive, handoff_paths)


if __name__ == "__main__":
    unittest.main()
