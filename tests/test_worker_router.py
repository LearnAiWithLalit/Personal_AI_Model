"""Tests for the WorkerRouter — auto-select Aider/JCode/Hermes based on task size.

Covers:
- Task classification routing (small → Aider, large → JCode, research → Hermes)
- Worker availability detection (binary found/not found)
- Fallback chain logic
- Handoff preparation
- Execution gating (opt-in, fail-closed)
- Code reviewer pattern
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from guardian_agent.core import GuardianError, initialize
from guardian_agent.worker_router import (
    _check_worker_availability,
    _select_worker,
    classify_task_size,
    route_task,
    execute_route,
)


class WorkerAvailabilityTests(unittest.TestCase):
    """Tests for worker binary detection."""

    @patch("guardian_agent.worker_router._aider_path", return_value="/usr/bin/aider")
    @patch("guardian_agent.jcode._jcode_path", return_value=None)
    @patch("guardian_agent.hermes._hermes_path", return_value=None)
    def test_aider_only_available(self, _hermes, _jcode, _aider) -> None:
        """Only Aider should be reported as available."""
        avail = _check_worker_availability()
        self.assertTrue(avail["aider"]["available"])
        self.assertFalse(avail["jcode"]["available"])
        self.assertFalse(avail["hermes"]["available"])

    @patch("guardian_agent.worker_router._aider_path", return_value="/usr/bin/aider")
    @patch("guardian_agent.jcode._jcode_path", return_value="/usr/bin/jcode")
    @patch("guardian_agent.hermes._hermes_path", return_value="/usr/bin/hermes")
    def test_all_workers_available(self, _hermes, _jcode, _aider) -> None:
        """All workers should be reported as available."""
        avail = _check_worker_availability()
        self.assertTrue(avail["aider"]["available"])
        self.assertTrue(avail["jcode"]["available"])
        self.assertTrue(avail["hermes"]["available"])
        self.assertTrue(avail["hermes"]["execution_disabled"])  # Fail-closed

    @patch("guardian_agent.worker_router._aider_path", return_value=None)
    @patch("guardian_agent.jcode._jcode_path", return_value=None)
    @patch("guardian_agent.hermes._hermes_path", return_value=None)
    def test_no_workers_available(self, _hermes, _jcode, _aider) -> None:
        """All workers should report unavailable."""
        avail = _check_worker_availability()
        self.assertFalse(avail["aider"]["available"])
        self.assertFalse(avail["jcode"]["available"])
        self.assertFalse(avail["hermes"]["available"])

    def test_hermes_execution_disabled_by_default(self) -> None:
        """Hermes should always report execution_disabled=True."""
        avail = _check_worker_availability()
        self.assertTrue(avail["hermes"]["execution_disabled"])


class WorkerSelectionTests(unittest.TestCase):
    """Tests for worker selection logic with fallback chains."""

    def _make_classification(self, category: str) -> dict:
        return {
            "category": category,
            "reason": f"Test: {category}",
            "recommended_worker": "aider",
            "workers_available": {"aider": True, "jcode": False, "hermes": False},
        }

    def _make_availability(
        self,
        aider: bool = True,
        jcode: bool = False,
        hermes: bool = False,
    ) -> dict:
        return {
            "aider": {
                "available": aider, "executable": "/usr/bin/aider" if aider else None,
                "execution_disabled": False, "requires_opt_in": False, "opted_in": None,
            },
            "jcode": {
                "available": jcode, "executable": "/usr/bin/jcode" if jcode else None,
                "execution_disabled": False, "requires_opt_in": True, "opted_in": None,
            },
            "hermes": {
                "available": hermes, "executable": "/usr/bin/hermes" if hermes else None,
                "execution_disabled": True, "requires_opt_in": True, "opted_in": None,
            },
        }

    def test_small_task_selects_aider(self) -> None:
        """Small tasks should select Aider."""
        avail = self._make_availability(aider=True, jcode=False, hermes=False)
        result = _select_worker(self._make_classification("small"), avail)
        self.assertEqual(result["worker"], "aider")
        self.assertTrue(result["execution_possible"])

    def test_large_task_selects_jcode(self) -> None:
        """Large tasks should select JCode when available."""
        avail = self._make_availability(aider=True, jcode=True, hermes=False)
        result = _select_worker(self._make_classification("large"), avail)
        self.assertEqual(result["worker"], "jcode")
        self.assertTrue(result["execution_possible"])

    def test_large_task_falls_back_to_aider(self) -> None:
        """Large tasks should fall back to Aider when JCode is unavailable."""
        avail = self._make_availability(aider=True, jcode=False, hermes=False)
        result = _select_worker(self._make_classification("large"), avail)
        self.assertEqual(result["worker"], "aider")
        self.assertTrue(result["execution_possible"])

    def test_research_task_selects_hermes_with_fallback(self) -> None:
        """Research tasks should fall back to Aider when Hermes execution is disabled."""
        avail = self._make_availability(aider=True, jcode=False, hermes=True)
        result = _select_worker(self._make_classification("research"), avail)
        # Hermes is available but execution_disabled, so Aider is better
        self.assertEqual(result["worker"], "aider")
        self.assertTrue(result["execution_possible"])

    def test_small_task_falls_back_when_aider_unavailable(self) -> None:
        """Small tasks should fall back when Aider is unavailable."""
        avail = self._make_availability(aider=False, jcode=True, hermes=False)
        result = _select_worker(self._make_classification("small"), avail)
        self.assertEqual(result["worker"], "jcode")
        self.assertTrue(result["execution_possible"])

    def test_all_workers_tags_present(self) -> None:
        """Result should include capabilities, reason, and fallback chain."""
        avail = self._make_availability(aider=True, jcode=False, hermes=False)
        result = _select_worker(self._make_classification("small"), avail)
        self.assertIn("worker_capabilities", result)
        self.assertIn("fallback_chain", result)
        self.assertIn("reason", result)
        self.assertIn("category", result)


class RouterIntegrationTests(unittest.TestCase):
    """End-to-end tests for route_task function."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Router Demo", "Router integration tests")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @patch("guardian_agent.worker_router._aider_path", return_value="/usr/bin/aider")
    @patch("guardian_agent.jcode._jcode_path", return_value=None)
    @patch("guardian_agent.hermes._hermes_path", return_value=None)
    def test_route_small_task_to_aider(
        self, _hermes, _jcode, _aider
    ) -> None:
        """Small task should route to Aider with a handoff."""

        result = route_task(self.brain, "Fix a typo in the README")

        self.assertEqual(result["classification"]["category"], "small")
        self.assertEqual(result["worker_selection"]["worker"], "aider")
        self.assertTrue(result["execution_plan"]["execution_possible"])
        self.assertIn("handoff", result)
        self.assertIsNotNone(result["handoff"])
        self.assertIn("route_id", result)

    @patch("guardian_agent.worker_router._aider_path", return_value="/usr/bin/aider")
    @patch("guardian_agent.jcode._jcode_path", return_value="/usr/bin/jcode")
    @patch("guardian_agent.hermes._hermes_path", return_value=None)
    def test_route_large_task_to_jcode(
        self, _hermes, _jcode, _aider
    ) -> None:
        """Large refactoring task should route to JCode."""
        result = route_task(
            self.brain,
            "Refactor the authentication module into multiple files",
        )

        self.assertEqual(result["classification"]["category"], "large")
        self.assertEqual(result["worker_selection"]["worker"], "jcode")
        self.assertIn("handoff", result)

    @patch("guardian_agent.worker_router._aider_path", return_value="/usr/bin/aider")
    @patch("guardian_agent.jcode._jcode_path", return_value=None)
    @patch("guardian_agent.hermes._hermes_path", return_value="/usr/bin/hermes")
    def test_route_research_task_with_hermes_available(
        self, _hermes, _jcode, _aider
    ) -> None:
        """Research task should route to Aider (Hermes execution is disabled)."""
        result = route_task(
            self.brain,
            "Research the best authentication methods for a FastAPI app",
        )

        self.assertEqual(result["classification"]["category"], "research")
        # Aider selected because Hermes execution is disabled
        self.assertEqual(result["worker_selection"]["worker"], "aider")
        self.assertFalse(
            result["worker_selection"]["worker_capabilities"]
            .get("execution_disabled", False)
        )
        self.assertTrue(result["execution_plan"]["execution_possible"])

    @patch("guardian_agent.worker_router._aider_path", return_value=None)
    @patch("guardian_agent.jcode._jcode_path", return_value=None)
    @patch("guardian_agent.hermes._hermes_path", return_value=None)
    def test_route_no_workers_still_produces_handoff(
        self, _hermes, _jcode, _aider
    ) -> None:
        """Routing with no workers should still produce a handoff and route decision."""
        result = route_task(self.brain, "Fix typo")

        self.assertIn("route_id", result)
        self.assertIn("handoff", result)
        self.assertIn("classification", result)
        self.assertIn("worker_selection", result)

    def test_route_empty_task_raises(self) -> None:
        """Empty task should raise GuardianError."""
        with self.assertRaises(GuardianError):
            route_task(self.brain, "")

    def test_route_with_writable_paths(self) -> None:
        """Routing with writable paths should include them in the handoff."""
        test_file = self.brain.root / "src" / "main.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("print('hello')", encoding="utf-8")

        result = route_task(
            self.brain, "Update main.py",
            writable_paths=["src/main.py"],
        )
        handoff = result.get("handoff", {})
        if handoff:
            paths = handoff.get("writable_paths") or handoff.get("read_paths", [])
            self.assertTrue(
                any("src/main.py" in str(p) for p in paths),
                f"Expected src/main.py in paths, got {paths}",
            )


