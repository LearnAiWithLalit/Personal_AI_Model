"""Bounded local supervisor for Guardian execution records (Phase 5 Autonomous Daemon Hardened).

The supervisor is a durable coordination layer. It inspects execution records,
recovers stale leases, writes bounded executor tickets, monitors provider capacity,
and orchestrates autonomous background worker loop execution up to max_workers limit.
"""

from __future__ import annotations

import fcntl
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc
from guardian_agent.execution import (
    list_executions,
    next_execution_stage,
    recover_execution,
)
from guardian_agent.model_policy import is_model_allowed
from guardian_agent.runtime import is_kill_switch_active

_SUPERVISOR_DIR = Path("tasks") / "supervisor"
_MAX_ITEMS_PER_RUN = 100
_MAX_HISTORY = 50
_MAX_TEXT = 500
_TICKET_STATES = {
    "ready",
    "blocked",
    "dispatched",
    "processed",
    "awaiting_primary_review",
}


def _directory(brain: ProjectBrain) -> Path:
    path = brain.directory / _SUPERVISOR_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _supervisor_directory(brain: ProjectBrain) -> Path:
    return brain.directory / _SUPERVISOR_DIR


def _execution_directory(brain: ProjectBrain) -> Path:
    return brain.directory / "tasks" / "executions"


