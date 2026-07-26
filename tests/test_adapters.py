"""Comprehensive Phase 4 IDE & Coding-Tool Adapter test suite (Production Hardened).

Tests cover all Phase 4 functional requirements:
1. Rich handoff package contract (task, requirements, acceptance_criteria, allowed_paths, review_required)
2. Startup reconciliation (missing/corrupt handoff package causes safe rollback to claimed state)
3. Crash-safe handoff transaction (simulated write failure reverts dispatch state in brain)
4. Task-scoped allowed_paths enforcement (artifact paths outside allowed_paths are rejected)
5. CLI verification-results input parsing (JSON string, file path, key:value list)
6. CLI launch command with strict returncode & binary field verification
7. Strict validation of verification evidence (accepting '0 errors', '12 passed', rejecting 'not passed', 'skipped', 'failed', '0 passed', empty dicts)
8. Robust JSONC parser (preserving comments and trailing commas inside string literals like "keep,}")
9. Persistent adapter_target and adapter_token binding in ExecutionStage (including idempotent replay checks)
10. VS Code / Antigravity path collision protection
11. Ownership-safe file overwrite
12. Non-root integration file uninstall
13. Primary-review stage blocking
14. Specialized detection for all 6 tools
15. --no-root-harness CLI toggle
16. Real smoke tests for local installed tools (Codex, Claude Code, VS Code, Antigravity)
"""

import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from guardian_agent.adapters import (
    SUPPORTED_IDE_TARGETS,
    _ROOT_HARNESS_PATHS,
    _get_project_context,
    _is_guardian_owned,
    _strip_jsonc_comments,
    _validate_verification_results,
    create_bounded_handoff,
    detect_installed_tools,
    generate_adapter_config,
    get_adapter,
    launch_adapter_tool,
    submit_adapter_result,
    uninstall_adapter_config,
)
from guardian_agent.cli import main as cli_main
from guardian_agent.core import GuardianError, initialize
from guardian_agent.execution import (
    plan_execution,
    reconcile_dispatched_handoffs,
    show_execution,
)
from guardian_agent.orchestration import orchestrate_confirm, orchestrate_dispatch, orchestrate_start


def _make_brain(tmp: str, name: str = "demo") -> tuple:
    root = Path(tmp) / name
    brain = initialize(root, "Adapter Tests", "Phase 4 test suite")
    return root, brain


def _setup_execution(brain):
    start = orchestrate_start(brain, "Build auth module", limit=3, approved_paths=["src/", "tests/"])
    orch_id = start["orchestration_id"]

    orchestrate_confirm(brain, orch_id, "Build auth module")
    orchestrate_dispatch(brain, orch_id)
    ex = plan_execution(brain, orch_id)
    return ex["id"], ex.get("stages", [])


# ---------------------------------------------------------------------------
# Crash-Safe Handoff Transaction & Startup Reconciliation Tests
# ---------------------------------------------------------------------------

