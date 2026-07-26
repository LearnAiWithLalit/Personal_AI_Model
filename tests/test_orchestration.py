"""Unit tests for Unified Orchestration Control Plane."""

import json
import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import GuardianError, initialize
from guardian_agent.gateway import default_gateway
from guardian_agent.orchestration import (
    orchestrate_confirm,
    orchestrate_dispatch,
    orchestrate_list,
    orchestrate_recover,
    orchestrate_show,
    orchestrate_start,
)


class OrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(
            Path(self.tempdir.name) / "demo",
            "Orchestration Demo",
            "Unified orchestration control plane tests",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_start_creates_draft_without_model_call(self) -> None:
        """Starting an orchestration creates a draft with no model calls."""
        result = orchestrate_start(self.brain, "Implement a login form", limit=3, approved_paths=["src/", "tests/"])
        self.assertEqual(result["status"], "draft")
        self.assertTrue(result["orchestration_id"].startswith("orch-"))
        self.assertIn("preview_text", result)
        self.assertIn("preview", result)
        preview = result["preview"]
        self.assertEqual(preview["risk"]["profile"], "standard")

        self.assertEqual(preview["task_type"], "coding")
        self.assertGreaterEqual(len(preview["selected_profiles"]), 1)
        self.assertLessEqual(len(preview["selected_profiles"]), 3)
        self.assertIn("prohibited_models", preview)
        self.assertIn("claude-sonnet-4.6", preview["prohibited_models"])
        self.assertIn("context_savings", preview)
        self.assertGreater(preview["context_savings"].get("estimated_savings_percent", 0), 0)

    def test_start_rejects_empty_task(self) -> None:
        with self.assertRaises(GuardianError):
            orchestrate_start(self.brain, "")

    def test_start_rejects_excessive_limit(self) -> None:
        with self.assertRaises(GuardianError):
            orchestrate_start(self.brain, "Write unit tests", limit=10)

    def test_start_preserves_prohibited_models(self) -> None:
        """Verify claude-sonnet-4.6 transitive blocking is preserved."""
        result = orchestrate_start(self.brain, "Review authentication", limit=2)
        preview = result["preview"]
        self.assertIn("claude-sonnet-4.6", preview["prohibited_models"])

    def test_classify_coding_task(self) -> None:
        result = orchestrate_start(self.brain, "Build a new API endpoint", limit=2, approved_paths=["src/", "tests/"])
        self.assertEqual(result["preview"]["task_type"], "coding")

    def test_classify_research_task(self) -> None:
        result = orchestrate_start(self.brain, "Research authentication best practices", limit=2)
        self.assertEqual(result["preview"]["task_type"], "research")

    def test_classify_documentation_task(self) -> None:
        result = orchestrate_start(self.brain, "Write documentation for the API", limit=2)
        self.assertEqual(result["preview"]["task_type"], "documentation")

    def test_classify_planning_task(self) -> None:
        result = orchestrate_start(self.brain, "Design the database schema", limit=2)
        self.assertEqual(result["preview"]["task_type"], "planning")

    def test_confirm_changes_status_and_starts_workflow(self) -> None:
        """Confirming a draft changes its status and starts a workflow."""
        start_result = orchestrate_start(self.brain, "Add error logging to the service", limit=2, approved_paths=["src/", "tests/"])
        orch_id = start_result["orchestration_id"]

        confirm_result = orchestrate_confirm(
            self.brain, orch_id, "Add structured error logging with context enrichment"
        )
        self.assertEqual(confirm_result["status"], "confirmed")
        self.assertIsNotNone(confirm_result["workflow_id"])
        self.assertTrue(confirm_result["workflow_id"].startswith("wf-"))
        self.assertEqual(
            confirm_result["requirement_summary"],
            "Add structured error logging with context enrichment",
        )

        show_result = orchestrate_show(self.brain, orch_id)
        self.assertEqual(show_result["status"], "confirmed")
        self.assertEqual(show_result["workflow_id"], confirm_result["workflow_id"])

    def test_confirm_rejects_already_confirmed(self) -> None:
        start_result = orchestrate_start(self.brain, "Fix a bug", limit=2, approved_paths=["src/", "tests/"])
        orch_id = start_result["orchestration_id"]
        orchestrate_confirm(self.brain, orch_id, "Fix the null pointer bug")

        with self.assertRaises(GuardianError):
            orchestrate_confirm(self.brain, orch_id, "Fix the bug again")

    def test_confirm_rejects_nonexistent(self) -> None:
        with self.assertRaises(GuardianError):
            orchestrate_confirm(self.brain, "orch-nonexistent-id", "Test")

    def test_confirm_uses_exact_request_when_multiple_drafts_exist(self) -> None:
        first = orchestrate_start(self.brain, "Implement the billing API", limit=2, approved_paths=["src/", "tests/"])
        second = orchestrate_start(self.brain, "Write the public README", limit=2)

        orchestrate_confirm(
            self.brain,
            first["orchestration_id"],
            "Implement the approved billing API scope",
        )

        requirements = self.brain.document("REQUIREMENTS.md").read_text(encoding="utf-8")
        self.assertIn(
            f"- **Reference ID:** {first['orchestration_id']}",
            requirements,
        )
        self.assertIn("- **Original request:** Implement the billing API", requirements)
        self.assertNotIn(
            f"- **Reference ID:** {second['orchestration_id']}",
            requirements,
        )

    def test_dispatch_writes_compact_handoff(self) -> None:
        """Dispatching a confirmed orchestration writes a compact handoff file."""
        start_result = orchestrate_start(self.brain, "Build a responsive navbar", limit=3, approved_paths=["src/", "tests/"])
        orch_id = start_result["orchestration_id"]
        orchestrate_confirm(self.brain, orch_id, "Build responsive navigation bar component")

        dispatch_result = orchestrate_dispatch(self.brain, orch_id)
        self.assertEqual(dispatch_result["status"], "dispatched")
        self.assertTrue(dispatch_result["handoff_exists"])
        handoff_path = Path(dispatch_result["handoff_path"])
        self.assertTrue(handoff_path.is_file())

        handoff_text = handoff_path.read_text(encoding="utf-8")
        self.assertIn("# Orchestration Handoff for", handoff_text)
        self.assertIn("Build a responsive navbar", handoff_text)
        self.assertIn("## Selected Specialist Profiles", handoff_text)
        self.assertIn("## Route Preview", handoff_text)
        self.assertIn("claude-sonnet-4.6", handoff_text)

    def test_dispatch_is_idempotent(self) -> None:
        """Calling dispatch again on an already-dispatch returns existing handoff."""
        start_result = orchestrate_start(self.brain, "Add unit tests", limit=2, approved_paths=["src/", "tests/"])
        orch_id = start_result["orchestration_id"]
        orchestrate_confirm(self.brain, orch_id, "Add unit tests for the parser")

        first = orchestrate_dispatch(self.brain, orch_id)
        second = orchestrate_dispatch(self.brain, orch_id)

        self.assertEqual(second["status"], "dispatched")
        self.assertEqual(second["handoff_path"], first["handoff_path"])
        self.assertIn("already dispatched", second.get("note", ""))

    def test_dispatch_rejects_draft(self) -> None:
        start_result = orchestrate_start(self.brain, "Refactor the config module", limit=2, approved_paths=["src/", "tests/"])
        orch_id = start_result["orchestration_id"]

        with self.assertRaises(GuardianError):
            orchestrate_dispatch(self.brain, orch_id)

    def test_list_returns_all_orchestrations(self) -> None:
        """List returns all orchestration records created."""
        orch_ids = []
        for task in ["Fix typo in README", "Add rate limiting", "Write API docs"]:
            paths = ["src/", "tests/"] if "Fix" in task or "Add" in task else []
            result = orchestrate_start(self.brain, task, limit=2, approved_paths=paths)
            orch_ids.append(result["orchestration_id"])

        results = orchestrate_list(self.brain)
        self.assertGreaterEqual(len(results), 3)
        returned_ids = [r["id"] for r in results]
        for orch_id in orch_ids:
            self.assertIn(orch_id, returned_ids)

    def test_recover_returns_idempotent_state(self) -> None:
        """Recover returns current state without side effects."""
        start_result = orchestrate_start(self.brain, "Add caching layer", limit=2, approved_paths=["src/", "tests/"])
        orch_id = start_result["orchestration_id"]

        draft_recovery = orchestrate_recover(self.brain, orch_id)
        self.assertEqual(draft_recovery["status"], "draft")
        self.assertIsNone(draft_recovery.get("workflow_id"))
        self.assertIn("draft", draft_recovery.get("recovery_action", ""))

        orchestrate_confirm(self.brain, orch_id, "Add Redis caching layer")
        confirmed_recovery = orchestrate_recover(self.brain, orch_id)
        self.assertEqual(confirmed_recovery["status"], "confirmed")
        self.assertIsNotNone(confirmed_recovery.get("workflow_id"))
        self.assertIn("confirmed", confirmed_recovery.get("recovery_action", ""))

        orchestrate_dispatch(self.brain, orch_id)
        dispatched_recovery = orchestrate_recover(self.brain, orch_id)
        self.assertEqual(dispatched_recovery["status"], "dispatched")
        self.assertIsNotNone(dispatched_recovery.get("handoff_path"))

    def test_show_returns_full_record(self) -> None:
        start_result = orchestrate_start(self.brain, "Implement search feature", limit=3, approved_paths=["src/", "tests/"])
        orch_id = start_result["orchestration_id"]

        record = orchestrate_show(self.brain, orch_id)
        self.assertEqual(record["id"], orch_id)
        self.assertEqual(record["status"], "draft")
        self.assertEqual(record["task"], "Implement search feature")
        self.assertIn("preview", record)
        self.assertIn("selected_profiles", record["preview"])
        self.assertIn("routes", record["preview"])

    def test_preserves_private_memory_boundaries(self) -> None:
        """Verify that orchestration does not expose sensitive data."""
        start_result = orchestrate_start(
            self.brain, "Review the authentication implementation", limit=2
        )
        orch_id = start_result["orchestration_id"]
        orchestrate_confirm(
            self.brain, orch_id, "Review authentication implementation"
        )
        dispatch_result = orchestrate_dispatch(self.brain, orch_id)

        handoff_path = Path(dispatch_result["handoff_path"])
        handoff_text = handoff_path.read_text(encoding="utf-8")

        self.assertNotIn("sk-", handoff_text)
        self.assertNotIn("api_key", handoff_text)
        self.assertNotIn("password", handoff_text)
        self.assertNotIn("OMNIROUTE_API_KEY", handoff_text)
        self.assertNotIn("OPENAI_API_KEY", handoff_text)

    def test_handoff_contains_verified_context_savings(self) -> None:
        """Handoff includes estimated context savings."""
        start_result = orchestrate_start(
            self.brain, "Build a user dashboard with React", limit=2, approved_paths=["src/", "tests/"]
        )
        orch_id = start_result["orchestration_id"]
        preview = start_result["preview"]
        self.assertGreater(preview["context_savings"]["estimated_savings_percent"], 0)
        self.assertGreater(preview["context_savings"]["full_catalog_estimated_tokens"], 0)

        orchestrate_confirm(self.brain, orch_id, "Build user dashboard")
        dispatch_result = orchestrate_dispatch(self.brain, orch_id)

        handoff_text = Path(dispatch_result["handoff_path"]).read_text(encoding="utf-8")
        self.assertIn("Context Savings", handoff_text)
        self.assertIn("%", handoff_text)

    def test_route_preview_caps_routes_and_reserves_final_review_last(self) -> None:
        gateway = self.brain.directory / "model-gateway.json"
        payload = default_gateway()
        payload["providers"] = [
            {
                "id": "local-test",
                "kind": "ollama",
                "base_url": "http://localhost:11434",
                "credential_env": None,
                "enabled": True,
                "models": [
                    {
                        "id": "local-model",
                        "capabilities": ["coding"],
                        "cost_tier": "local",
                        "priority": 1,
                    }
                ],
            },
            {
                "id": "local-omniroute",
                "kind": "omniroute",
                "base_url": "http://localhost:3000",
                "credential_env": None,
                "enabled": True,
                "models": [
                    {
                        "id": f"free-combo-{index}",
                        "capabilities": ["coding"],
                        "cost_tier": "free-limited",
                        "priority": 10 + index,
                    }
                    for index in range(6)
                ]
                + [
                    {
                        "id": "claude-opus-5",
                        "capabilities": ["coding"],
                        "cost_tier": "free-limited",
                        "priority": 40,
                        "usage_class": "final-review",
                        "member_models": ["cgpt-web/gpt-5.5"],
                    }
                ],
            },
        ]
        gateway.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        result = orchestrate_start(self.brain, "Implement an API", limit=2, approved_paths=["src/", "tests/"])
        routes = result["preview"]["routes"]
        self.assertEqual(len(routes), 5)
        self.assertEqual(routes[0]["provider"], "local-test")
        self.assertEqual(routes[-1]["model"], "claude-opus-5")


if __name__ == "__main__":
    unittest.main()
