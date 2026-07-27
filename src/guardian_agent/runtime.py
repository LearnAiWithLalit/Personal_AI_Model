"""Durable Task Runtime, Job Queue, Crash Recovery & Graceful Drain Coordinator (Phase 5B).

Provides persistent job queues, priorities, task locks, idempotency keys,
checkpointing, pause/resume, retry limits, an emergency stop/kill switch,
and a thread-safe DrainCoordinator for graceful supervisor daemon shutdown.
Hardened with atomic file locks, atomic temp-file replacement, and corruption recovery.
"""

from __future__ import annotations

import fcntl
import json
import os
import signal
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc, markdown_escape
from guardian_agent.policy import consume_action_approval


VALID_STATES = {
    "draft", "awaiting_confirmation", "queued", "running", "awaiting_approval",
    "blocked", "failed", "cancelled", "completed",
}
ALLOWED_TRANSITIONS = {
    "draft": {"awaiting_confirmation", "queued", "cancelled"},
    "awaiting_confirmation": {"queued", "cancelled"},
    "queued": {"running", "awaiting_approval", "cancelled", "blocked"},
    "running": {"awaiting_approval", "blocked", "failed", "cancelled", "completed", "queued"},
    "awaiting_approval": {"queued", "cancelled", "blocked"},
    "blocked": {"queued", "cancelled"},
    "failed": {"queued", "cancelled"},
    "cancelled": set(),
    "completed": set(),
}


def tasks_dir(brain: ProjectBrain) -> Path:
    d = brain.directory / "tasks"
    d.mkdir(exist_ok=True)
    return d


def queue_file(brain: ProjectBrain) -> Path:
    return tasks_dir(brain) / "queue.json"


def locks_file(brain: ProjectBrain) -> Path:
    return tasks_dir(brain) / "locks.json"


def emergency_stop_file(brain: ProjectBrain) -> Path:
    return tasks_dir(brain) / "emergency-stop.json"


def _lock_file_path(target_path: Path) -> Path:
    return target_path.parent / f".{target_path.name}.lock"


def _atomic_json_read(file_path: Path, default_factory=list):
    """Safely read JSON file with a shared file lock and corruption recovery."""
    if not file_path.is_file():
        return default_factory()

    lock_path = _lock_file_path(file_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_SH)
        try:
            content = file_path.read_text(encoding="utf-8")
            if not content.strip():
                return default_factory()
            return json.loads(content)
        except (json.JSONDecodeError, OSError):
            pass
    finally:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_fd.close()

    # On corruption: upgrade to exclusive lock before mutating/moving corrupted file
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        if file_path.is_file():
            try:
                content = file_path.read_text(encoding="utf-8")
                if content.strip():
                    return json.loads(content)
            except (json.JSONDecodeError, OSError):
                corrupted_path = file_path.parent / f"{file_path.name}.corrupted.{int(time.time())}"
                try:
                    os.replace(file_path, corrupted_path)
                except OSError:
                    pass
        return default_factory()
    finally:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_fd.close()



