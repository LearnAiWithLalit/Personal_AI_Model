import tempfile
import unittest
from pathlib import Path

from guardian_agent.browser_operator import check_playwright_available, inspect_web_page
from guardian_agent.core import initialize


class BrowserOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Browser Demo", "Browser operator test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_playwright_availability_check(self) -> None:
        avail = check_playwright_available()
        self.assertIsInstance(avail, bool)

    def test_inspect_web_page_graceful_fallback(self) -> None:
        res = inspect_web_page(self.brain, url="https://example.invalid")
        self.assertIn("status", res)
        self.assertIn("method", res)
        self.assertTrue(res["status"] in {"success", "fallback_http", "failed"})


if __name__ == "__main__":
    unittest.main()
