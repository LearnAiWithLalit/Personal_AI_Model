import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import initialize
from guardian_agent.operator import audit_log_action, resolve_vault_reference


class OperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Operator Demo", "Operator and vault test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_resolve_vault_reference(self) -> None:
        env = {"MY_KEY": "secret_value_123"}
        val = resolve_vault_reference("vault://MY_KEY", env=env)
        self.assertEqual(val, "secret_value_123")

    def test_vault_reference_missing(self) -> None:
        val = resolve_vault_reference("vault://NON_EXISTENT", env={})
        self.assertIsNone(val)

    def test_audit_log_action(self) -> None:
        entry = audit_log_action(self.brain, action="browser_navigate", target="https://example.com", status="success")
        self.assertEqual(entry["action"], "browser_navigate")
        audit_file = self.brain.directory / "audit" / "audit.jsonl"
        self.assertTrue(audit_file.is_file())
        self.assertIn("browser_navigate", audit_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
