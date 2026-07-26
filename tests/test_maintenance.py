import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from guardian_agent.core import GuardianError, initialize
from guardian_agent.maintenance import (
    add_maintenance_job,
    initialize_maintenance,
    maintenance_status,
    run_due_maintenance,
    scheduler_instructions,
)
from guardian_agent.runtime import kill_switch


class MaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Maintenance", "Tests")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_safe_defaults_run_without_model_completions(self) -> None:
        config = initialize_maintenance(self.brain)
        self.assertEqual(len(config["jobs"]), 3)
        self.assertFalse(config["policy"]["model_completions_allowed"])
        result = run_due_maintenance(self.brain)
        self.assertEqual(result["executed"], 3)
        self.assertEqual(result["model_completions_spent"], 0)
        self.assertTrue(all(
            record["status"] in {"passed", "attention"}
            for record in result["records"]
        ))
        self.assertEqual(maintenance_status(self.brain)["due_count"], 0)

    def test_network_probe_requires_explicit_target(self) -> None:
        initialize_maintenance(self.brain)
        with self.assertRaisesRegex(GuardianError, "provider_id and model_id"):
            add_maintenance_job(
                self.brain,
                "provider-probe",
                3600,
            )
        job = add_maintenance_job(
            self.brain,
            "provider-probe",
            3600,
            provider_id="local-ollama",
            model_id="model",
        )
        self.assertEqual(job["parameters"]["provider_id"], "local-ollama")

    @patch("guardian_agent.maintenance._execute_job", side_effect=RuntimeError("temporary"))
    def test_failures_receive_backoff(self, _execute) -> None:
        initialize_maintenance(self.brain)
        result = run_due_maintenance(self.brain, max_jobs=1)
        record = result["records"][0]
        self.assertEqual(record["status"], "failed")
        self.assertGreater(record["next_run_epoch"], 0)
        status = maintenance_status(self.brain)
        failed = next(job for job in status["jobs"] if job["id"] == record["id"])
        self.assertEqual(failed["failure_count"], 1)
        self.assertIn("temporary", failed["last_error"])

    def test_kill_switch_blocks_runner_and_scheduler_is_non_mutating(self) -> None:
        initialize_maintenance(self.brain)
        kill_switch(self.brain)
        with self.assertRaisesRegex(GuardianError, "Emergency stop"):
            run_due_maintenance(self.brain)
        instructions = scheduler_instructions(self.brain)
        self.assertEqual(instructions["command_argv"][0], "guardian")
        self.assertIn("does not install", instructions["note"])


if __name__ == "__main__":
    unittest.main()
