import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from guardian_agent.core import GuardianError, initialize
from guardian_agent.council import configure_council, load_council, run_council


class CouncilTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Council Demo", "Council test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_configuration_is_persistent(self) -> None:
        updated = configure_council(self.brain, max_members=2, chairman="local:model")
        self.assertEqual(updated["max_members"], 2)
        self.assertEqual(load_council(self.brain)["chairman"], "local:model")

    def test_council_rejects_external_side_effect_tasks(self) -> None:
        with self.assertRaises(GuardianError):
            run_council(self.brain, task="coding", prompt="Make a payment")

    @patch("guardian_agent.council.complete_task_with_model")
    @patch("guardian_agent.council.list_routes_for_task")
    def test_council_records_opinions_reviews_and_synthesis(self, routes, complete) -> None:
        routes.return_value = [
            {"provider": "one", "model": "m1", "task": "planning"},
            {"provider": "two", "model": "m2", "task": "planning"},
        ]
        complete.side_effect = [
            {"response": "First opinion"}, {"response": "Second opinion"},
            {"response": "Review one"}, {"response": "Review two"}, {"response": "Chair summary"},
        ]
        result = run_council(self.brain, task="planning", prompt="Choose a design", max_members=2)
        self.assertEqual(result["response"], "Chair summary")
        self.assertEqual(len(result["members"]), 2)
        self.assertTrue(Path(result["artifact"]).is_file())
        reviewer_prompt = complete.call_args_list[2].kwargs.get("prompt") or complete.call_args_list[2].args[2]
        self.assertIn("Opinion 1", reviewer_prompt)
        self.assertNotIn("provider", reviewer_prompt.lower())


if __name__ == "__main__":
    unittest.main()
