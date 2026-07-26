import json
import io
import shutil
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path

from guardian_agent.core import GuardianError, initialize
from guardian_agent.orchestration import orchestrate_start, orchestrate_confirm, orchestrate_dispatch
from guardian_agent.execution import (
    next_execution_stage,
    plan_execution,
    record_execution_result,
    show_execution,
)
from guardian_agent.runtime import kill_switch
from guardian_agent.service import (
    backup_brain,
    generate_service_config,
    get_brain_schema_version,
    install_service,
    migrate_brain,
    restore_brain,
    service_run,
    service_run_once,
    service_status,
    start_service,
    stop_service,
    uninstall_service,
    _rotate_service_log,
)


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Service Demo", "Testing local service and backup")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_service_status(self) -> None:
        st = service_status(self.brain)
        self.assertEqual(st["service_health"], "ready")
        self.assertFalse(st["emergency_stop_active"])
        self.assertIn("primary_review_inbox_count", st)

    def test_service_run_once(self) -> None:
        start = orchestrate_start(self.brain, "Service task", limit=3)
        orch_id = start["orchestration_id"]
        orchestrate_confirm(self.brain, orch_id, "Service task")
        orchestrate_dispatch(self.brain, orch_id)
        plan_execution(self.brain, orch_id)

        res = service_run_once(self.brain, max_tickets=2, dry_run=True)
        self.assertTrue(res.get("dry_run"))
        self.assertEqual(res["supervisor_summary"]["tickets_written"], 0)

    def test_service_run_loop_and_heartbeat(self) -> None:
        start = orchestrate_start(self.brain, "Loop task", limit=3)
        orch_id = start["orchestration_id"]
        orchestrate_confirm(self.brain, orch_id, "Loop task")
        orchestrate_dispatch(self.brain, orch_id)
        plan_execution(self.brain, orch_id)

        res = service_run(self.brain, interval_seconds=1, max_cycles=2, max_tickets=2, dry_run=True)
        self.assertEqual(res["cycles_completed"], 2)
        self.assertFalse(res["stopped"])

        st = service_status(self.brain)
        self.assertEqual(st["service_health"], "ready")

    def test_concurrent_service_lock_refusal(self) -> None:
        """Verify running a second service instance raises GuardianError when locked."""
        lock_file = self.brain.directory / "tasks" / ".service.pid.lock"
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        fd = open(lock_file, "w")
        import fcntl
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        try:
            with self.assertRaises(GuardianError):
                service_run(self.brain, interval_seconds=1, max_cycles=1, dry_run=False)
        finally:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
            fd.close()

    def test_generate_service_config_and_unique_naming(self) -> None:
        sysd = generate_service_config(self.root, "systemd")
        self.assertEqual(sysd["system_kind"], "systemd")
        self.assertIn("[Unit]", sysd["content"])
        self.assertIn("guardian-agent-demo-", sysd["filename"])

        root2 = Path(self.tempdir.name) / "other_project"
        sysd2 = generate_service_config(root2, "systemd")
        self.assertNotEqual(sysd["filename"], sysd2["filename"])

    def test_service_config_escaping_special_characters(self) -> None:
        """Verify % is escaped as %% in systemd and XML escaping is single-pass in launchd."""
        special_path = Path(self.tempdir.name) / "project & test %100"
        special_path.mkdir(parents=True, exist_ok=True)

        sysd = generate_service_config(special_path, "systemd")
        self.assertIn("project & test %%100", sysd["content"])

        launchd = generate_service_config(special_path, "launchd")
        # Verify single XML escaping: project & test %100 becomes project &amp; test %100 (NOT &amp;amp;)
        self.assertIn("project &amp; test %100", launchd["content"])
        self.assertNotIn("&amp;amp;", launchd["content"])


    @patch("subprocess.run")
    def test_install_and_uninstall_service(self, mock_subproc) -> None:
        mock_subproc.return_value.returncode = 0
        mock_subproc.return_value.stdout = "OK"

        with patch("pathlib.Path.home", return_value=Path(self.tempdir.name)):
            inst = install_service(self.root, system_kind="systemd")
            self.assertTrue(inst["installed"])
            self.assertTrue(Path(inst["unit_file"]).is_file())
            self.assertTrue(any(
                call.args[0][:3] == ["systemctl", "--user", "enable"]
                for call in mock_subproc.call_args_list
            ))

            uninst = uninstall_service(self.root, system_kind="systemd")
            self.assertTrue(uninst["uninstalled"])
            self.assertFalse(Path(inst["unit_file"]).exists())

    @patch("subprocess.run")
    def test_start_and_stop_service(self, mock_subproc) -> None:
        mock_subproc.return_value.returncode = 0
        mock_subproc.return_value.stdout = "OK"

        start = start_service(self.root, system_kind="systemd")
        self.assertTrue(start["started"])

        stop = stop_service(self.root, system_kind="systemd")
        self.assertTrue(stop["stopped"])

    def test_bounded_service_log_rotation(self) -> None:
        log_file = Path(self.tempdir.name) / "service.log"
        log_file.write_text("X" * 100, encoding="utf-8")
        _rotate_service_log(log_file, max_bytes=50, backup_count=2)
        self.assertTrue((Path(self.tempdir.name) / "service.log.1").exists())

    def test_unsupported_future_version_migration_rejected(self) -> None:
        """Verify target_version exceeding current max supported version raises GuardianError."""
        with self.assertRaises(GuardianError) as ctx:
            migrate_brain(self.brain, target_version=99)
        self.assertIn("exceeds current maximum supported schema version", str(ctx.exception))

    def test_brain_schema_migration_and_rollback(self) -> None:
        self.assertEqual(get_brain_schema_version(self.brain), 1)

        mig = migrate_brain(self.brain, target_version=2)
        self.assertTrue(mig["migrated"])
        self.assertEqual(mig["applied_versions"], [2])
        self.assertEqual(get_brain_schema_version(self.brain), 2)
        manifest = json.loads(
            (self.brain.directory / "schema_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["format"], "guardian-brain-schema")
        self.assertEqual(manifest["version"], 2)

    def test_cli_migrate_defaults_to_latest_supported_schema(self) -> None:
        from guardian_agent.cli import main

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(["service", "migrate", "--project", str(self.root)])

        self.assertEqual(exit_code, 0)
        self.assertEqual(get_brain_schema_version(self.brain), 2)
        self.assertEqual(json.loads(output.getvalue())["current_version"], 2)

    def test_brain_schema_migration_failure_restores_v1_snapshot(self) -> None:
        partial = self.brain.directory / "partial-v2-state.json"

        def fail_after_partial_write(_brain, _version):
            partial.write_text('{"partial": true}\\n', encoding="utf-8")
            raise OSError("simulated v2 migration failure")

        with patch(
            "guardian_agent.service._apply_schema_migration",
            side_effect=fail_after_partial_write,
        ):
            with self.assertRaises(GuardianError) as ctx:
                migrate_brain(self.brain, target_version=2)

        self.assertIn("Rolled back to pre-upgrade state", str(ctx.exception))
        self.assertEqual(get_brain_schema_version(self.brain), 1)
        self.assertFalse(partial.exists())
        self.assertFalse((self.brain.directory / "schema_manifest.json").exists())

    def test_service_crash_releases_lock_for_restart(self) -> None:
        with patch(
            "guardian_agent.service.service_run_once",
            side_effect=RuntimeError("simulated process crash"),
        ):
            with self.assertRaises(RuntimeError):
                service_run(
                    self.brain,
                    interval_seconds=1,
                    max_cycles=1,
                    dry_run=False,
                )

        restarted = service_run(
            self.brain,
            interval_seconds=1,
            max_cycles=1,
            dry_run=False,
        )
        self.assertEqual(restarted["cycles_completed"], 1)

    def test_backup_overwrite_protection(self) -> None:
        dest = Path(self.tempdir.name) / "custom_backup.tar.gz"
        dest.write_text("DUMMY", encoding="utf-8")

        with self.assertRaises(GuardianError):
            backup_brain(self.brain, destination=dest, overwrite=False)

    def test_backup_inside_agent_rejected(self) -> None:
        dest_inside = self.brain.directory / "inside_backup.tar.gz"
        with self.assertRaises(GuardianError):
            backup_brain(self.brain, destination=dest_inside)

    def test_backup_and_restore_brain(self) -> None:
        backup_res = backup_brain(self.brain)
        backup_path = Path(backup_res["backup_path"])
        self.assertTrue(backup_path.is_file())

        target_new = Path(self.tempdir.name) / "restored"
        target_new.mkdir()
        restore_res = restore_brain(target_new, backup_path)
        self.assertTrue((target_new / ".agent").is_dir())
        self.assertTrue((target_new / ".agent" / "PROJECT.md").is_file())

    def test_restore_brain_pre_validation_protects_existing(self) -> None:
        invalid_path = self.root / "fake_archive.tar.gz"
        invalid_path.write_text("NOT_A_TARFILE", encoding="utf-8")

        with self.assertRaises(GuardianError):
            restore_brain(self.root, invalid_path)

        self.assertTrue((self.root / ".agent").is_dir())
        self.assertTrue((self.root / ".agent" / "PROJECT.md").is_file())

    def test_restore_brain_rejects_missing_project_md(self) -> None:
        archive_path = Path(self.tempdir.name) / "no_project_md.tar.gz"
        dummy_dir = Path(self.tempdir.name) / "dummy_brain" / ".agent"
        dummy_dir.mkdir(parents=True)
        (dummy_dir / "OTHER.txt").write_text("DATA", encoding="utf-8")

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(dummy_dir, arcname=".agent")

        target_root = Path(self.tempdir.name) / "test_target"
        target_root.mkdir()
        target_agent = target_root / ".agent"
        target_agent.mkdir()
        (target_agent / "PROJECT.md").write_text("ORIGINAL", encoding="utf-8")

        with self.assertRaises(GuardianError):
            restore_brain(target_root, archive_path)

        self.assertTrue((target_agent / "PROJECT.md").is_file())
        self.assertEqual((target_agent / "PROJECT.md").read_text(encoding="utf-8"), "ORIGINAL")

    def test_restore_brain_rejects_absolute_path_member(self) -> None:
        archive_path = Path(self.tempdir.name) / "abs_path.tar.gz"
        tinfo = tarfile.TarInfo(name="/etc/passwd")
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.addfile(tinfo)

        with self.assertRaises(GuardianError):
            restore_brain(self.root, archive_path)

    def test_restore_rejects_symlink_member(self) -> None:
        archive_path = Path(self.tempdir.name) / "symlink_member.tar.gz"
        tinfo = tarfile.TarInfo(name=".agent/link")
        tinfo.type = tarfile.SYMTYPE
        tinfo.linkname = "/etc/passwd"
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.addfile(tinfo)

        with self.assertRaises(GuardianError):
            restore_brain(self.root, archive_path)

    @patch("shutil.move")
    def test_restore_rollback_when_final_move_fails(self, mock_move) -> None:
        backup_res = backup_brain(self.brain)
        backup_path = Path(backup_res["backup_path"])

        target_root = Path(self.tempdir.name) / "swap_fail_target"
        target_root.mkdir()
        target_agent = target_root / ".agent"
        target_agent.mkdir()
        (target_agent / "PROJECT.md").write_text("ORIGINAL_CONTENT", encoding="utf-8")

        real_move = shutil.move

        def side_effect(src, dst, *args, **kwargs):
            if ".agent_extract_tmp" in str(src):
                raise OSError("Simulated filesystem move error during extraction swap")
            return real_move(src, dst, *args, **kwargs)

        mock_move.side_effect = side_effect

        with self.assertRaises(GuardianError):
            restore_brain(target_root, backup_path)

        self.assertTrue((target_agent / "PROJECT.md").is_file())
        self.assertEqual((target_agent / "PROJECT.md").read_text(encoding="utf-8"), "ORIGINAL_CONTENT")

    @patch("guardian_agent.executor_worker.complete_task_with_model")
    def test_end_to_end_governance_cycle_and_emergency_stop(self, mock_model) -> None:
        """Verify full end-to-end cycle from intake to ticket processing and emergency stop blocking."""
        mock_model.return_value = {"model": "test-mock-model", "response": "Mocked completion text for coding"}
        task = "Implement end-to-end code change with tests"
        start = orchestrate_start(self.brain, task, limit=3, approved_paths=["src/", "tests/"])
        orch_id = start["orchestration_id"]

        orchestrate_confirm(self.brain, orch_id, task)
        orchestrate_dispatch(self.brain, orch_id)
        plan = plan_execution(self.brain, orch_id)

        # Service run cycle
        res = service_run_once(self.brain, max_tickets=2, dry_run=False)
        self.assertIn("supervisor_summary", res)
        self.assertIn("executor_summary", res)
        executed = res["executor_summary"]["executed"]
        self.assertEqual(len(executed), 1)
        dispatched = executed[0]
        self.assertEqual(dispatched["outcome"], "dispatched")

        verified = record_execution_result(
            self.brain,
            plan["id"],
            dispatched["stage_id"],
            dispatched["lease_id"],
            "passed",
            "Worker patch inspected; focused and full tests passed.",
            dispatch_id=dispatched["dispatch_id"],
        )
        self.assertEqual(verified["status"], "awaiting_final_review")
        review_stage = next_execution_stage(self.brain, plan["id"])["stage"]
        self.assertIn(review_stage["executor"], {"omniroute", "primary-review"})

        # Verify emergency stop immediately blocks service run
        kill_switch(self.brain)
        with self.assertRaises(GuardianError) as ctx:
            service_run_once(self.brain, max_tickets=2, dry_run=False)
        self.assertIn("Emergency stop is active", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
