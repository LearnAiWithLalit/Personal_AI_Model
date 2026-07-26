import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import (
    DOCUMENTS,
    confirm,
    initialize,
    intake,
    record_decision,
    record_lesson,
    render_context,
    require_brain,
    status,
)


class ProjectBrainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Demo", "Verify project memory")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_init_creates_documents_and_directories(self) -> None:
        for name in DOCUMENTS:
            self.assertTrue(self.brain.document(name).is_file())
        self.assertTrue((self.root / ".agent" / "research").is_dir())
        self.assertEqual(require_brain(self.root), self.brain)

    def test_confirmed_requirement_is_available_to_context(self) -> None:
        intake(self.brain, "Build a local dashboard")
        confirm(self.brain, "Build a local dashboard with a project status page")
        record_decision(self.brain, "Dependencies", "Use standard library for the first slice.")
        record_lesson(self.brain, "Scope", "Confirm requirements before implementation.")

        context = render_context(self.brain)

        self.assertIn("Build a local dashboard with a project status page", context)
        self.assertIn("Use standard library for the first slice", context)
        self.assertIn("Confirm requirements before implementation", context)
        self.assertTrue(self.brain.document("CONTEXT.md").read_text(encoding="utf-8").startswith("# Guardian Handoff Context"))

    def test_status_reports_project_progress(self) -> None:
        intake(self.brain, "Add project memory")
        confirm(self.brain, "Add durable project memory")
        result = status(self.brain)
        self.assertEqual(result["confirmed_requirements"], 1)
        self.assertIsNone(result["pending_requirement"])
        self.assertGreaterEqual(result["journey_entries"], 3)

    def test_new_intake_preserves_prior_confirmed_requirements(self) -> None:
        intake(self.brain, "First request")
        confirm(self.brain, "First confirmed request")
        intake(self.brain, "Second request")

        requirements = self.brain.document("REQUIREMENTS.md").read_text(encoding="utf-8")

        self.assertIn("First confirmed request", requirements)
        self.assertIn("Second request", requirements)


if __name__ == "__main__":
    unittest.main()
