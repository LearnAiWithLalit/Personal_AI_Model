import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import confirm, initialize, intake, record_decision
from guardian_agent.export import export_handoff


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Export Demo", "Testing token-saving handoffs")
        intake(self.brain, "Build user login")
        confirm(self.brain, "Build user login with JWT auth")
        record_decision(self.brain, "Auth Token", "Use JWT tokens stored in HTTP-only cookies")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_export_antigravity_format(self) -> None:
        res = export_handoff(self.brain, target="antigravity")
        self.assertEqual(res["target"], "antigravity")
        self.assertTrue(Path(res["path"]).is_file())
        content = Path(res["path"]).read_text(encoding="utf-8")
        self.assertIn("Antigravity Handoff Package", content)
        self.assertIn("Build user login with JWT auth", content)

    def test_export_codex_format(self) -> None:
        res = export_handoff(self.brain, target="codex")
        self.assertEqual(res["target"], "codex")
        self.assertTrue(Path(res["path"]).is_file())
        content = Path(res["path"]).read_text(encoding="utf-8")
        self.assertIn("Codex Handoff Package", content)

    def test_export_claude_format(self) -> None:
        res = export_handoff(self.brain, target="claude")
        self.assertEqual(res["target"], "claude")
        self.assertTrue(Path(res["path"]).is_file())
        content = Path(res["path"]).read_text(encoding="utf-8")
        self.assertIn("Claude Code Handoff Package", content)


if __name__ == "__main__":
    unittest.main()
