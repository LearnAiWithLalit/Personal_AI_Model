import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import initialize
from guardian_agent.workers import dispatch_worker, list_worker_roles


class SpecialistWorkersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Worker Demo", "Specialist worker test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_list_worker_roles(self) -> None:
        roles = list_worker_roles()
        self.assertIn("frontend", roles)
        self.assertIn("backend", roles)
        self.assertIn("security", roles)

    def test_dispatch_worker(self) -> None:
        result = dispatch_worker(self.brain, role="frontend", task="Build responsive navigation header")
        self.assertEqual(result["role"], "frontend")
        self.assertEqual(result["status"], "dispatched")
        self.assertIn("package_path", result)


if __name__ == "__main__":
    unittest.main()