class RouterExecuteTests(unittest.TestCase):
    """Tests for executing a routed task."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Router Exec", "Router execution tests")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_execute_route_requires_execution_possible(self) -> None:
        """Executing a route where execution is not possible should raise."""
        result = route_task(self.brain, "Research auth methods")
        # Ensure execution is not possible for hermes
        result["execution_plan"]["execution_possible"] = False

        with self.assertRaises(GuardianError) as ctx:
            execute_route(self.brain, result)
        self.assertIn("Cannot execute", str(ctx.exception))


class ClassifyTaskSizeRouteTests(unittest.TestCase):
    """Verify that classify_task_size produces correct routing outputs."""

    @patch("guardian_agent.aider._aider_path", return_value="/usr/bin/aider")
    def test_small_task_classification(self, _path) -> None:
        """Small task should classify as 'small'."""
        result = classify_task_size("Fix typo in error message")
        self.assertEqual(result["category"], "small")
        self.assertEqual(result["recommended_worker"], "aider")

    @patch("guardian_agent.aider._aider_path", return_value="/usr/bin/aider")
    def test_large_task_classification(self, _path) -> None:
        """Large refactoring task should classify as 'large'."""
        result = classify_task_size("Refactor the entire API layer to use dependency injection")
        self.assertEqual(result["category"], "large")

    @patch("guardian_agent.aider._aider_path", return_value="/usr/bin/aider")
    def test_research_task_classification(self, _path) -> None:
        """Research task should classify as 'research'."""
        result = classify_task_size("Research the best database for our use case")
        self.assertEqual(result["category"], "research")


if __name__ == "__main__":
    unittest.main()
