import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import initialize
from guardian_agent.vault import (
    get_secret,
    has_secret,
    redact_secrets,
    store_secret,
)


class VaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Vault Demo", "Testing Encrypted Vault")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_store_and_retrieve_secret(self) -> None:
        res = store_secret(self.brain, key="OPENAI_KEY", secret_value="sk-test-secret-value-12345")
        self.assertEqual(res["vault_uri"], "vault://OPENAI_KEY")
        self.assertTrue(has_secret(self.brain, "OPENAI_KEY"))

        val = get_secret(self.brain, "vault://OPENAI_KEY")
        self.assertEqual(val, "sk-test-secret-value-12345")

    def test_redact_secrets(self) -> None:
        store_secret(self.brain, key="MY_PASS", secret_value="SuperSecretPassword99")
        raw_text = "Logging in with SuperSecretPassword99 into the service."
        cleaned = redact_secrets(self.brain, raw_text)
        self.assertNotIn("SuperSecretPassword99", cleaned)
        self.assertIn("[REDACTED_SECRET]", cleaned)


if __name__ == "__main__":
    unittest.main()
