import tempfile
import unittest
import subprocess
from pathlib import Path

from guardian_agent.core import initialize
from guardian_agent.sandbox import (
    create_worktree_sandbox,
    generate_diff_preview,
    rollback_sandbox,
)


class SandboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Sandbox Demo", "Testing Git Worktree Sandbox")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_create_and_rollback_sandbox(self) -> None:
        sb = create_worktree_sandbox(self.brain, branch_name="feature-auth")
        self.assertTrue(Path(sb["worktree_path"]).is_dir())
        self.assertIn("feature-auth", sb["branch"])

        diff = generate_diff_preview(self.brain, sb["worktree_path"])
        self.assertIn("diff", diff)

        rb = rollback_sandbox(self.brain, sb["worktree_path"])
        self.assertEqual(rb["status"], "rolled_back")
        self.assertFalse(Path(sb["worktree_path"]).exists())

    def test_git_repository_uses_real_worktree(self) -> None:
        subprocess.run(["git", "-C", str(self.root), "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Guardian Test"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "guardian@example.invalid"], check=True)
        (self.root / "tracked.txt").write_text("baseline\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-m", "baseline"], check=True, capture_output=True)
        sandbox = create_worktree_sandbox(self.brain, "feature-real-worktree")
        self.assertEqual(sandbox["mode"], "git-worktree")
        self.assertTrue((Path(sandbox["worktree_path"]) / ".git").exists())
        rollback_sandbox(self.brain, sandbox["worktree_path"])


if __name__ == "__main__":
    unittest.main()
