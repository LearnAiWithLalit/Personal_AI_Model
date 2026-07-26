import tempfile
import unittest
from pathlib import Path

from guardian_agent.bootstrap import generate_bootstrap
from guardian_agent.core import GuardianError, initialize


class BootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Bootstrap Demo", "Harness exports")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_generate_all_preserves_existing_files(self) -> None:
        first = generate_bootstrap(self.brain, "all")
        self.assertEqual(len(first["targets"]), 6)
        second = generate_bootstrap(self.brain, "all")
        self.assertTrue(all(item["status"] == "preserved" for item in second["targets"]))

    def test_generate_root_harness_preserves_and_overwrites(self) -> None:
        first = generate_bootstrap(self.brain, "all", root_harness=True)
        self.assertEqual(len(first["targets"]), 6)
        self.assertTrue((self.brain.root / ".cursor" / "rules" / "guardian.mdc").is_file())

        second = generate_bootstrap(self.brain, "all", root_harness=True, overwrite=False)
        self.assertTrue(all(item["status"] == "preserved" for item in second["targets"]))

        third = generate_bootstrap(self.brain, "cursor", root_harness=True, overwrite=True)
        self.assertEqual(third["targets"][0]["status"], "created")

    def test_unknown_target_raises_error(self) -> None:
        with self.assertRaises(GuardianError):
            generate_bootstrap(self.brain, "invalid_target")


if __name__ == "__main__":
    unittest.main()
