import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from guardian_agent.core import GuardianError, initialize
from guardian_agent.gateway import (
    configure_provider_access,
    discover_free_providers,
    discover_ollama_models,
    discover_omniroute_combos,
    list_providers,
    list_routes_for_task,
    mark_omniroute_combo_free_limited,
    probe_provider_capacity,
    setup_ollama_provider,
    setup_omniroute_provider,
)


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return (
            b'{"models":['
            b'{"name":"qwen2.5-coder:14b","size":9000},'
            b'{"name":"gemma3:12b","size":8100},'
            b'{"name":"claude-sonnet-4.6","size":1}'
            b']}'
        )


class _FakeComboResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return (
            b'{"combos":['
            b'{"name":"free-coding","models":['
            b'{"model":"openrouter/qwen-coder:free"},'
            b'{"model":"openrouter/openrouter/free"}],"strategy":"fallback"},'
            b'{"name":"mixed-danger","models":['
            b'{"model":"agy/claude-sonnet-4-6"}],"strategy":"round-robin"}'
            b']}'
        )


class _FakeModelsResponse:
    headers = {"X-RateLimit-Remaining-Requests": "12"}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit):
        return b'{"object":"list","data":[{"id":"qwen2.5-coder:14b"}]}'


class _FakeSubscriptionComboResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return (
            b'{"combos":['
            b'{"name":"claude-opus-5","models":['
            b'{"model":"cgpt-web/gpt-5.5"}],"strategy":"round-robin"},'
            b'{"name":"claude-opus","models":['
            b'{"model":"qwen-web/qwen3.7-max"},'
            b'{"model":"qwen-web/qwen3.7-plus"},'
            b'{"model":"qwen-web/qwen3.6-plus"}],"strategy":"round-robin"}'
            b']}'
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

    def test_setup_omniroute_uses_live_endpoint_and_model_policy(self) -> None:
        result = setup_omniroute_provider(self.brain, "allowed-free-combo")
        self.assertEqual(result["base_url"], "http://localhost:3000/v1")
        with self.assertRaises(GuardianError):
            setup_omniroute_provider(self.brain, "claude-sonnet-4.6")
        with self.assertRaises(GuardianError):
            setup_omniroute_provider(self.brain, "auto/best-coding")

    @patch("guardian_agent.gateway.urllib.request.urlopen", return_value=_FakeResponse())
    def test_discover_ollama_registers_allowed_local_models(self, _urlopen) -> None:
        result = discover_ollama_models(self.brain)
        self.assertEqual([item["model"] for item in result], [
            "qwen2.5-coder:14b", "gemma3:12b",
        ])
        route = next(
            model
            for provider in list_providers(self.brain)
            if provider.id == "local-ollama"
            for model in provider.models
            if model.id == "qwen2.5-coder:14b"
        )
        self.assertIn("coding", route.capabilities)
        from guardian_agent.gateway import choose_model
        self.assertEqual(choose_model(self.brain, "coding")["model"], "qwen2.5-coder:14b")
        self.assertEqual(choose_model(self.brain, "research")["model"], "gemma3:12b")

    @patch("guardian_agent.gateway.urllib.request.urlopen", return_value=_FakeComboResponse())
    def test_discover_omniroute_blocks_prohibited_combo_members(self, _urlopen) -> None:
        result = discover_omniroute_combos(self.brain)
        self.assertEqual(result["registered_count"], 1)
        self.assertEqual(result["blocked_count"], 1)
        blocked = next(item for item in result["combos"] if item["name"] == "mixed-danger")
        self.assertEqual(blocked["blocked_members"], ["agy/claude-sonnet-4-6"])
        models = [
            model
            for provider in list_providers(self.brain)
            if provider.id == "local-omniroute"
            for model in provider.models
        ]
        self.assertEqual([model.id for model in models], ["free-coding"])
        self.assertEqual(models[0].route_kind, "omniroute-combo")
        self.assertEqual(models[0].member_models, [
            "openrouter/qwen-coder:free",
            "openrouter/openrouter/free",
        ])
        allowed = next(item for item in result["combos"] if item["name"] == "free-coding")
        self.assertEqual(allowed["cost_tier"], "free")

    @patch(
        "guardian_agent.gateway.urllib.request.urlopen",
        return_value=_FakeSubscriptionComboResponse(),
    )
    def test_subscription_combos_are_capability_aware_and_opt_in(self, _urlopen) -> None:
        result = discover_omniroute_combos(self.brain)
        qwen = next(item for item in result["combos"] if item["name"] == "claude-opus")
        gpt = next(item for item in result["combos"] if item["name"] == "claude-opus-5")
        self.assertEqual(qwen["cost_tier"], "subscription")
        self.assertEqual(qwen["usage_class"], "specialist")
        self.assertEqual(gpt["usage_class"], "final-review")
        self.assertEqual(list_routes_for_task(self.brain, "coding"), [])

        configure_provider_access(self.brain, allow_subscription=True)
        routes = list_routes_for_task(self.brain, "coding")
        self.assertEqual(routes[0]["model"], "claude-opus")
        self.assertEqual(routes[0]["usage_class"], "specialist")
        self.assertEqual(routes[1]["model"], "claude-opus-5")
        self.assertEqual(routes[1]["usage_class"], "final-review")
        marked = mark_omniroute_combo_free_limited(
            self.brain,
            "claude-opus-5",
        )
        self.assertEqual(marked["cost_tier"], "free-limited")
        refreshed = discover_omniroute_combos(self.brain)
        gpt = next(
            item for item in refreshed["combos"]
            if item["name"] == "claude-opus-5"
        )
        self.assertEqual(gpt["cost_tier"], "free-limited")
        self.assertTrue(gpt["user_confirmed_free_limited"])

    @patch(
        "guardian_agent.gateway.urllib.request.urlopen",
        return_value=_FakeModelsResponse(),
    )
    def test_capacity_probe_spends_no_completion_tokens(self, _urlopen) -> None:
        setup_ollama_provider(self.brain, "qwen2.5-coder:14b")
        result = probe_provider_capacity(
            self.brain,
            "local-ollama",
            "qwen2.5-coder:14b",
        )
        self.assertTrue(result["model_advertised"])
        self.assertEqual(result["completion_tokens_spent"], 0)
        self.assertEqual(
            result["capacity"]["headers"]["x-ratelimit-remaining-requests"],
            "12",
        )


if __name__ == "__main__":
    unittest.main()
