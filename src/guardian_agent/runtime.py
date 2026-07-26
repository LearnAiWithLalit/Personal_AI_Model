"""Durable Task Runtime, Job Queue & Crash Recovery (Phase G0).

Provides persistent job queues, priorities, task locks, idempotency keys,
checkpointing, pause/resume, retry limits, and an emergency stop/kill switch.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc, markdown_escape


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


def _load_queue(brain: ProjectBrain) -> list[dict]:
    p = queue_file(brain)
    if not p.is_file():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_queue(brain: ProjectBrain, tasks: list[dict]) -> None:
    queue_file(brain).write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")


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
    
    tasks = _load_queue(brain)
    existing = next((t for t in tasks if t.get("idempotency_key") == clean_key), None)
    if existing:
        return existing
        
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
    _save_queue(brain, tasks)
    append_journey(brain, f"Task Enqueued: {clean_summary}", [f"ID: {task_id}", f"Priority: {priority}"])
    return entry


def update_task_state(brain: ProjectBrain, task_id: str, new_state: str) -> dict:
    tasks = _load_queue(brain)
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        raise GuardianError(f"Task {task_id!r} not found in queue.")
    state = markdown_escape(new_state)
    if state not in VALID_STATES:
        raise GuardianError(f"Invalid task state {state!r}.")
    previous = task["state"]
    if state != previous and state not in ALLOWED_TRANSITIONS.get(previous, set()):
        raise GuardianError(f"Task {task_id!r} cannot transition from {previous!r} to {state!r}.")
    task["state"] = state
    task["updated_at"] = now_utc()
    _save_queue(brain, tasks)
    return task


def recover_interrupted_tasks(brain: ProjectBrain) -> list[dict]:
    """Safely recover crash-interrupted work without executing it automatically.

    A previous running task is returned to ``queued`` only when it is safe to
    retry. Tasks that may have caused an external side effect wait for a human
    approval/review instead.
    """
    tasks = _load_queue(brain)
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
    if recovered:
        _save_queue(brain, tasks)
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
    p = locks_file(brain)
    locks = {}
    if p.is_file():
        try:
            locks = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            locks = {}
            
    clean_res = markdown_escape(resource_name)
    if locks.get(clean_res):
        return False
        
    locks[clean_res] = {"acquired_at": now_utc()}
    p.write_text(json.dumps(locks, indent=2), encoding="utf-8")
    return True


def release_lock(brain: ProjectBrain, resource_name: str) -> None:
    p = locks_file(brain)
    if not p.is_file():
        return
    try:
        locks = json.loads(p.read_text(encoding="utf-8"))
        clean_res = markdown_escape(resource_name)
        if clean_res in locks:
            del locks[clean_res]
            p.write_text(json.dumps(locks, indent=2), encoding="utf-8")
    except Exception:
        pass


def kill_switch(brain: ProjectBrain) -> dict:
    """Emergency stop switch — halts all running and queued tasks immediately."""
    tasks = _load_queue(brain)
    stopped_count = 0
    for t in tasks:
        if t["state"] in {"queued", "running", "awaiting_approval"}:
            t["state"] = "cancelled"
            t["updated_at"] = now_utc()
            stopped_count += 1
            
    _save_queue(brain, tasks)
    append_journey(brain, "EMERGENCY STOP TRIGGERED", [f"Cancelled {stopped_count} active tasks."])
    return {
        "status": "emergency_stop_triggered",
        "tasks_stopped": stopped_count,
        "timestamp": now_utc(),
    }
