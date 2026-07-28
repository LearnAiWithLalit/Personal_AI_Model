import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from guardian_agent.core import GuardianError, initialize
from guardian_agent.gateway import (
    add_provider,
    choose_model,
    complete_task_with_failover,
    complete_task_with_model,
    provider_summary,
    record_telemetry,
    resolve_configured_route,
)


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
        exact = resolve_configured_route(self.brain, "coding", "local", "local-coder")
        self.assertEqual(exact["model"], "local-coder")
        with self.assertRaises(GuardianError):
            resolve_configured_route(self.brain, "coding", "local", "missing")

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

    def test_complete_task_unreachable_provider_raises_error(self) -> None:
        add_provider(
            self.brain,
            provider_id="mock-local",
            kind="local",
            model_id="mock-coder",
            capabilities=["coding"],
            cost_tier="local",
            priority=1,
            base_url="http://127.0.0.1:59999/v1",
            credential_env=None,
        )
        with self.assertRaises(GuardianError):
            complete_task_with_model(self.brain, task="coding", prompt="Write a function")

    def test_prohibited_model_cannot_be_registered_or_executed(self) -> None:
        with self.assertRaises(GuardianError):
            add_provider(
                self.brain,
                provider_id="blocked",
                kind="openai-compatible",
                model_id="vendor/claude-sonnet-4.6",
                capabilities=["coding"],
                cost_tier="free",
                priority=1,
                base_url="http://localhost:3000/v1",
                credential_env=None,
            )
        with self.assertRaises(GuardianError):
            add_provider(
                self.brain,
                provider_id="blocked-alias",
                kind="openai-compatible",
                model_id="agy/claude-sonnet-4-6-thinking",
                capabilities=["coding"],
                cost_tier="free",
                priority=1,
                base_url="http://localhost:3000/v1",
                credential_env=None,
            )
        with self.assertRaises(GuardianError):
            complete_task_with_model(
                self.brain,
                "coding",
                "hello",
                route={
                    "provider": "manual",
                    "model": "claude_sonnet_4.6",
                    "base_url": "http://localhost:3000/v1",
                },
            )

    @patch("guardian_agent.gateway.complete_task_with_model")
    def test_bounded_failover_uses_next_healthy_route(self, completion) -> None:
        for provider_id, priority in (("first", 1), ("second", 2)):
            add_provider(
                self.brain,
                provider_id=provider_id,
                kind="local",
                model_id=f"{provider_id}-model",
                capabilities=["coding"],
                cost_tier="local",
                priority=priority,
                base_url="http://127.0.0.1:11434/v1",
                credential_env=None,
            )
        completion.side_effect = [
            GuardianError("first failed"),
            {"task": "coding", "provider": "second", "model": "second-model", "response": "ok"},
        ]
        result = complete_task_with_failover(
            self.brain, "coding", "small prompt", max_attempts=2
        )
        self.assertEqual(result["provider"], "second")
        self.assertEqual(result["routing"]["attempts"], 2)
        self.assertEqual(len(result["routing"]["failed_routes"]), 1)

    @patch("guardian_agent.gateway.complete_task_with_model")
    def test_failover_prioritizes_independent_quota_combos(self, completion) -> None:
        for index in range(3):
            add_provider(
                self.brain,
                provider_id="local-ollama",
                kind="local",
                model_id=f"local-{index}",
                capabilities=["coding"],
                cost_tier="local",
                priority=index,
                base_url="http://127.0.0.1:11434/v1",
                credential_env=None,
            )
        for index in range(3):
            add_provider(
                self.brain,
                provider_id="local-omniroute",
                kind="openai-compatible",
                model_id=f"combo-{index}",
                capabilities=["coding"],
                cost_tier="free-limited",
                priority=index,
                base_url="http://127.0.0.1:3000/v1",
                credential_env=None,
            )
        completion.side_effect = [
            GuardianError("failed"),
            GuardianError("failed"),
            GuardianError("failed"),
            {
                "task": "coding",
                "provider": "local-omniroute",
                "model": "combo-2",
                "response": "ok",
            },
        ]
        result = complete_task_with_failover(
            self.brain,
            "coding",
            "small task",
            max_attempts=4,
        )
        attempted = [
            call.kwargs["route"]["model"]
            for call in completion.call_args_list
        ]
        self.assertEqual(
            attempted,
            ["local-0", "combo-0", "combo-1", "combo-2"],
        )
        self.assertEqual(result["model"], "combo-2")

    def test_failover_enforces_limits_before_calls(self) -> None:
        with self.assertRaises(GuardianError):
            complete_task_with_failover(
                self.brain, "coding", "task", max_attempts=6
            )

    @patch("guardian_agent.gateway.urllib.request.urlopen")
    def test_completion_uses_configured_environment_credential(self, urlopen) -> None:
        import os
        os.environ["TEST_GATEWAY_KEY"] = "test-secret-token"
        self.addCleanup(os.environ.pop, "TEST_GATEWAY_KEY", None)
        add_provider(
            self.brain, provider_id="authenticated", kind="openai-compatible", model_id="model",
            capabilities=["coding"], cost_tier="local", priority=1,
            base_url="https://example.invalid/v1", credential_env="TEST_GATEWAY_KEY",
        )
        response = unittest.mock.MagicMock()
        response.read.return_value = b'{"choices":[{"message":{"content":"done"}}]}'
        urlopen.return_value.__enter__.return_value = response
        result = complete_task_with_model(self.brain, "coding", "hello")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret-token")
        import json
        self.assertFalse(json.loads(request.data.decode("utf-8"))["stream"])
        self.assertEqual(result["response"], "done")

    @patch("guardian_agent.gateway.urllib.request.urlopen")
    def test_subscription_equivalent_cost_is_not_billed(self, urlopen) -> None:
        add_provider(
            self.brain,
            provider_id="subscription",
            kind="openai-compatible",
            model_id="web-model",
            capabilities=["coding"],
            cost_tier="subscription",
            priority=1,
            base_url="https://example.invalid/v1",
            credential_env=None,
        )
        from guardian_agent.gateway import configure_provider_access
        configure_provider_access(self.brain, allow_subscription=True)
        response = unittest.mock.MagicMock()
        response.read.return_value = (
            b'{"choices":[{"message":{"content":"done"}}],'
            b'"usage":{"prompt_tokens":5,"completion_tokens":1,"total_tokens":6}}'
        )
        response.headers = {"x-omniroute-response-cost": "0.002"}
        urlopen.return_value.__enter__.return_value = response
        result = complete_task_with_model(self.brain, "coding", "hello")
        self.assertEqual(result["usage"]["cost_usd"], 0.0)
        self.assertEqual(
            result["usage"]["reported_equivalent_cost_usd"],
            0.002,
        )

    @patch("guardian_agent.gateway.urllib.request.urlopen")
    def test_omniroute_combo_is_reaudited_and_blocks_changed_members(self, urlopen) -> None:
        add_provider(
            self.brain,
            provider_id="local-omniroute",
            kind="openai-compatible",
            model_id="safe-combo",
            capabilities=["coding"],
            cost_tier="free",
            priority=1,
            base_url="http://localhost:3000/v1",
            credential_env=None,
            route_kind="omniroute-combo",
            member_models=["openrouter/qwen:free"],
        )
        response = unittest.mock.MagicMock()
        response.read.return_value = (
            b'{"combos":[{"name":"safe-combo","models":'
            b'[{"model":"agy/claude-sonnet-4-6"}]}]}'
        )
        urlopen.return_value.__enter__.return_value = response
        with self.assertRaisesRegex(GuardianError, "now contains prohibited"):
            complete_task_with_model(self.brain, "coding", "hello")
        self.assertEqual(urlopen.call_count, 1)

    @patch("guardian_agent.gateway.urllib.request.urlopen")
    def test_streaming_accumulates_chunks_usage_and_capacity(self, urlopen) -> None:
        add_provider(
            self.brain,
            provider_id="local-stream",
            kind="local",
            model_id="stream-model",
            capabilities=["coding"],
            cost_tier="local",
            priority=1,
            base_url="http://localhost:11434/v1",
            credential_env=None,
        )

        class StreamResponse:
            headers = {
                "X-RateLimit-Remaining-Requests": "9",
                "X-RateLimit-Limit-Requests": "10",
            }

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def __iter__(self):
                return iter([
                    b'data: {"choices":[{"delta":{"content":"hel"}}]}\n',
                    b'data: {"choices":[{"delta":{"content":"lo"}}]}\n',
                    b'data: {"choices":[],"usage":{"prompt_tokens":4,'
                    b'"completion_tokens":2,"total_tokens":6}}\n',
                    b"data: [DONE]\n",
                ])

        urlopen.return_value = StreamResponse()
        chunks = []
        result = complete_task_with_model(
            self.brain,
            "coding",
            "hello",
            stream=True,
            on_chunk=chunks.append,
        )
        self.assertEqual(result["response"], "hello")
        self.assertEqual(chunks, ["hel", "lo"])
        self.assertTrue(result["streamed"])
        self.assertEqual(result["usage"]["total_tokens"], 6)
        import json
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertTrue(payload["stream"])
        self.assertTrue(payload["stream_options"]["include_usage"])
        from guardian_agent.provider_capacity import provider_capacity_status
        capacity = provider_capacity_status(self.brain)
        self.assertEqual(
            capacity["routes"][0]["headers"]["x-ratelimit-remaining-requests"],
            "9",
        )

    def test_local_coding_routing_selects_qwen3_coder_30b(self) -> None:
        """Verify qwen3-coder:30b with priority=0 beats competing local models (e.g. qwen2.5-coder:14b) for coding tasks."""
        # Add competing model qwen2.5-coder:14b at priority 6
        add_provider(
            self.brain,
            provider_id="local-ollama-25",
            kind="local",
            model_id="qwen2.5-coder:14b",
            capabilities=["coding", "review"],
            cost_tier="local",
            priority=6,
            base_url="http://localhost:11434/v1",
            credential_env=None,
        )


        from guardian_agent.gateway import setup_ollama_provider
        setup = setup_ollama_provider(self.brain)
        self.assertEqual(setup["model"], "qwen3-coder:30b")

        route = choose_model(self.brain, "coding")
        self.assertEqual(route["provider"], "local-ollama")
        self.assertEqual(route["model"], "qwen3-coder:30b")



if __name__ == "__main__":
    unittest.main()
