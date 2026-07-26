import tempfile
import unittest
import json
import os
from pathlib import Path
from unittest.mock import patch

from guardian_agent.core import GuardianError, initialize
from guardian_agent.evaluation import (
    LIVE_SCENARIOS,
    evaluation_history,
    evaluation_regression_alerts,
    run_evaluation,
)


class EvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Eval", "Evaluation tests")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_deterministic_evaluation_proves_catalog_routing_and_policy(self) -> None:
        result = run_evaluation(self.brain)
        self.assertTrue(result["passed"])
        self.assertEqual(result["schema_version"], "guardian-eval-v1")
        self.assertGreaterEqual(result["routing"]["minimum_context_savings_percent"], 90)
        self.assertTrue(Path(result["artifact"]).is_file())

    def test_live_evaluation_requires_complete_route_identity(self) -> None:
        with self.assertRaises(GuardianError):
            run_evaluation(self.brain, provider_id="local")

    @patch("guardian_agent.evaluation.complete_task_with_model")
    @patch("guardian_agent.evaluation.resolve_configured_route")
    def test_live_evaluation_scores_required_quality_terms(self, resolve, complete) -> None:
        resolve.side_effect = lambda _brain, task, provider, model: {
            "task": task,
            "provider": provider,
            "model": model,
        }
        responses = [
            "REQUIREMENTS then RISKS then VERIFICATION.",
            "Handle zero division and add a test.",
            "A token budget prevents overuse.",
        ]
        complete.side_effect = [
            {
                "provider": "local",
                "model": "model",
                "response": response,
                "usage": {"total_tokens": 5},
            }
            for response in responses
        ]
        result = run_evaluation(
            self.brain,
            provider_id="local",
            model_id="model",
        )
        self.assertEqual(len(result["live_quality"]["scenarios"]), len(LIVE_SCENARIOS))
        self.assertTrue(result["live_quality"]["passed"])
        self.assertEqual(result["live_quality"]["quality_score_percent"], 100.0)
        self.assertTrue(result["passed"])
        history = evaluation_history(self.brain)
        self.assertEqual(history["model_count"], 1)
        self.assertEqual(history["models"][0]["scenario_count"], 3)
        self.assertEqual(history["models"][0]["average_quality_score_percent"], 100.0)
        from guardian_agent.provider_capacity import provider_quality_adjustment
        self.assertEqual(
            provider_quality_adjustment(self.brain, "local", "model"),
            -5,
        )

    def test_regression_alert_detects_quality_drop_and_token_growth(self) -> None:
        directory = self.brain.directory / "audit" / "evaluations"
        directory.mkdir(parents=True, exist_ok=True)
        for index, (score, passed, tokens) in enumerate((
            (100.0, True, 100),
            (60.0, False, 200),
        )):
            artifact = directory / f"guardian-eval-v1-manual-{index}.json"
            artifact.write_text(json.dumps({
                "created_at": f"run-{index}",
                "live_quality": {
                    "executed": True,
                    "passed": passed,
                    "quality_score_percent": score,
                    "scenarios": [{
                        "provider": "local",
                        "model": "model",
                        "required_terms": ["a"],
                        "missing_terms": [] if passed else ["a"],
                        "passed": passed,
                        "usage": {"total_tokens": tokens, "cost_usd": 0},
                    }],
                },
            }), encoding="utf-8")
            os.utime(artifact, (1000 + index, 1000 + index))
        report = evaluation_regression_alerts(self.brain)
        self.assertFalse(report["passed"])
        self.assertEqual(report["alert_count"], 1)
        self.assertEqual(
            set(report["alerts"][0]["reasons"]),
            {"pass-to-fail", "quality-drop", "token-increase"},
        )


if __name__ == "__main__":
    unittest.main()