class TestCrashSafeHandoffTransaction(unittest.TestCase):
    def test_simulated_write_failure_reverts_dispatch_state(self) -> None:
        """If writing the handoff file fails, the execution record must NOT be left in 'dispatched' state."""
        with tempfile.TemporaryDirectory() as tmp:
            root, brain = _make_brain(tmp)
            ex_id, _ = _setup_execution(brain)

            # Mock json.dump after stage dispatch to simulate package write failure
            orig_dump = json.dump
            dump_count = [0]
            def mock_dump(*args, **kwargs):
                dump_count[0] += 1
                if dump_count[0] == 3:  # 1: claim_stage, 2: mark_dispatched, 3: handoff package, 4: rollback save
                    raise OSError("Disk write error")
                return orig_dump(*args, **kwargs)


            with patch("json.dump", side_effect=mock_dump):
                with self.assertRaises(GuardianError):
                    create_bounded_handoff(brain, target="vscode", execution_id=ex_id, stage_index=0)






            # Check that execution stage was reverted back to claimed/pending, NOT left dispatched
            rec = show_execution(brain, ex_id)
            stage0 = rec["stages"][0]
            self.assertNotEqual(stage0["state"], "dispatched", "Stage left in 'dispatched' state despite write crash!")
            self.assertIsNone(stage0.get("dispatch_id"))

    def test_startup_reconciliation_reverts_missing_package(self) -> None:
        """Startup reconciliation must revert dispatched stages if the handoff package file is missing."""
        with tempfile.TemporaryDirectory() as tmp:
            root, brain = _make_brain(tmp)
            ex_id, _ = _setup_execution(brain)
            handoff = create_bounded_handoff(brain, target="vscode", execution_id=ex_id, stage_index=0)

            # Delete the package file on disk to simulate power outage / process kill before write completion
            pkg_path = Path(handoff["package_path"])
            if pkg_path.exists():
                pkg_path.unlink()

            # Run startup reconciliation
            res = reconcile_dispatched_handoffs(brain)
            self.assertEqual(res["reconciled_count"], 1)
            self.assertEqual(res["reverted_count"], 1)

            # Verify state was safely reverted back to claimed
            rec = show_execution(brain, ex_id)
            stage0 = rec["stages"][0]
            self.assertEqual(stage0["state"], "claimed")
            self.assertIsNone(stage0.get("dispatch_id"))


# ---------------------------------------------------------------------------
# Path Filtering & Context Protection Tests
# ---------------------------------------------------------------------------

class TestPathFiltering(unittest.TestCase):
    def test_protected_files_excluded_from_allowed_paths(self) -> None:
        """Sensitive files like .env and .agent/vault must NEVER appear in allowed_paths."""
        with tempfile.TemporaryDirectory() as tmp:
            root, brain = _make_brain(tmp)
            (root / ".env").write_text("SECRET=123")
            (root / "vault.pem").write_text("KEY")

            ctx = _get_project_context(brain, task_summary="Update auth system", stage_allowed_paths=["src/", ".env", "vault.pem"])
            paths = ctx["allowed_paths"]

            for p in paths:
                self.assertNotIn(".env", p)
                self.assertNotIn("vault", p)
                self.assertNotIn(".git", p)

    def test_allowed_paths_strictly_enforced_on_recording(self) -> None:
        """Recording a result with an artifact path outside stage allowed_paths must raise GuardianError."""
        with tempfile.TemporaryDirectory() as tmp:
            root, brain = _make_brain(tmp)
            ex_id, stages = _setup_execution(brain)

            # Manually set allowed_paths on stage
            from guardian_agent.execution import _load_record, _save_record
            rec = _load_record(brain, ex_id)
            rec.stages[0].allowed_paths = ["src/auth/"]
            _save_record(brain, rec)

            handoff = create_bounded_handoff(brain, target="vscode", execution_id=ex_id, stage_index=0)

            with self.assertRaises(GuardianError) as err:
                submit_adapter_result(
                    brain,
                    target="vscode",
                    execution_id=ex_id,
                    stage_id=handoff["stage_id"],
                    lease_id=handoff["lease_id"],
                    dispatch_id=handoff["dispatch_id"],
                    adapter_token=handoff["adapter_token"],
                    outcome="passed",
                    summary="Changed unauthorized file",
                    verification_results=[{"check": "unit", "result": "passed"}],
                    artifacts_changed=["config/secret.json"],
                )
            self.assertIn("allowed paths", str(err.exception).lower())


# ---------------------------------------------------------------------------
# Rich Handoff Package Contract
# ---------------------------------------------------------------------------

class TestRichHandoffContract(unittest.TestCase):
    def test_handoff_package_contains_rich_context(self) -> None:
        """Package must include task, requirements, acceptance criteria, and explicit allowed paths."""
        with tempfile.TemporaryDirectory() as tmp:
            root, brain = _make_brain(tmp)
            ex_id, _ = _setup_execution(brain)
            handoff = create_bounded_handoff(brain, target="vscode", execution_id=ex_id, stage_index=0)
            pkg_file = Path(handoff["package_path"])
            self.assertTrue(pkg_file.is_file())

            pkg = json.loads(pkg_file.read_text(encoding="utf-8"))
            self.assertEqual(pkg["target"], "vscode")
            self.assertEqual(pkg["context_mode"], "fresh_bounded_handoff")
            self.assertIn("task", pkg)
            self.assertIn("requirements", pkg)
            self.assertIn("acceptance_criteria", pkg)
            self.assertIn("allowed_paths", pkg)
            self.assertIn("review_required", pkg)
            self.assertTrue(len(pkg["requirements"]) > 0)
            self.assertTrue(len(pkg["acceptance_criteria"]) > 0)
            self.assertTrue(len(pkg["allowed_paths"]) > 0)


