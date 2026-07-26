import tempfile
import unittest
from pathlib import Path

from guardian_agent.coding import apply_file_edits, run_coding_loop, run_verification
from guardian_agent.core import initialize


class CodingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Coding Demo", "Verification sandbox test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_apply_file_edits(self) -> None:
        edits = {"src/sample.py": "print('hello from test')"}
        res = apply_file_edits(self.root, edits)
        self.assertEqual(res["status"], "success")
        self.assertTrue((self.root / "src/sample.py").exists())
        self.assertEqual((self.root / "src/sample.py").read_text(encoding="utf-8"), "print('hello from test')")

    def test_run_verification(self) -> None:
        res = run_verification(self.root, "python3 -c 'print(\"ok\")'")
        self.assertTrue(res["success"])
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("ok", res["stdout"])

    def test_run_coding_loop(self) -> None:
        result = run_coding_loop(
            self.brain,
            task="Add helper script",
            file_edits={"helper.py": "x = 42\n"},
            test_command="python3 -c 'import helper; assert helper.x == 42'",
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["status"], "completed")


if __name__ == "__main__":
    unittest.main()
