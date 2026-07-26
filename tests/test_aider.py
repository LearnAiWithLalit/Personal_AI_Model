import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from guardian_agent.aider import (
    aider_status,
    build_aider_command,
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


if __name__ == "__main__":
    unittest.main()