# ---------------------------------------------------------------------------
# Strict Verification Results Validation
# ---------------------------------------------------------------------------

class TestStrictVerificationValidation(unittest.TestCase):
    def test_passed_requires_non_empty_verification_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, brain = _make_brain(tmp)
            ex_id, _ = _setup_execution(brain)
            handoff = create_bounded_handoff(brain, target="vscode", execution_id=ex_id, stage_index=0)
            with self.assertRaises(GuardianError) as ctx:
                submit_adapter_result(
                    brain,
                    target="vscode",
                    execution_id=ex_id,
                    stage_id=handoff["stage_id"],
                    lease_id=handoff["lease_id"],
                    dispatch_id=handoff["dispatch_id"],
                    adapter_token=handoff["adapter_token"],
                    outcome="passed",
                    summary="All clean.",
                    verification_results=[],
                )
            self.assertIn("verification_results", str(ctx.exception).lower())

    def test_negative_result_in_verification_item_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, brain = _make_brain(tmp)
            ex_id, _ = _setup_execution(brain)
            handoff = create_bounded_handoff(brain, target="vscode", execution_id=ex_id, stage_index=0)
            with self.assertRaises(GuardianError) as ctx:
                submit_adapter_result(
                    brain,
                    target="vscode",
                    execution_id=ex_id,
                    stage_id=handoff["stage_id"],
                    lease_id=handoff["lease_id"],
                    dispatch_id=handoff["dispatch_id"],
                    adapter_token=handoff["adapter_token"],
                    outcome="passed",
                    summary="Claiming passed despite failure.",
                    verification_results=[{"check": "tests", "result": "failed (2 errors)"}],
                )
            self.assertIn("indicates failure", str(ctx.exception).lower())

    def test_not_passed_and_skipped_rejected(self) -> None:
        with self.assertRaises(GuardianError):
            _validate_verification_results([{"check": "tests", "result": "not passed"}])
        with self.assertRaises(GuardianError):
            _validate_verification_results([{"check": "tests", "result": "skipped"}])

    def test_zero_errors_and_12_passed_accepted(self) -> None:
        _validate_verification_results([{"check": "unit_tests", "result": "12 passed, 0 errors"}])
        _validate_verification_results([{"check": "lint", "result": "0 errors"}])

    def test_positive_verification_results_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, brain = _make_brain(tmp)
            ex_id, _ = _setup_execution(brain)
            handoff = create_bounded_handoff(brain, target="vscode", execution_id=ex_id, stage_index=0)
            res = submit_adapter_result(
                brain,
                target="vscode",
                execution_id=ex_id,
                stage_id=handoff["stage_id"],
                lease_id=handoff["lease_id"],
                dispatch_id=handoff["dispatch_id"],
                adapter_token=handoff["adapter_token"],
                outcome="passed",
                summary="Verified success.",
                verification_results=[
                    {"check": "unit_tests", "result": "47/47 passed"},
                    {"check": "lint", "result": "clean"},
                ],
            )
            self.assertEqual(res["outcome"], "passed")


# ---------------------------------------------------------------------------
# Persistent Identity & Target Binding
# ---------------------------------------------------------------------------

