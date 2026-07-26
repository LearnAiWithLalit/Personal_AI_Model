import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import initialize
from guardian_agent.policy import (
    approve_action_request,
    check_policy_permission,
    get_policy,
    load_approval_queue,
    request_action_approval,
)


class PolicyEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Policy Demo", "Testing Policy Engine")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_default_policy_permissions(self) -> None:
        policy = get_policy(self.brain)
        self.assertTrue(policy["policy"]["allow_local_read"])

        # Read file should be permitted
        perm = check_policy_permission(self.brain, action="read_file", target="PROJECT.md")
        self.assertEqual(perm, "permitted")

        # Payment should require explicit approval
        perm_pay = check_policy_permission(self.brain, action="submit_payment", target="https://stripe.com")
        self.assertEqual(perm_pay, "requires_approval")

    def test_request_and_approve_action(self) -> None:
        req = request_action_approval(
            self.brain,
            action="delete_file",
            target="important.db",
            reason="Database clean-up",
        )
        self.assertEqual(req["status"], "pending")

        queue = load_approval_queue(self.brain)
        self.assertEqual(len(queue), 1)

        approved = approve_action_request(self.brain, req["id"])
        self.assertEqual(approved["status"], "approved")


if __name__ == "__main__":
    unittest.main()
