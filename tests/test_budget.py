import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from guardian_agent.budget import (
    budget_status,
    reserve_budget,
    settle_budget,
)
from guardian_agent.core import GuardianError, initialize
from guardian_agent.gateway import (
    add_provider,
    complete_task_with_model,
    configure_budget,
    get_budget_status,
)


class BudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Budget", "Budget tests")
        self.policy = {
            "daily_token_budget": 100,
            "daily_cost_budget_usd": 1.0,
            "max_completion_tokens": 20,
        }
        self.route = {
            "provider": "local",
            "model": "local-model",
            "cost_tier": "local",
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_reservation_prevents_concurrent_overspend_and_settles(self) -> None:
        first = reserve_budget(self.brain, self.policy, self.route, "hello", "worker")
        with self.assertRaisesRegex(GuardianError, "token budget"):
            reserve_budget(
                self.brain,
                self.policy,
                self.route,
                "x" * 300,
                "worker",
            )
        settled = settle_budget(
            self.brain,
            first,
            actual_tokens=7,
            actual_cost_usd=0.0,
            charge_reservation=False,
        )
        self.assertEqual(settled["tokens"], 7)
        status = budget_status(self.brain, self.policy)
        self.assertEqual(status["spent_tokens"], 7)
        self.assertEqual(status["active_reservations"], 0)

    def test_paid_route_without_verified_pricing_is_blocked(self) -> None:
        paid = {"provider": "paid", "model": "model", "cost_tier": "paid"}
        with self.assertRaisesRegex(GuardianError, "no verified pricing"):
            reserve_budget(self.brain, self.policy, paid, "hello", "worker")

    def test_prepaid_subscription_route_has_no_per_call_cost(self) -> None:
        subscription = {
            "provider": "local-omniroute",
            "model": "claude-opus",
            "cost_tier": "subscription",
        }
        reservation = reserve_budget(
            self.brain,
            self.policy,
            subscription,
            "hello",
            "worker",
        )
        self.assertEqual(reservation.cost_usd, 0.0)
        settle_budget(
            self.brain,
            reservation,
            actual_tokens=1,
            actual_cost_usd=0.0,
            charge_reservation=False,
        )
        limited = {
            "provider": "local-omniroute",
            "model": "quota-combo",
            "cost_tier": "free-limited",
        }
        limited_reservation = reserve_budget(
            self.brain,
            self.policy,
            limited,
            "hello",
            "worker",
        )
        self.assertEqual(limited_reservation.cost_usd, 0.0)

    def test_configure_and_show_budget(self) -> None:
        configured = configure_budget(
            self.brain,
            daily_tokens=500,
            daily_cost_usd=2.5,
            max_completion_tokens=30,
        )
        self.assertEqual(configured["daily_token_budget"], 500)
        self.assertEqual(get_budget_status(self.brain)["daily_cost_budget_usd"], 2.5)

    @patch("guardian_agent.gateway.urllib.request.urlopen")
    def test_completion_records_provider_usage_and_budget(self, urlopen) -> None:
        add_provider(
            self.brain,
            provider_id="local",
            kind="local",
            model_id="local-model",
            capabilities=["coding"],
            cost_tier="local",
            priority=1,
            base_url="http://localhost:11434/v1",
            credential_env=None,
        )
        response = unittest.mock.MagicMock()
        response.read.return_value = (
            b'{"choices":[{"message":{"content":"done"}}],'
            b'"usage":{"prompt_tokens":5,"completion_tokens":2,"total_tokens":7}}'
        )
        response.headers = {}
        urlopen.return_value.__enter__.return_value = response
        result = complete_task_with_model(self.brain, "coding", "hello")
        self.assertEqual(result["usage"]["total_tokens"], 7)
        self.assertEqual(result["usage"]["source"], "provider")
        self.assertEqual(get_budget_status(self.brain)["spent_tokens"], 7)


if __name__ == "__main__":
    unittest.main()
