import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import GuardianError, initialize
from guardian_agent.gateway import add_provider, choose_model, provider_summary, record_telemetry, complete_task_with_model


class ModelGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Demo", "Gateway test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_router_prefers_local_capable_model(self) -> None:
        add_provider(
            self.brain,
            provider_id="free-cloud",
            kind="openai-compatible",
            model_id="free-general",
            capabilities=["general"],
            cost_tier="free",
            priority=1,
            base_url="https://example.invalid/v1",
            credential_env="FREE_CLOUD_KEY",
        )
        add_provider(
            self.brain,
            provider_id="local",
            kind="local",
            model_id="local-coder",
            capabilities=["coding", "review"],
            cost_tier="local",
            priority=50,
            base_url="http://localhost:11434/v1",
            credential_env=None,
        )

        route = choose_model(self.brain, "coding")

        self.assertEqual(route["provider"], "local")
        self.assertEqual(route["model"], "local-coder")
        self.assertEqual(len(provider_summary(self.brain)), 2)

    def test_paid_provider_is_not_selected_without_policy_change(self) -> None:
        add_provider(
            self.brain,
            provider_id="paid",
            kind="openai-compatible",
            model_id="strong-model",
            capabilities=["coding"],
            cost_tier="paid",
            priority=1,
            base_url=None,
            credential_env="PAID_KEY",
        )

        with self.assertRaises(GuardianError):
            choose_model(self.brain, "coding")

    def test_record_telemetry(self) -> None:
        record_telemetry(self.brain, task="coding", provider="local", model="local-coder", tokens=150, cost_usd=0.0)
        costs_doc = self.brain.document("COSTS.md").read_text(encoding="utf-8")
        self.assertIn("local-coder", costs_doc)
        self.assertIn("150", costs_doc)

    def test_complete_task_with_model(self) -> None:
        add_provider(
            self.brain,
            provider_id="mock-local",
            kind="local",
            model_id="mock-coder",
            capabilities=["coding"],
            cost_tier="local",
            priority=1,
            base_url=None,
            credential_env=None,
        )
        res = complete_task_with_model(self.brain, task="coding", prompt="Write a function")
        self.assertIn("response", res)
        self.assertEqual(res["provider"], "mock-local")


if __name__ == "__main__":
    unittest.main()