def _malformed_execution_files(brain: ProjectBrain) -> list[str]:
    """Return malformed execution record stems without exposing file contents."""
    directory = _execution_directory(brain)
    if not directory.is_dir():
        return []

    malformed = []
    for path in sorted(directory.glob("exec-*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            malformed.append(path.stem)
    return malformed


def _state_path(brain: ProjectBrain) -> Path:
    return _directory(brain) / "state.json"


def _ticket_path(brain: ProjectBrain, execution_id: str, stage_id: str) -> Path:
    return _directory(brain) / f"ticket-{execution_id}-{stage_id}.json"


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _bounded(value: object) -> str:
    return str(value).replace("\x00", "").strip()[:_MAX_TEXT]


@contextmanager
def _supervisor_lock(brain: ProjectBrain):
    """Acquire a non-blocking single-instance supervisor lock."""
    path = _directory(brain) / "supervisor.lock"
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise GuardianError(
                "Another supervisor run is active."
            ) from error
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _lock_is_active(brain: ProjectBrain) -> bool:
    """Inspect actual flock state without modifying anything."""
    path = _supervisor_directory(brain) / "supervisor.lock"
    if not path.exists():
        return False

    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False


def _ticket_state(stage: dict[str, Any]) -> str:
    model = stage.get("model")
    if model and not is_model_allowed(model):
        return "blocked"
    if stage.get("executor") == "primary-review":
        return "awaiting_primary_review"
    return "ready"


def _write_ticket(
    brain: ProjectBrain,
    execution: dict[str, Any],
    stage: dict[str, Any],
) -> dict[str, Any]:
    path = _ticket_path(brain, execution["id"], stage["id"])
    previous = _read_json(path)

    ticket = {
        "version": 1,
        "execution_id": execution["id"],
        "stage_id": stage["id"],
        "executor": stage.get("executor"),
        "provider": stage.get("provider"),
        "model": stage.get("model"),
        "task": _bounded(execution.get("task", "")),
        "purpose": _bounded(stage.get("purpose", "")),
        "created_at": previous.get("created_at", now_utc()),
        "updated_at": now_utc(),
        "state": _ticket_state(stage),
    }

    _atomic_write(path, ticket)
    return ticket


def _save_state(brain: ProjectBrain, summary: dict[str, Any]) -> None:
    previous = _read_json(_state_path(brain))
    history = list(previous.get("history", []))
    history.append(
        {
            "timestamp": summary["timestamp"],
            "tickets_written": summary["tickets_written"],
            "stale_leases_recovered": summary["stale_leases_recovered"],
        }
    )

    summary["history"] = history[-_MAX_HISTORY:]
    _atomic_write(_state_path(brain), summary)


def supervisor_run_once(brain: ProjectBrain) -> dict[str, Any]:
    """Run one bounded supervisor cycle."""
    if is_kill_switch_active(brain):
        raise GuardianError(
            "Emergency stop is active; supervisor did not run."
        )

    with _supervisor_lock(brain):
        tickets: list[dict[str, Any]] = []
        corrupted: list[str] = _malformed_execution_files(brain)[:_MAX_ITEMS_PER_RUN]
        recovered = 0
        inspected = 0

        executions = list_executions(brain)[:_MAX_ITEMS_PER_RUN]

        for execution in executions:
            inspected += 1

            if execution.get("status") in {"completed", "failed"}:
                continue

            try:
                recovery = recover_execution(brain, execution["id"])
                recovered += recovery.get(
                    "stale_claims_recovered",
                    0,
                )
                stage_info = next_execution_stage(
                    brain,
                    execution["id"],
                )
            except GuardianError:
                corrupted.append(execution.get("id", "unknown"))
                continue

            stage = stage_info.get("stage")

            if not stage:
                continue

            # The supervisor only creates work for stages awaiting an executor.
            # Claimed, completed, skipped, and failed stages are ignored.
            if stage.get("state") != "pending":
                continue

            if len(tickets) >= _MAX_ITEMS_PER_RUN:
                break

            tickets.append(
                _write_ticket(
                    brain,
                    execution,
                    stage,
                )
            )

        summary = {
            "version": 1,
            "timestamp": now_utc(),
            "executions_inspected": inspected,
            "tickets_written": len(tickets),
            "stale_leases_recovered": recovered,
            "corrupted_executions": corrupted[:_MAX_ITEMS_PER_RUN],
            "history": [],
        }

        _save_state(brain, summary)

    append_journey(
        brain,
        "Supervisor Run Completed",
        [
            f"Tickets written: {len(tickets)}",
            f"Recovered leases: {recovered}",
        ],
    )

    return {
        **summary,
        "tickets": tickets,
    }


def supervisor_status(brain: ProjectBrain) -> dict[str, Any]:
    """Return read-only supervisor state and ticket information."""
    directory = _supervisor_directory(brain)
    state = _read_json(directory / "state.json")

    tickets: list[dict[str, Any]] = []
    for path in sorted(
        directory.glob("ticket-*.json")
    )[:_MAX_ITEMS_PER_RUN]:
        payload = _read_json(path)
        if payload:
            tickets.append(payload)

    return {
        "active_lock": _lock_is_active(brain),
        "last_run": state,
        "ticket_counts": {
            status: sum(
                ticket.get("state") == status
                for ticket in tickets
            )
            for status in sorted(_TICKET_STATES)
        },
        "awaiting_primary_review": [
            ticket["stage_id"]
            for ticket in tickets
            if ticket.get("state") == "awaiting_primary_review"
        ],
    }


def supervisor_daemon_run(
    brain: ProjectBrain,
    interval_seconds: int = 10,
    max_cycles: int | None = 6,
    max_workers: int = 4,
    indefinite: bool = False,
) -> dict[str, Any]:
    """Run an autonomous background worker daemon loop.

    Coordinates supervisor cycles, recovers stale stage leases, checks provider capacity,
    claims tickets safely under process locks, and processes ready tasks concurrently up to max_workers limit.
    """
    if interval_seconds < 1 or interval_seconds > 3600:
        raise GuardianError("interval_seconds must be between 1 and 3600.")
    if max_workers < 1 or max_workers > 16:
        raise GuardianError("max_workers must be between 1 and 16.")

    from guardian_agent.executor_worker import process_ready_tickets
    from guardian_agent.provider_capacity import provider_capacity_status

    cycles = []
    processed_count = 0
    cycle_index = 0

    while True:
        if is_kill_switch_active(brain):
            append_journey(brain, "Supervisor Daemon Stopped", ["Emergency stop activated."])
            break

        if not indefinite and max_cycles and cycle_index >= max_cycles:
            break

        cycle_start = time.time()
        cycle_res = supervisor_run_once(brain)

        cap = provider_capacity_status(brain)
        active_providers = [p for p, data in cap.get("providers", {}).items() if data.get("available")]

        if is_kill_switch_active(brain):
            cycles.append({
                "cycle": cycle_index + 1,
                "timestamp": now_utc(),
                "supervisor": cycle_res,
                "processed_tickets": 0,
                "active_providers": active_providers,
            })
            cycle_index += 1
            break

        work_res = process_ready_tickets(brain, max_tickets=max_workers)


        processed_now = len(work_res.get("processed", []))
        processed_count += processed_now

        cycles.append({
            "cycle": cycle_index + 1,
            "timestamp": now_utc(),
            "supervisor": cycle_res,
            "processed_tickets": processed_now,
            "active_providers": active_providers,
        })

        cycle_index += 1

        if is_kill_switch_active(brain):
            break

        if not indefinite and max_cycles and cycle_index >= max_cycles:
            break

        elapsed = time.time() - cycle_start
        sleep_dur = max(0.1, interval_seconds - elapsed)
        time.sleep(sleep_dur)

    append_journey(
        brain,
        "Supervisor Daemon Loop Completed",
        [
            f"Total Cycles: {cycle_index}",
            f"Processed Tickets: {processed_count}",
            f"Emergency Stop Active: {is_kill_switch_active(brain)}",
        ],
    )

    return {
        "status": "stopped" if is_kill_switch_active(brain) else "completed",
        "stopped": is_kill_switch_active(brain),
        "cycles_completed": cycle_index,
        "total_processed": processed_count,
        "emergency_stop": is_kill_switch_active(brain),
        "cycles": cycles,
    }



def supervisor_run(
    brain: ProjectBrain,
    interval_seconds: int = 600,
    max_cycles: int = 6,
) -> dict[str, Any]:
    """Run a bounded foreground supervisor loop."""
    if interval_seconds < 60 or interval_seconds > 3600:
        raise GuardianError("interval_seconds must be between 60 and 3600.")
    if max_cycles < 1 or max_cycles > 12:
        raise GuardianError("max_cycles must be between 1 and 12.")

    return supervisor_daemon_run(brain, interval_seconds=interval_seconds, max_cycles=max_cycles)
