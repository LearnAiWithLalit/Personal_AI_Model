import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import GuardianError, initialize
from guardian_agent.policy import approve_action_request, request_action_approval
from guardian_agent.workflow import (
    advance_workflow,
    assess_profile,
    record_workflow_review,
    start_workflow,
    verify_workflow,
)


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Workflow Demo", "Lifecycle test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _approval(self, action: str, target: str) -> str:
        request = request_action_approval(self.brain, action, target, "Test approval")
        approve_action_request(self.brain, request["id"])
        return request["id"]

    def test_adaptive_profiles(self) -> None:
        self.assertEqual(assess_profile("Correct README typo")["profile"], "fast")
        self.assertEqual(assess_profile("Deploy payment authentication migration")["profile"], "high_assurance")
        self.assertEqual(assess_profile("Add reporting dashboard")["profile"], "standard")

    def test_fast_workflow_requires_fresh_verification(self) -> None:
        record = start_workflow(self.brain, "Correct README typo", "low")
        record = advance_workflow(self.brain, record["id"], "Edited only README.md")
        self.assertEqual(record["current_stage"], "verification")
        with self.assertRaises(GuardianError):
            advance_workflow(self.brain, record["id"], "Tests passed earlier")
        record = verify_workflow(self.brain, record["id"], "python3 -c 'print(\"verified\")'")
        self.assertEqual(record["status"], "completed")

    def test_standard_workflow_enforces_design_and_two_reviews(self) -> None:
        record = start_workflow(self.brain, "Add reporting dashboard", "medium")
        with self.assertRaises(GuardianError):
            advance_workflow(self.brain, record["id"], "Design looks fine")
        approval = self._approval("workflow_design_approval", record["id"])
        record = advance_workflow(self.brain, record["id"], "User approved design", approval)
        record = advance_workflow(self.brain, record["id"], "Plan saved with tests and rollback")
        record = advance_workflow(self.brain, record["id"], "Implementation complete in worktree")
        self.assertEqual(record["current_stage"], "specification_review")
        record = record_workflow_review(self.brain, record["id"], "specification", True, [])
        self.assertEqual(record["current_stage"], "quality_review")
        record = record_workflow_review(self.brain, record["id"], "quality", True, [])
        self.assertEqual(record["current_stage"], "verification")

    def test_high_assurance_requires_final_approval(self) -> None:
        record = start_workflow(self.brain, "Deploy authentication migration", "auto")
        design = self._approval("workflow_design_approval", record["id"])
        record = advance_workflow(self.brain, record["id"], "Approved design", design)
        record = advance_workflow(self.brain, record["id"], "Plan approved")
        record = advance_workflow(self.brain, record["id"], "Implemented")
        record = record_workflow_review(self.brain, record["id"], "specification", True, [])
        record = record_workflow_review(self.brain, record["id"], "quality", True, [])
        record = verify_workflow(self.brain, record["id"], "python3 -c 'print(\"verified\")'")
        self.assertEqual(record["current_stage"], "final_approval")
        with self.assertRaises(GuardianError):
            advance_workflow(self.brain, record["id"], "Ready")
        final = self._approval("workflow_final_approval", record["id"])
        record = advance_workflow(self.brain, record["id"], "Final user approval", final)
        self.assertEqual(record["status"], "completed")


if __name__ == "__main__":
    unittest.main()
