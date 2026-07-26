import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import initialize
from guardian_agent.gateway import (
    discover_free_providers,
    list_providers,
    setup_ollama_provider,
)


class FreeGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Free Gateway", "Testing free providers")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_discover_free_providers(self) -> None:
        added = discover_free_providers(self.brain)
        self.assertGreater(len(added), 0)
        providers = list_providers(self.brain)
        self.assertTrue(any(p.id.startswith("openrouter-free") for p in providers))

    def test_setup_ollama_provider(self) -> None:
        res = setup_ollama_provider(self.brain, model_name="qwen2.5-coder")
        self.assertEqual(res["provider_id"], "local-ollama")
        providers = list_providers(self.brain)
        self.assertTrue(any(p.id == "local-ollama" for p in providers))


if __name__ == "__main__":
    unittest.main()
