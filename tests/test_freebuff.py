import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import initialize
from guardian_agent.freebuff import create_freebuff_handoff, freebuff_status


class FreebuffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Freebuff Demo", "Freebuff integration test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_prepare_creates_compact_handoff(self) -> None:
        result = create_freebuff_handoff(self.brain, "Add tests for the parser")
        handoff = Path(result["handoff"])
        self.assertTrue(handoff.is_file())
        self.assertIn("Add tests for the parser", handoff.read_text(encoding="utf-8"))

    def test_status_is_structured(self) -> None:
        result = freebuff_status()
        self.assertIn("available", result)


if __name__ == "__main__":
    unittest.main()
