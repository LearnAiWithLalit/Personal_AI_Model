import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from guardian_agent.core import GuardianError, initialize
from guardian_agent.provider_capacity import (
    provider_capacity_status,
    record_provider_capacity,
    require_capacity_available,
)


class ProviderCapacityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Capacity", "Tests")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @patch("guardian_agent.provider_capacity.time.time", return_value=1000.0)
    def test_only_allowlisted_headers_are_recorded(self, _time) -> None:
        record = record_provider_capacity(
            self.brain,
            "provider",
            "model",
            {
                "Authorization": "Bearer secret",
                "Set-Cookie": "private",
                "X-RateLimit-Remaining-Requests": "5",
                "X-OmniRoute-Response-Cost": "0.0",
            },
            latency_ms=12,
            status="success",
        )
        self.assertNotIn("authorization", record["headers"])
        self.assertNotIn("set-cookie", record["headers"])
        self.assertEqual(record["headers"]["x-ratelimit-remaining-requests"], "5")
        self.assertEqual(provider_capacity_status(self.brain)["event_count"], 1)

    @patch("guardian_agent.provider_capacity.time.time", return_value=1000.0)
    def test_observed_exhaustion_blocks_without_sending(self, _time) -> None:
        record_provider_capacity(
            self.brain,
            "provider",
            "model",
            {
                "X-RateLimit-Remaining-Requests": "0",
                "Retry-After": "30",
            },
            latency_ms=10,
            status="rate_limited",
        )
        with self.assertRaisesRegex(GuardianError, "no request was sent"):
            require_capacity_available(self.brain, "provider", "model")
        require_capacity_available(self.brain, "provider", "different-model")

    @patch("guardian_agent.provider_capacity.time.time", return_value=1000.0)
    def test_prompt_inflation_creates_routing_penalty(self, _time) -> None:
        record = record_provider_capacity(
            self.brain,
            "provider",
            "model",
            {},
            latency_ms=10,
            status="success",
            usage={"prompt_tokens": 100, "completion_tokens": 2, "total_tokens": 102},
            estimated_prompt_tokens=10,
        )
        self.assertTrue(record["efficiency_warning"])
        self.assertEqual(record["prompt_inflation_ratio"], 10.0)
        from guardian_agent.provider_capacity import provider_efficiency_penalty
        self.assertEqual(provider_efficiency_penalty(self.brain, "provider", "model"), 10)
        from guardian_agent.provider_capacity import provider_prompt_reservation_multiplier
        self.assertEqual(
            provider_prompt_reservation_multiplier(self.brain, "provider", "model"),
            10.0,
        )
        self.assertEqual(
            provider_prompt_reservation_multiplier(
                self.brain, "local-omniroute", "unknown"
            ),
            128.0,
        )
        preserved = record_provider_capacity(
            self.brain,
            "provider",
            "model",
            {},
            latency_ms=2,
            status="probe_success",
        )
        self.assertEqual(preserved["prompt_inflation_ratio"], 10.0)
        self.assertEqual(preserved["usage"]["total_tokens"], 102)


if __name__ == "__main__":
    unittest.main()
