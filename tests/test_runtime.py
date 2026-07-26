import concurrent.futures
import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import initialize
from guardian_agent.runtime import (
    acquire_lock,
    enqueue_task,
    get_task_status,
    is_kill_switch_active,
    kill_switch,
    list_queued_tasks,
    release_lock,
    recover_interrupted_tasks,
    resume_after_kill_switch,
    update_task_state,
)
from guardian_agent.policy import approve_action_request, request_action_approval


def _process_enqueue_worker(root_path_str: str, worker_idx: int) -> int:
    brain = initialize(Path(root_path_str), "Runtime Demo", "Testing durable task runtime")
    for i in range(3):
        enqueue_task(
            brain,
            task_type="coding",
            summary=f"Proc Worker {worker_idx} Task {i}",
            idempotency_key=f"proc-{worker_idx}-task-{i}",
        )
    return 3


def _process_lock_worker(args: tuple[str, str]) -> bool:
    root_path_str, res_name = args
    brain = initialize(Path(root_path_str), "Runtime Demo", "Testing durable task runtime")
    return acquire_lock(brain, res_name)


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
        self.assertTrue(is_kill_switch_active(self.brain))
        request = request_action_approval(
            self.brain,
            "runtime_resume",
            "guardian-runtime",
            "Resume safe maintenance",
        )
        approve_action_request(self.brain, request["id"])
        resume_after_kill_switch(self.brain, request["id"])
        self.assertFalse(is_kill_switch_active(self.brain))

    def test_recovery_requires_review_for_side_effect_task(self) -> None:
        safe = enqueue_task(self.brain, task_type="coding", summary="Local work")
        external = enqueue_task(self.brain, task_type="browser", summary="Submit form")
        update_task_state(self.brain, safe["id"], "running")
        update_task_state(self.brain, external["id"], "running")
        tasks = list_queued_tasks(self.brain)
        next(task for task in tasks if task["id"] == external["id"])["external_side_effect"] = True
        from guardian_agent.runtime import _save_queue
        _save_queue(self.brain, tasks)
        recover_interrupted_tasks(self.brain)
        self.assertEqual(get_task_status(self.brain, safe["id"])["state"], "queued")
        self.assertEqual(get_task_status(self.brain, external["id"])["state"], "awaiting_approval")

    def test_multiprocess_concurrent_enqueue_tasks(self) -> None:
        """Test process-level concurrency with true separate OS processes."""
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(_process_enqueue_worker, str(self.root), idx)
                for idx in range(4)
            ]
            results = [f.result() for f in futures]

        self.assertEqual(sum(results), 12)
        queued = list_queued_tasks(self.brain)
        self.assertEqual(len(queued), 12)
        keys = {t["idempotency_key"] for t in queued}
        self.assertEqual(len(keys), 12)

    def test_multiprocess_concurrent_task_locking(self) -> None:
        """Test process-level lock contention across separate OS processes."""
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
            args_list = [(str(self.root), "shared_resource") for _ in range(4)]
            results = list(executor.map(_process_lock_worker, args_list))

        self.assertEqual(results.count(True), 1)

        release_lock(self.brain, "shared_resource")
        self.assertTrue(acquire_lock(self.brain, "shared_resource"))

    def test_corrupted_json_recovery(self) -> None:
        from guardian_agent.runtime import queue_file, _load_queue

        q_path = queue_file(self.brain)
        q_path.parent.mkdir(parents=True, exist_ok=True)
        q_path.write_text("{CORRUPTED_NON_JSON___", encoding="utf-8")

        tasks = _load_queue(self.brain)
        self.assertEqual(tasks, [])

        corrupted_files = list(q_path.parent.glob("queue.json.corrupted.*"))
        self.assertTrue(len(corrupted_files) >= 1)


if __name__ == "__main__":
    unittest.main()