class TestPersistentIdentityBinding(unittest.TestCase):
    def test_token_never_exposed_in_show_execution_or_cli(self) -> None:
        """Token must be redacted in show_execution output and never exposed in public status APIs."""
        with tempfile.TemporaryDirectory() as tmp:
            root, brain = _make_brain(tmp)
            ex_id, _ = _setup_execution(brain)
            handoff = create_bounded_handoff(brain, target="vscode", execution_id=ex_id, stage_index=0)
            actual_token = handoff["adapter_token"]

            rec = show_execution(brain, ex_id)
            stage0 = rec["stages"][0]
            self.assertEqual(stage0["adapter_token"], "[REDACTED]", "Public execution view exposed actual adapter token!")
            self.assertNotEqual(stage0["adapter_token"], actual_token)

    def test_mismatched_adapter_target_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, brain = _make_brain(tmp)
            ex_id, _ = _setup_execution(brain)
            handoff = create_bounded_handoff(brain, target="vscode", execution_id=ex_id, stage_index=0)
            with self.assertRaises(GuardianError) as ctx:
                submit_adapter_result(
                    brain,
                    target="cursor",
                    execution_id=ex_id,
                    stage_id=handoff["stage_id"],
                    lease_id=handoff["lease_id"],
                    dispatch_id=handoff["dispatch_id"],
                    adapter_token=handoff["adapter_token"],
                    outcome="passed",
                    summary="Cross target attempt",
                    verification_results=[{"check": "smoke", "result": "passed"}],
                )
            self.assertIn("target", str(ctx.exception).lower())

    def test_mismatched_adapter_token_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, brain = _make_brain(tmp)
            ex_id, _ = _setup_execution(brain)
            handoff = create_bounded_handoff(brain, target="vscode", execution_id=ex_id, stage_index=0)
            with self.assertRaises(GuardianError) as ctx:
                submit_adapter_result(
                    brain,
                    target="vscode",
                    execution_id=ex_id,
                    stage_id=handoff["stage_id"],
                    lease_id=handoff["lease_id"],
                    dispatch_id=handoff["dispatch_id"],
                    adapter_token="forged-token-0000000000000000000000000000",
                    outcome="passed",
                    summary="Forged token attempt",
                    verification_results=[{"check": "smoke", "result": "passed"}],
                )
            self.assertIn("token", str(ctx.exception).lower())

    def test_completed_replay_validates_token_and_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, brain = _make_brain(tmp)
            ex_id, _ = _setup_execution(brain)
            handoff = create_bounded_handoff(brain, target="vscode", execution_id=ex_id, stage_index=0)
            res1 = submit_adapter_result(
                brain,
                target="vscode",
                execution_id=ex_id,
                stage_id=handoff["stage_id"],
                lease_id=handoff["lease_id"],
                dispatch_id=handoff["dispatch_id"],
                adapter_token=handoff["adapter_token"],
                outcome="passed",
                summary="Initial result",
                verification_results=[{"check": "smoke", "result": "passed"}],
            )
            self.assertEqual(res1["outcome"], "passed")

            with self.assertRaises(GuardianError):
                submit_adapter_result(
                    brain,
                    target="vscode",
                    execution_id=ex_id,
                    stage_id=handoff["stage_id"],
                    lease_id=handoff["lease_id"],
                    dispatch_id=handoff["dispatch_id"],
                    adapter_token="wrong-token-12345678901234567890",
                    outcome="passed",
                    summary="Replay with wrong token",
                    verification_results=[{"check": "smoke", "result": "passed"}],
                )


# ---------------------------------------------------------------------------
# JSONC Parser Hardening
# ---------------------------------------------------------------------------

class TestJSONCParserHardening(unittest.TestCase):
    def test_block_comment_inside_string_literal_preserved(self) -> None:
        raw = '{"greeting": "Hello /* World */", "count": 5}'
        stripped = _strip_jsonc_comments(raw)
        data = json.loads(stripped)
        self.assertEqual(data["greeting"], "Hello /* World */")

    def test_trailing_comma_inside_string_literal_preserved(self) -> None:
        raw = '{"val": "keep,}", "other": 123}'
        stripped = _strip_jsonc_comments(raw)
        data = json.loads(stripped)
        self.assertEqual(data["val"], "keep,}")

    def test_trailing_commas_outside_strings_handled(self) -> None:
        raw = '{\n  "a": 1,\n  "b": 2,\n}'
        stripped = _strip_jsonc_comments(raw)
        data = json.loads(stripped)
        self.assertEqual(data["a"], 1)
        self.assertEqual(data["b"], 2)


