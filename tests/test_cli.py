import tempfile
import unittest
from pathlib import Path

from guardian_agent.cli import main
from guardian_agent.core import initialize


class CLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        initialize(self.root, "CLI Demo", "Testing CLI subcommands")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_cli_status(self) -> None:
        code = main(["status", "--project", str(self.root)])
        self.assertEqual(code, 0)

    def test_cli_skill_draft_and_list(self) -> None:
        code_draft = main([
            "skill", "draft",
            "--project", str(self.root),
            "--name", "unit-testing",
            "--description", "Write unit tests",
            "--instructions", "Test every module"
        ])
        self.assertEqual(code_draft, 0)

        code_list = main(["skill", "list", "--project", str(self.root)])
        self.assertEqual(code_list, 0)

    def test_cli_worker_roles_and_dispatch(self) -> None:
        code_roles = main(["worker", "roles", "--project", str(self.root)])
        self.assertEqual(code_roles, 0)

        code_dispatch = main([
            "worker", "dispatch",
            "--project", str(self.root),
            "--role", "frontend",
            "--task", "Create login form"
        ])
        self.assertEqual(code_dispatch, 0)


if __name__ == "__main__":
    unittest.main()
