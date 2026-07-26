import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import initialize
from guardian_agent.creative import record_creative_artifact, list_creative_artifacts


class CreativeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Creative Demo", "Creative artifact test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_record_and_list_creative_artifact(self) -> None:
        art = record_creative_artifact(
            self.brain,
            tool_name="canva",
            asset_name="Homepage Banner",
            asset_url="https://canva.com/design/123",
            notes="Brand colors added",
        )
        self.assertEqual(art["tool"], "canva")
        self.assertEqual(art["asset_name"], "Homepage Banner")
        
        all_arts = list_creative_artifacts(self.brain)
        self.assertEqual(len(all_arts), 1)
        self.assertEqual(all_arts[0]["asset_name"], "Homepage Banner")


if __name__ == "__main__":
    unittest.main()
