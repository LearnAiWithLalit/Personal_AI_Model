import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import initialize
from guardian_agent.runtime import (
    acquire_lock,
    enqueue_task,
    get_task_status,
    kill_switch,
    list_queued_tasks,
    release_lock,
    update_task_state,
)


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "demo"
        self.brain = initialize(self.root, "Runtime Demo", "Testing durable task runtime")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_enqueue_and_update_task_state(self) -> None:
        task = enqueue_task(
            self.brain,
            task_type="coding",
            summary="Refactor auth module",
            priority="normal",
            idempotency_key="task-001",
        )
        self.assertEqual(task["state"], "queued")
        self.assertEqual(task["idempotency_key"], "task-001")

        updated = update_task_state(self.brain, task["id"], "running")
        self.assertEqual(updated["state"], "running")

        status_res = get_task_status(self.brain, task["id"])
        self.assertEqual(status_res["state"], "running")

    def test_task_locking(self) -> None:
        lock_id = acquire_lock(self.brain, "browser_session_profile")
        self.assertTrue(lock_id)
        # Attempting duplicate lock should fail
        lock2 = acquire_lock(self.brain, "browser_session_profile")
        self.assertFalse(lock2)

        release_lock(self.brain, "browser_session_profile")
        lock3 = acquire_lock(self.brain, "browser_session_profile")
        self.assertTrue(lock3)

    def test_kill_switch(self) -> None:
        enqueue_task(self.brain, task_type="coding", summary="Background job 1")
        enqueue_task(self.brain, task_type="research", summary="Background job 2")

        res = kill_switch(self.brain)
        self.assertEqual(res["status"], "emergency_stop_triggered")
        queued = list_queued_tasks(self.brain)
        self.assertTrue(all(t["state"] in {"cancelled", "stopped"} for t in queued))


if __name__ == "__main__":
    unittest.main()
