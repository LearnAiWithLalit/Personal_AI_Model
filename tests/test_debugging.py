import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import GuardianError, initialize
from guardian_agent.debugging import add_debug_hypothesis, record_debug_attempt, start_debug_case


class DebuggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Debug Demo", "Debug ledger test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_requires_hypothesis_and_escalates_after_three_failures(self) -> None:
        case = start_debug_case(self.brain, "Request fails", "Run the focused failing test")
        with self.assertRaises(GuardianError):
            record_debug_attempt(self.brain, case["id"], "Guess", "test", False, "Still fails")
        for index in range(3):
            add_debug_hypothesis(
                self.brain, case["id"], f"Dependency mismatch {index}", "Observed version difference"
            )
            case = record_debug_attempt(
                self.brain, case["id"], "Change one dependency", "test command", False, "Same failure"
            )
        self.assertEqual(case["state"], "architecture_review_required")
        with self.assertRaises(GuardianError):
            add_debug_hypothesis(self.brain, case["id"], "Fourth guess", "No new evidence")


if __name__ == "__main__":
    unittest.main()
