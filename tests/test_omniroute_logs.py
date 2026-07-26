import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from guardian_agent.core import GuardianError, initialize
from guardian_agent.gateway import add_provider, list_routes_for_task
from guardian_agent.omniroute_logs import (
    audit_omniroute_logs,
    omniroute_log_penalty,
)


class _LogResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit):
        return json.dumps([
            "2026-07-26T14:00:00Z | qwen3.7-max | QWEN-WEB | private@example.com | 10 | 1 | 500",
            "2026-07-26T13:59:00Z | qwen3.7-plus | QWEN-WEB | secret-connection | 10 | 1 | 200",
            "2026-07-26T13:58:00Z | qwen3.7-max | QWEN-WEB | secret-connection | 10 | 1 | 429",
            "malformed raw account@example.com line",
        ]).encode("utf-8")


class OmniRouteLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(
            Path(self.tempdir.name) / "demo",
            "Omni Logs",
            "Redacted health",
        )
        add_provider(
            self.brain,
            provider_id="local-omniroute",
            kind="openai-compatible",
            model_id="claude-opus",
            capabilities=["coding"],
            cost_tier="free-limited",
            priority=1,
            base_url="http://localhost:3000/v1",
            credential_env=None,
            route_kind="omniroute-combo",
            member_models=[
                "qwen-web/qwen3.7-max",
                "qwen-web/qwen3.7-plus",
            ],
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @patch(
        "guardian_agent.omniroute_logs.urllib.request.urlopen",
        return_value=_LogResponse(),
    )
    def test_audit_redacts_connections_and_penalizes_unstable_combo(self, _urlopen) -> None:
        result = audit_omniroute_logs(self.brain, limit=10)
        self.assertEqual(result["event_count"], 3)
        self.assertEqual(result["failure_count"], 2)
        route = result["routes"][0]
        self.assertEqual(route["model"], "claude-opus")
        self.assertEqual(route["routing_penalty"], 30)
        artifact_text = Path(result["artifact"]).read_text(encoding="utf-8")
        self.assertNotIn("private@example.com", artifact_text)
        self.assertNotIn("secret-connection", artifact_text)
        self.assertEqual(omniroute_log_penalty(self.brain, "claude-opus"), 30)
        routed = list_routes_for_task(self.brain, "coding")[0]
        self.assertEqual(routed["log_health_penalty"], 30)

    def test_non_loopback_log_source_is_blocked(self) -> None:
        with self.assertRaisesRegex(GuardianError, "loopback"):
            audit_omniroute_logs(
                self.brain,
                base_url="https://example.com",
            )


if __name__ == "__main__":
    unittest.main()