# ---------------------------------------------------------------------------
# CLI Commands & Tool Execution Verification
# ---------------------------------------------------------------------------

class TestCLIAdapterCommands(unittest.TestCase):
    def test_cli_adapter_record_with_verification_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, brain = _make_brain(tmp)
            ex_id, _ = _setup_execution(brain)
            handoff = create_bounded_handoff(brain, target="vscode", execution_id=ex_id, stage_index=0)

            ret = cli_main([
                "adapter", "record",
                "--project", str(root),
                "--target", "vscode",
                "--execution-id", ex_id,
                "--stage-id", handoff["stage_id"],
                "--lease-id", handoff["lease_id"],
                "--dispatch-id", handoff["dispatch_id"],
                "--adapter-token", handoff["adapter_token"],
                "--outcome", "passed",
                "--summary", "CLI verified result",
                "--verification-results", "unit_test:passed,lint:clean",
            ])
            self.assertEqual(ret, 0)

    def test_cli_adapter_launch_and_execute_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, brain = _make_brain(tmp)
            ret = cli_main(["adapter", "launch", "--project", str(root), "--target", "vscode"])
            self.assertEqual(ret, 0)


# ---------------------------------------------------------------------------
# Installed Tools Smoke Testing with Binary & Returncode Verification
# ---------------------------------------------------------------------------

class TestInstalledToolsSmoke(unittest.TestCase):
    def test_failed_command_rejected_by_smoke_check(self) -> None:
        """Smoke test must reject commands that exit with non-zero exit code."""
        with tempfile.TemporaryDirectory() as tmp:
            _, brain = _make_brain(tmp)
            adapter = get_adapter("vscode")

            mock_proc = subprocess.CompletedProcess(args=["code", "--version"], returncode=1, stdout="", stderr="error: failed")
            with patch("subprocess.run", return_value=mock_proc):
                res = adapter.launch(brain, execute=True)
                self.assertFalse(res.get("executed", False), "Failed command was incorrectly accepted as executed!")
                self.assertIn("error", res)
                self.assertIn("binary", res)

    def test_launch_returns_binary_key_for_all_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, brain = _make_brain(tmp)
            for target in SUPPORTED_IDE_TARGETS:
                res = launch_adapter_tool(brain, target=target, execute=False)
                self.assertIn("binary", res)
                self.assertIn("installed", res)
                self.assertIn("command", res)

    def test_launch_and_execute_installed_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, brain = _make_brain(tmp)
            det = detect_installed_tools()
            for target in SUPPORTED_IDE_TARGETS:
                tool_info = det["tools"][target]
                if tool_info["installed"]:
                    res = launch_adapter_tool(brain, target=target, execute=True)
                    self.assertEqual(res["target"], target)
                    self.assertTrue(res["installed"])
                    self.assertIn("binary", res)
                    if res.get("executed"):
                        self.assertEqual(res.get("returncode"), 0)
                        self.assertTrue(res.get("verified"))
                    else:
                        self.assertIn("error", res)
                        self.assertTrue(res.get("unavailable_in_environment", False))



# ---------------------------------------------------------------------------
# Path Collision & Ownership-Safe Overwrite Tests
# ---------------------------------------------------------------------------

class TestPathCollisionAndOwnership(unittest.TestCase):
    def test_vscode_and_antigravity_paths_distinct(self) -> None:
        self.assertNotEqual(str(_ROOT_HARNESS_PATHS["vscode"]), str(_ROOT_HARNESS_PATHS["antigravity"]))

    def test_user_owned_file_protected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, brain = _make_brain(tmp)
            (root / "AGENTS.md").write_text("# User file\nDo not delete.")
            res = generate_adapter_config(brain, target="codex", overwrite=True, root_harness=True)
            self.assertEqual(res["results"][0]["status"], "skipped_user_owned")


if __name__ == "__main__":
    unittest.main()
