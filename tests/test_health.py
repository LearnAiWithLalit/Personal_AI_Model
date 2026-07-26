import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import initialize
from guardian_agent.health import check_provider_health, record_provider_error


class HealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Health Demo", "Testing Provider Health System")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_check_provider_health(self) -> None:
        status_res = check_provider_health(self.brain, provider_id="local-ollama")
        self.assertIn("healthy", status_res)
        self.assertIn("error_count", status_res)

    def test_record_provider_error(self) -> None:
        for _ in range(3):
            record_provider_error(self.brain, provider_id="cloud-api", error_msg="HTTP 429 Rate Limit Exceeded")
            
        status_res = check_provider_health(self.brain, provider_id="cloud-api")
        self.assertEqual(status_res["error_count"], 3)
        self.assertFalse(status_res["healthy"])


if __name__ == "__main__":
    unittest.main()
