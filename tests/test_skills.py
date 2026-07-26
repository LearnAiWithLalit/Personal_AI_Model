import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import initialize
from guardian_agent.skills import (
    create_skill_draft,
    inject_relevant_lessons,
    list_skills,
    promote_skill,
    validate_skill,
)


class SkillFactoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "Demo", "Skill factory test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_skill_lifecycle_draft_validate_promote(self) -> None:
        skill = create_skill_draft(
            self.brain,
            name="test-driven-dev",
            description="Run unit tests before confirming changes",
            instructions="Always write unit tests first.",
        )
        self.assertTrue(skill["path"].endswith("SKILL.md"))
        self.assertEqual(skill["status"], "draft")

        skills = list_skills(self.brain)
        self.assertEqual(len(skills["drafts"]), 1)

        val_result = validate_skill(self.brain, "test-driven-dev")
        self.assertTrue(val_result["valid"])

        promoted = promote_skill(self.brain, "test-driven-dev")
        self.assertEqual(promoted["status"], "trusted")

        skills_after = list_skills(self.brain)
        self.assertEqual(len(skills_after["trusted"]), 1)
        self.assertEqual(len(skills_after["drafts"]), 0)

    def test_inject_relevant_lessons(self) -> None:
        lesson = inject_relevant_lessons(self.brain, "Scope and requirements verification")
        self.assertIsInstance(lesson, str)


if __name__ == "__main__":
    unittest.main()