def _atomic_json_read_modify_write(file_path: Path, modify_fn, default_factory=list):
    """Safely read, modify, and atomically write JSON file with an exclusive file lock."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _lock_file_path(file_path)
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        data = default_factory()
        if file_path.is_file():
            try:
                content = file_path.read_text(encoding="utf-8")
                if content.strip():
                    data = json.loads(content)
            except (json.JSONDecodeError, OSError):
                corrupted_path = file_path.parent / f"{file_path.name}.corrupted.{int(time.time())}"
                try:
                    os.replace(file_path, corrupted_path)
                except OSError:
                    pass
                data = default_factory()

        result, updated_data = modify_fn(data)

        # Atomic temp file write
        tmp_path = file_path.parent / f".{file_path.name}.tmp.{uuid.uuid4().hex}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(updated_data, indent=2) + "\n")
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, file_path)
        return result
    finally:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_fd.close()


def _load_queue(brain: ProjectBrain) -> list[dict]:
    return _atomic_json_read(queue_file(brain), list)


def _save_queue(brain: ProjectBrain, tasks: list[dict]) -> None:
    def _modify(_existing):
        return None, tasks
    _atomic_json_read_modify_write(queue_file(brain), _modify, list)


def enqueue_task(
    brain: ProjectBrain,
    task_type: str,
    summary: str,
    priority: str = "normal",
    idempotency_key: str | None = None,
) -> dict:
    clean_type = markdown_escape(task_type)
    clean_summary = markdown_escape(summary)
    clean_key = markdown_escape(idempotency_key or str(uuid.uuid4()))

    def _enqueue(tasks: list[dict]):
        existing = next((t for t in tasks if t.get("idempotency_key") == clean_key), None)
        if existing:
            return existing, tasks

        task_id = f"task-{uuid.uuid4().hex[:8]}"
        entry = {
            "id": task_id,
            "type": clean_type,
            "summary": clean_summary,
            "priority": priority,
            "idempotency_key": clean_key,
            "state": "queued",
            "retry_count": 0,
            "created_at": now_utc(),
            "updated_at": now_utc(),
        }
        tasks.append(entry)
        return entry, tasks

    entry = _atomic_json_read_modify_write(queue_file(brain), _enqueue, list)
    append_journey(brain, f"Task Enqueued: {clean_summary}", [f"ID: {entry['id']}", f"Priority: {priority}"])
    return entry


def update_task_state(brain: ProjectBrain, task_id: str, new_state: str) -> dict:
    state = markdown_escape(new_state)
    if state not in VALID_STATES:
        raise GuardianError(f"Invalid task state {state!r}.")

    def _update(tasks: list[dict]):
        task = next((t for t in tasks if t["id"] == task_id), None)
        if not task:
            raise GuardianError(f"Task {task_id!r} not found in queue.")
        previous = task["state"]
        if state != previous and state not in ALLOWED_TRANSITIONS.get(previous, set()):
            raise GuardianError(f"Task {task_id!r} cannot transition from {previous!r} to {state!r}.")
        task["state"] = state
        task["updated_at"] = now_utc()
        return task, tasks

    return _atomic_json_read_modify_write(queue_file(brain), _update, list)


def recover_interrupted_tasks(brain: ProjectBrain) -> list[dict]:
    """Safely recover crash-interrupted work without executing it automatically."""
    def _recover(tasks: list[dict]):
        recovered: list[dict] = []
        for task in tasks:
            if task.get("state") != "running":
                continue
            if task.get("external_side_effect", False):
                task["state"] = "awaiting_approval"
                task["recovery_reason"] = "Interrupted during potential external side effect; review required."
            else:
                task["state"] = "queued"
                task["recovery_reason"] = "Recovered after an interrupted local task."
            task["updated_at"] = now_utc()
            recovered.append(task)
        return recovered, tasks

    recovered = _atomic_json_read_modify_write(queue_file(brain), _recover, list)
    if recovered:
        append_journey(brain, "Task Recovery Performed", [f"Recovered {len(recovered)} interrupted task(s)."])
    return recovered


def get_task_status(brain: ProjectBrain, task_id: str) -> dict:
    tasks = _load_queue(brain)
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        raise GuardianError(f"Task {task_id!r} not found in queue.")
    return task


def list_queued_tasks(brain: ProjectBrain) -> list[dict]:
    return _load_queue(brain)


def acquire_lock(brain: ProjectBrain, resource_name: str) -> bool:
    clean_res = markdown_escape(resource_name)

    def _acquire(locks: dict):
        if locks.get(clean_res):
            return False, locks
        locks[clean_res] = {"acquired_at": now_utc()}
        return True, locks

    return _atomic_json_read_modify_write(locks_file(brain), _acquire, dict)


def release_lock(brain: ProjectBrain, resource_name: str) -> None:
    clean_res = markdown_escape(resource_name)

    def _release(locks: dict):
        if clean_res in locks:
            del locks[clean_res]
        return None, locks

    _atomic_json_read_modify_write(locks_file(brain), _release, dict)


def kill_switch(brain: ProjectBrain) -> dict:
    """Emergency stop switch — halts all running and queued tasks immediately."""
    # Write emergency stop active FIRST so concurrent processes see it immediately
    def _set_stop(data: dict):
        data["active"] = True
        data["triggered_at"] = now_utc()
        return None, data

    _atomic_json_read_modify_write(emergency_stop_file(brain), _set_stop, dict)

    def _cancel_all(tasks: list[dict]):
        stopped_count = 0
        for t in tasks:
            if t["state"] in {"queued", "running", "awaiting_approval"}:
                t["state"] = "cancelled"
                t["updated_at"] = now_utc()
                stopped_count += 1
        return stopped_count, tasks

    stopped_count = _atomic_json_read_modify_write(queue_file(brain), _cancel_all, list)
    append_journey(brain, "EMERGENCY STOP TRIGGERED", [f"Cancelled {stopped_count} active tasks."])
    return {
        "status": "emergency_stop_triggered",
        "tasks_stopped": stopped_count,
        "timestamp": now_utc(),
    }



def is_kill_switch_active(brain: ProjectBrain) -> bool:
    data = _atomic_json_read(emergency_stop_file(brain), dict)
    return bool(data.get("active", False))


def resume_after_kill_switch(brain: ProjectBrain, approval_id: str) -> dict:
    consume_action_approval(
        brain,
        approval_id,
        "runtime_resume",
        "guardian-runtime",
    )

    def _resume(data: dict):
        data["active"] = False
        data["resumed_at"] = now_utc()
        data["approval_id"] = approval_id
        return None, data

    _atomic_json_read_modify_write(emergency_stop_file(brain), _resume, dict)
    append_journey(
        brain,
        "Runtime Resumed After Emergency Stop",
        [f"Approval: {approval_id}", "Cancelled tasks were not automatically requeued."],
    )
    return {"active": False, "approval_id": approval_id}


# ---------------------------------------------------------------------------
# Graceful Drain Coordinator (Phase 5B)
# ---------------------------------------------------------------------------


class DrainCoordinator:
    """Thread-safe coordinator for graceful supervisor daemon shutdown/drain.

    States:
      - Running (default): normal operation, new work is accepted.
      - Draining: drain was requested (e.g. via SIGTERM/SIGINT).
        In-flight work continues but no new work is dispatched.
      - Drained: all in-flight work completed after drain request.

    Shutdown hooks can be registered to run during the drain completion phase.
    """

    def __init__(self) -> None:
        self._drain_requested = threading.Event()
        self._lock = threading.Lock()
        self._inflight_count: int = 0
        self._shutdown_hooks: list[Callable[[], None]] = []

    # --- Drain signaling ---

    def request_drain(self) -> None:
        """Signal that a graceful drain should begin.

        In-flight work is allowed to finish; the daemon loop will stop
        dispatching new work and exit after drain completes.
        """
        self._drain_requested.set()

    def is_draining(self) -> bool:
        """Return True if drain has been requested."""
        return self._drain_requested.is_set()

    # --- In-flight tracking ---

    def register_inflight(self) -> None:
        """Record one unit of work that has started."""
        with self._lock:
            self._inflight_count += 1

    def complete_inflight(self) -> None:
        """Record completion of one unit of work."""
        with self._lock:
            if self._inflight_count > 0:
                self._inflight_count -= 1

    @property
    def inflight_count(self) -> int:
        with self._lock:
            return self._inflight_count

    def is_drained(self) -> bool:
        """Return True if drain was requested AND no in-flight work remains."""
        return self.is_draining() and self.inflight_count == 0

    # --- Shutdown hooks ---

    def add_shutdown_hook(self, hook: Callable[[], None]) -> None:
        """Register a cleanup callback invoked when drain completes."""
        with self._lock:
            self._shutdown_hooks.append(hook)

    def _run_shutdown_hooks(self) -> None:
        """Execute all registered shutdown hooks, swallowing exceptions."""
        hooks: list[Callable[[], None]] = []
        with self._lock:
            hooks = list(self._shutdown_hooks)
            self._shutdown_hooks.clear()
        for hook in hooks:
            try:
                hook()
            except Exception:
                pass

    # --- Await drain completion ---

    def wait_for_drain(self, timeout: float = 30.0) -> bool:
        """Block until all in-flight work finishes or *timeout* seconds elapse.

        Shutdown hooks are executed before blocking.

        Returns:
            True if fully drained (no in-flight work remains), False if timed out.
        """
        self._run_shutdown_hooks()
        deadline = time.monotonic() + max(0.1, timeout)
        while time.monotonic() < deadline:
            if self.is_drained():
                return True
            time.sleep(0.1)
        return self.is_drained()

    def reset(self) -> None:
        """Reset the coordinator to its initial (Running) state.

        This is primarily useful in tests.
        """
        self._drain_requested.clear()
        with self._lock:
            self._inflight_count = 0
            self._shutdown_hooks.clear()

    def __repr__(self) -> str:
        state = "draining" if self.is_draining() else "active"
        return (
            f"<DrainCoordinator state={state} "
            f"inflight={self.inflight_count} "
            f"hooks={len(self._shutdown_hooks)}>"
        )


# ---------------------------------------------------------------------------
# Signal handlers for graceful shutdown
# ---------------------------------------------------------------------------


def install_drain_signal_handlers(
    drain: DrainCoordinator,
    signals: tuple[int, ...] = (signal.SIGTERM, signal.SIGINT),
) -> list[tuple[int, Any]]:
    """Install signal handlers that trigger drain on the given signals.

    Must be called from the **main thread** (signal.signal restriction).

    Returns:
        List of (signum, original_handler) tuples for later restoration.
    """
    def _handler(signum: int, frame: Any | None) -> None:
        drain.request_drain()

    restored: list[tuple[int, Any]] = []
    for sig in signals:
        try:
            original = signal.signal(sig, _handler)
            restored.append((sig, original))
        except (ValueError, OSError):
            # Not in main thread or signal not supported
            pass
    return restored


def restore_signal_handlers(restored: list[tuple[int, Any]]) -> None:
    """Restore previously saved signal handlers."""
    for sig, handler in restored:
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass
