import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import initialize
from guardian_agent.research import build_handoff_package, inspect_repository


class ResearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Demo Research", "Repository and handoff test")
        (self.root / "src").mkdir(exist_ok=True)
        (self.root / "src" / "main.py").write_text("print('hello')", encoding="utf-8")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_inspect_repository(self) -> None:
        repo_info = inspect_repository(self.root)
        self.assertIn("files", repo_info)
        self.assertTrue(any("main.py" in f for f in repo_info["files"]))

    def test_build_handoff_package(self) -> None:
        pkg = build_handoff_package(self.brain, "Add logging", target_files=["src/main.py"])
        self.assertIn("confirmed_goal", pkg)
        self.assertIn("target_files", pkg)
        self.assertIn("src/main.py", pkg["target_files"])
        self.assertIn("handoff_markdown", pkg)


if __name__ == "__main__":
    unittest.main()
