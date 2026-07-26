import json
import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import GuardianError, initialize, record_lesson, render_context
from guardian_agent.learning import (
    apply_reusable_lessons,
    delete_reusable_lesson,
    list_lesson_candidates,
    promote_reusable_lesson,
    search_reusable_lessons,
)
from guardian_agent.policy import approve_action_request, request_action_approval


class ReusableLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.brain = initialize(root / "project-one", "Private Project", "Learning")
        self.library = root / "user-library" / "learning.json"
        record_lesson(
            self.brain,
            "Authentication fixture failure",
            "PrivateClient test failed because its token used a fixed expired timestamp.",
        )
        self.candidate = list_lesson_candidates(self.brain)[0]

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _approval(self, action: str, target: str) -> str:
        request = request_action_approval(
            self.brain,
            action,
            target,
            "Reviewed sanitized reusable learning.",
        )
        approve_action_request(self.brain, request["id"])
        return request["id"]

    def test_promotion_requires_exact_approval_and_exports_only_sanitized_fields(self) -> None:
        with self.assertRaisesRegex(GuardianError, "not found"):
            promote_reusable_lesson(
                self.brain,
                self.candidate["id"],
                pattern="Time-sensitive authentication fixtures can expire.",
                prevention="Generate fixture timestamps relative to the controlled test clock.",
                tags=["authentication", "testing"],
                approval_id="req-missing",
                library_path=self.library,
            )
        approval = self._approval("learning_export", self.candidate["id"])
        exported = promote_reusable_lesson(
            self.brain,
            self.candidate["id"],
            pattern="Time-sensitive authentication fixtures can expire.",
            prevention="Generate fixture timestamps relative to the controlled test clock.",
            tags=["authentication", "testing"],
            approval_id=approval,
            library_path=self.library,
        )
        self.assertTrue(exported["id"].startswith("shared-"))
        payload_text = self.library.read_text(encoding="utf-8")
        self.assertNotIn("PrivateClient", payload_text)
        self.assertNotIn(str(self.brain.root), payload_text)
        self.assertEqual(self.library.stat().st_mode & 0o777, 0o600)

    def test_sensitive_export_is_rejected_before_approval_is_consumed(self) -> None:
        approval = self._approval("learning_export", self.candidate["id"])
        with self.assertRaisesRegex(GuardianError, "private or secret"):
            promote_reusable_lesson(
                self.brain,
                self.candidate["id"],
                pattern="Use API key: abcdef0123456789abcdef0123456789.",
                prevention="Rotate it.",
                tags=["security"],
                approval_id=approval,
                library_path=self.library,
            )
        exported = promote_reusable_lesson(
            self.brain,
            self.candidate["id"],
            pattern="Long-lived credentials can leak through test fixtures.",
            prevention="Use short-lived synthetic credentials and scan fixtures.",
            tags=["security"],
            approval_id=approval,
            library_path=self.library,
        )
        self.assertTrue(exported["id"].startswith("shared-"))

    def test_search_apply_context_and_approved_delete(self) -> None:
        approval = self._approval("learning_export", self.candidate["id"])
        exported = promote_reusable_lesson(
            self.brain,
            self.candidate["id"],
            pattern="Authentication fixtures should follow the controlled test clock.",
            prevention="Generate token timestamps relative to the test clock.",
            tags=["authentication", "testing"],
            approval_id=approval,
            library_path=self.library,
        )
        found = search_reusable_lessons(
            "authentication test token",
            library_path=self.library,
        )
        self.assertEqual(found["count"], 1)
        applied = apply_reusable_lessons(
            self.brain,
            "authentication test token",
            library_path=self.library,
        )
        self.assertEqual(applied["count"], 1)
        self.assertIn(exported["id"], render_context(self.brain))

        delete_approval = self._approval("learning_delete", exported["id"])
        deleted = delete_reusable_lesson(
            self.brain,
            exported["id"],
            delete_approval,
            library_path=self.library,
        )
        self.assertTrue(deleted["deleted"])
        payload = json.loads(self.library.read_text(encoding="utf-8"))
        self.assertEqual(payload["lessons"], [])


if __name__ == "__main__":
    unittest.main()
