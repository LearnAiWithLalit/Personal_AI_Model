"""CLI integration tests for worker command dispatch.

Tests that guardian hermes status, guardian hermes prepare,
guardian jcode status, and guardian aider status actually
execute their handlers and produce output. These tests would
have caught the Hermes CLI nesting bug (handler was inside the
jcode block, making it dead code).
"""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from guardian_agent.cli import main
from guardian_agent.core import initialize


def _capture_main(argv: list[str]) -> tuple[int, str]:
    """Run main() with given argv and capture stdout."""
    old_stdout = sys.stdout
    captured = io.StringIO()
    sys.stdout = captured
    try:
        code = main(argv)
    finally:
        sys.stdout = old_stdout
    return code, captured.getvalue()


class HermesCLIIntegrationTests(unittest.TestCase):
    """Integration tests for guardian hermes status and prepare."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        initialize(self.root, "Hermes CLI", "Hermes CLI integration tests")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @patch("guardian_agent.hermes._hermes_path", return_value="/usr/bin/hermes")
    @patch("guardian_agent.hermes._timeout_version", return_value="Hermes 0.2.0")
    def test_hermes_status_prints_json_when_binary_found(
        self, _version, _path
    ) -> None:
        """guardian hermes status must print JSON output (not silently return 0)."""
        code, output = _capture_main([
            "hermes", "status", "--project", str(self.root),
        ])
        self.assertEqual(code, 0)
        self.assertTrue(output.strip(), "hermes status produced no output")
        data = json.loads(output)
        self.assertIn("available", data)
        self.assertIn("restrictions", data)

    @patch("guardian_agent.hermes._hermes_path", return_value=None)
    def test_hermes_status_prints_json_when_binary_missing(
        self, _path
    ) -> None:
        """guardian hermes status must still print JSON when binary is missing."""
        code, output = _capture_main([
            "hermes", "status", "--project", str(self.root),
        ])
        self.assertEqual(code, 0)
        self.assertTrue(output.strip(), "hermes status produced no output")
        data = json.loads(output)
        self.assertFalse(data["available"])

    def test_hermes_prepare_creates_handoff_file(self) -> None:
        """guardian hermes prepare must create a handoff file and print JSON."""
        code, output = _capture_main([
            "hermes", "prepare", "--project", str(self.root),
            "--task", "Research authentication methods",
        ])
        self.assertEqual(code, 0)
        self.assertTrue(output.strip(), "hermes prepare produced no output")
        data = json.loads(output)
        self.assertIn("handoff", data)
        self.assertIn("read_paths", data)
        self.assertIn("restrictions", data)
        # Verify the handoff file was actually created
        handoff_path = Path(data["handoff"])
        self.assertTrue(handoff_path.is_file(), f"Handoff file not found: {handoff_path}")
        text = handoff_path.read_text(encoding="utf-8")
        self.assertIn("Research authentication methods", text)

    def test_hermes_prepare_with_read_paths(self) -> None:
        """guardian hermes prepare must accept --read-path and include it."""
        # Create a test file to reference
        test_dir = self.root / "docs"
        test_dir.mkdir(parents=True, exist_ok=True)
        (test_dir / "notes.md").write_text("# Notes", encoding="utf-8")

        code, output = _capture_main([
            "hermes", "prepare", "--project", str(self.root),
            "--task", "Review docs",
            "--read-path", "docs/notes.md",
        ])
        self.assertEqual(code, 0)
        data = json.loads(output)
        self.assertIn("docs/notes.md", str(data["read_paths"]))


class JCodeCLIIntegrationTests(unittest.TestCase):
    """Integration tests for guardian jcode status."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        initialize(self.root, "JCode CLI", "JCode CLI integration tests")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @patch("guardian_agent.jcode._timeout_version", return_value="jcode 0.5.0")
    @patch("guardian_agent.jcode._jcode_path", return_value="/usr/bin/jcode")
    @patch("guardian_agent.jcode.subprocess.run")
    def test_jcode_status_prints_json_when_binary_found(
        self, mock_run, _path, _version
    ) -> None:
        """guardian jcode status must print JSON output.

        Mocks _timeout_version directly so subprocess.run is only
        used by the probe's --help invocation (not the version check).
        """
        mock_run.return_value.stdout = (
            "Usage: jcode [OPTIONS] [COMMAND]\n"
            "  --read <PATH>        Read context\n"
            "  --message <TEXT>     Task description\n"
            "  --dry-run            Preview mode\n"
        )
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0

        code, output = _capture_main([
            "jcode", "status", "--project", str(self.root),
        ])
        self.assertEqual(code, 0)
        self.assertTrue(output.strip(), "jcode status produced no output")
        data = json.loads(output)
        self.assertIn("available", data)
        self.assertIn("restrictions", data)

    @patch("guardian_agent.jcode._jcode_path", return_value=None)
    def test_jcode_status_prints_json_when_binary_missing(
        self, _path
    ) -> None:
        """guardian jcode status must still print JSON when JCode is not installed."""
        code, output = _capture_main([
            "jcode", "status", "--project", str(self.root),
        ])
        self.assertEqual(code, 0)
        self.assertTrue(output.strip(), "jcode status produced no output")
        data = json.loads(output)
        self.assertFalse(data["available"])


class AiderCLIIntegrationTests(unittest.TestCase):
    """Integration tests for guardian aider status."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        initialize(self.root, "Aider CLI", "Aider CLI integration tests")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @patch("guardian_agent.aider.shutil.which", return_value="/usr/bin/aider")
    @patch("guardian_agent.aider.subprocess.run")
    def test_aider_status_prints_json(self, mock_run, _which) -> None:
        """guardian aider status must print JSON output with availability info."""
        mock_run.return_value.stdout = "Aider 0.70.0\n"
        mock_run.return_value.stderr = ""
        mock_run.return_value.returncode = 0

        code, output = _capture_main([
            "aider", "status", "--project", str(self.root),
        ])
        self.assertEqual(code, 0)
        self.assertTrue(output.strip(), "aider status produced no output")
        data = json.loads(output)
        self.assertIn("available", data)
        self.assertIn("backends", data)

    @patch("guardian_agent.aider.shutil.which", return_value=None)
    def test_aider_status_prints_json_when_not_installed(
        self, _which
    ) -> None:
        """guardian aider status must still print JSON when aider is not installed."""
        code, output = _capture_main([
            "aider", "status", "--project", str(self.root),
        ])
        self.assertEqual(code, 0)
        self.assertTrue(output.strip(), "aider status produced no output")
        data = json.loads(output)
        self.assertFalse(data["available"])


if __name__ == "__main__":
    unittest.main()
