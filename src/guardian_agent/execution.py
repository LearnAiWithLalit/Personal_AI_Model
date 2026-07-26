"""Durable Free-Resource Execution Governor.

Converts a dispatched orchestration into an ordered, recoverable execution plan
across local Ollama, FreeBuff, safe free/free-limited OmniRoute specialist
routes, one final-review-reserve route, and a manual primary-model final-green-
signal stage.

This module is a control/evidence layer. It must not itself call a model, start
FreeBuff, send files externally, edit code, commit, push, or perform any
external action.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, markdown_escape, now_utc

from guardian_agent.gateway import list_routes_for_task
from guardian_agent.health import check_provider_health
from guardian_agent.model_policy import PROHIBITED_MODELS, is_model_allowed
from guardian_agent.runtime import is_kill_switch_active
from guardian_agent.freebuff import freebuff_status
from guardian_agent.orchestration import orchestrate_show as _orchestrate_show
from guardian_agent.orchestration import _classify_task as _reclassify_task
from guardian_agent.provider_capacity import require_capacity_available


EXECUTIONS_DIR = "executions"
_MAX_EVIDENCE_LENGTH = 10_000
_MAX_EVENT_HISTORY = 100

_PROTECTED_PATH_PATTERNS = re.compile(
    r"^(\.env.*|\.git.*|\.venv.*|\.ssh.*|vault.*|\.agent/vault.*|credentials.*|secrets.*|.*\.pem|.*\.key|.*\.pfx|.*\.p12|.*\.sqlite|.*\.db)$",
    re.IGNORECASE,
)

_SENSITIVE_PATH_PARTS = frozenset({
    ".env",
    ".agent/vault",
    ".agent/vault.json",
    ".agent/vault.lock",
    ".git",
    "node_modules",
    "venv",
    ".venv",
})


@dataclass
class ExecutionStage:
    """One stage in an execution plan."""

    id: str
    executor: str  # "ollama" | "freebuff" | "omniroute" | "primary-review"
    provider: str | None = None
    model: str | None = None
    purpose: str = ""
    selection_reason: str = ""
    state: str = "pending"  # "pending" | "claimed" | "dispatched" | "passed" | "failed" | "skipped"
    attempt_count: int = 0
    lease_id: str | None = None
    lease_expires_at: float | None = None
    dispatch_id: str | None = None
    dispatched_at: str | None = None
    evidence: str = ""
    artifact_path: str | None = None
    adapter_target: str | None = None
    adapter_token: str | None = None
    allowed_paths: list[str] = field(default_factory=list)
    artifacts_changed: list[str] = field(default_factory=list)





@dataclass
class ExecutionRecord:
    """Persistent record of one execution plan."""

    id: str
    orchestration_id: str
    task: str
    task_type: str
    status: str  # "planned" | "running" | "awaiting_final_review" | "completed" | "failed"
    stages: list[ExecutionStage]
    current_stage_index: int = 0
    created_at: str = field(default_factory=now_utc)
    updated_at: str = field(default_factory=now_utc)
    events: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Private helpers & Execution Lock
# ---------------------------------------------------------------------------


class ExecutionLockManager:
    """Process lock shared between handoff creation and startup reconciliation."""

    def __init__(self, brain: ProjectBrain) -> None:
        self.brain = brain
        self.lock_file = brain.directory / "executions.lock"
        self._fd = None


    def __enter__(self) -> ExecutionLockManager:
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self._fd = open(self.lock_file, "w", encoding="utf-8")
        try:
            fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX)
            self._fd.write(f"{os.getpid()}\n")
            self._fd.flush()
        except (OSError, IOError) as err:
            if self._fd:
                self._fd.close()
                self._fd = None
            raise GuardianError("Could not acquire execution lock.") from err
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._fd:
            try:
                fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
                self._fd.close()
            except OSError:
                pass
            self._fd = None



def _executions_dir(brain: ProjectBrain) -> Path:
    path = brain.directory / "tasks" / EXECUTIONS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _execution_path(brain: ProjectBrain, execution_id: str) -> Path:
    clean = markdown_escape(execution_id)
    if not clean.startswith("exec-") or not all(c.isalnum() or c == "-" for c in clean):
        raise GuardianError(f"Invalid execution ID: {execution_id!r}")
    return _executions_dir(brain) / f"{clean}.json"


def _atomic_write(path: Path, data: dict) -> None:
    """Atomic temporary-file replacement with 0600 file permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _load_record(brain: ProjectBrain, execution_id: str) -> ExecutionRecord:
    path = _execution_path(brain, execution_id)
    if not path.is_file():
        raise GuardianError(f"Execution {execution_id!r} was not found.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise GuardianError(f"Execution {execution_id!r} is corrupted.") from error
    return _deserialize(data)


def _save_record(brain: ProjectBrain, record: ExecutionRecord) -> None:
    record.updated_at = now_utc()
    data = _serialize(record, redact_token=False)
    _atomic_write(_execution_path(brain, record.id), data)


def _serialize_stage(stage: ExecutionStage, redact_token: bool = True) -> dict:
    tok = "[REDACTED]" if (redact_token and stage.adapter_token) else stage.adapter_token
    return {
        "id": stage.id,
        "executor": stage.executor,
        "provider": stage.provider,
        "model": stage.model,
        "purpose": stage.purpose,
        "selection_reason": stage.selection_reason,
        "state": stage.state,
        "attempt_count": stage.attempt_count,
        "lease_id": stage.lease_id,
        "lease_expires_at": stage.lease_expires_at,
        "dispatch_id": stage.dispatch_id,
        "dispatched_at": stage.dispatched_at,
        "evidence": stage.evidence,
        "artifact_path": stage.artifact_path,
        "artifacts_changed": list(stage.artifacts_changed),
        "adapter_target": stage.adapter_target,
        "adapter_token": tok,
        "allowed_paths": list(stage.allowed_paths),
    }



def _deserialize_stage(data: dict) -> ExecutionStage:
    return ExecutionStage(
        id=data["id"],
        executor=data.get("executor", "ollama"),
        provider=data.get("provider"),
        model=data.get("model"),
        purpose=data.get("purpose", ""),
        selection_reason=data.get("selection_reason", ""),
        state=data.get("state", "pending"),
        attempt_count=int(data.get("attempt_count", 0)),
        lease_id=data.get("lease_id"),
        lease_expires_at=data.get("lease_expires_at"),
        dispatch_id=data.get("dispatch_id"),
        dispatched_at=data.get("dispatched_at"),
        evidence=data.get("evidence", ""),
        artifact_path=data.get("artifact_path"),
        adapter_target=data.get("adapter_target"),
        adapter_token=data.get("adapter_token"),
        allowed_paths=list(data.get("allowed_paths", [])),
        artifacts_changed=list(data.get("artifacts_changed", [])),
    )





def _serialize(record: ExecutionRecord, redact_token: bool = True) -> dict:
    return {
        "id": record.id,
        "orchestration_id": record.orchestration_id,
        "task": record.task,
        "task_type": record.task_type,
        "status": record.status,
        "stages": [_serialize_stage(s, redact_token=redact_token) for s in record.stages],
        "current_stage_index": record.current_stage_index,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "events": list(record.events),
    }



def _deserialize(data: dict) -> ExecutionRecord:
    return ExecutionRecord(
        id=data["id"],
        orchestration_id=data.get("orchestration_id", ""),
        task=data.get("task", ""),
        task_type=data.get("task_type", "routing"),
        status=data.get("status", "planned"),
        stages=[_deserialize_stage(s) for s in data.get("stages", [])],
        current_stage_index=int(data.get("current_stage_index", 0)),
        created_at=data.get("created_at", now_utc()),
        updated_at=data.get("updated_at", now_utc()),
        events=list(data.get("events", [])),
    )


def _append_event(record: ExecutionRecord, event_type: str, detail: str) -> None:
    record.events.append({
        "timestamp": now_utc(),
        "type": event_type,
        "detail": markdown_escape(detail)[:_MAX_EVIDENCE_LENGTH],
    })
    # Trim to bounded history
    if len(record.events) > _MAX_EVENT_HISTORY:
        record.events = record.events[-_MAX_EVENT_HISTORY:]


def _safe_artifact_path(brain: ProjectBrain, artifact_path: str | None) -> str | None:
    """Validate that an artifact path is safe and project-relative."""
    if artifact_path is None:
        return None
    clean = markdown_escape(artifact_path)
    if not clean:
        return None
    absolute = (brain.root / clean).resolve()
    try:
        absolute.relative_to(brain.root.resolve())
    except ValueError:
        raise GuardianError(
            f"Artifact path {artifact_path!r} resolves outside the project root."
        ) from None
    for part in absolute.parts:
        if part in _SENSITIVE_PATH_PARTS:
            raise GuardianError(
                f"Artifact path {artifact_path!r} points to a protected directory ({part})."
            )
    return str(absolute.relative_to(brain.root))


def _classify_omniroute_usage(route: dict) -> str | None:
    """Map a route to an executor kind if it's a usable OmniRoute variant."""
    cost_tier = route.get("cost_tier", "")
    usage_class = route.get("usage_class", "")
    provider = route.get("provider", "")
    model = str(route.get("model", ""))

    if not is_model_allowed(model):
        return None
    if provider == "local-omniroute" and usage_class == "final-review":
        return "final-review"
    if provider == "local-omniroute" and cost_tier in ("free", "free-limited", "subscription"):
        return "omniroute"
    return None


def _orchestration_data(brain: ProjectBrain, orchestration_id: str) -> dict:
    """Load orchestration record from disk (read-only)."""
    data = _orchestrate_show(brain, orchestration_id)
    if data.get("status") != "dispatched":
        raise GuardianError(
            f"Orchestration {orchestration_id!r} is in status {data.get('status')!r}, "
            "not 'dispatched'. Only dispatched orchestrations can be planned into execution."
        )
    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def plan_execution(
    brain: ProjectBrain,
    orchestration_id: str,
    lease_seconds: int = 900,
) -> dict[str, Any]:
    """Create an execution plan from a dispatched orchestration.

    This function performs no model calls, no external actions, and no
    provider network access. It reads deterministic state from the
    orchestration and existing provider/health records.

    Planning the same orchestration twice returns the existing record
    without duplicating stages (idempotent).

    Args:
        brain: The project brain.
        orchestration_id: A dispatched orchestration ID.
        lease_seconds: Default lease duration for claimed stages.

    Returns:
        Execution plan record as a dict.
    """
    # Check emergency stop
    if is_kill_switch_active(brain):
        raise GuardianError(
            "The persistent emergency stop is active. "
            "Resume it first with an approved runtime resume before planning execution."
        )

    clean_id = markdown_escape(orchestration_id)
    if not clean_id:
        raise GuardianError("An orchestration ID is required.")

    # Idempotent: return existing plan
    execution_id = f"exec-{clean_id.removeprefix('orch-')}"
    existing_path = _execution_path(brain, execution_id)
    if existing_path.is_file():
        try:
            existing = _load_record(brain, execution_id)
            return _serialize(existing)
        except GuardianError:
            # Corrupted - re-plan below
            pass

    # Load orchestration data
    orch = _orchestration_data(brain, clean_id)
    task = orch.get("task", "")
    preview = orch.get("preview", {})
    task_type = orch.get("task_type", "routing")
    # Fallback: re-classify from the raw task text if task_type was not stored.
    # The stored task_type may be the default "routing" for old orchestration
    # records created before the task_type field was added.  Always re-classify
    # in that case -- the fallback classification is deterministic and free.
    if task_type == "routing":
        task_type = _reclassify_task(task)

    # Build ordered stages
    stages: list[ExecutionStage] = []
    stage_count = 0
    max_model_stages = 5

    # Check for a healthy final-review route up front so we can reserve a slot.
    # This prevents ordinary fallback stages from crowding out the final review.
    all_final_candidates = [
        r for r in list_routes_for_task(brain, task_type)
        if _classify_omniroute_usage(r) == "final-review"
        and check_provider_health(brain, r["provider"]).get("healthy", False)
    ]
    has_final_review = bool(all_final_candidates)

    # If a healthy final-review route exists, reserve one of the maximum five
    # automated slots for it so it cannot be crowded out by ordinary stages.
    ordinary_max = max_model_stages - 1 if has_final_review else max_model_stages

    # Determine if FreeBuff should be included
    freebuff_available = freebuff_status().get("available", False)
    include_freebuff = freebuff_available and task_type in ("coding", "review")

    raw_paths = orch.get("approved_paths") or preview.get("allowed_paths") or []
    normalized_paths = []
    for p in raw_paths:
        clean_p = p.strip()
        if clean_p and not _PROTECTED_PATH_PATTERNS.match(clean_p.rstrip("/")):
            normalized_paths.append(clean_p)

    requires_change = task_type in ("coding", "refactoring", "bugfix") or preview.get("requires_change", False)
    if requires_change and not normalized_paths:
        raise GuardianError("Execution planning failed: writable task has no explicit orchestration approved paths.")


    # 1. Best healthy local Ollama route
    all_local = [
        r for r in list_routes_for_task(brain, task_type)
        if r.get("provider") == "local-ollama"
        and r.get("cost_tier") == "local"
        and is_model_allowed(r.get("model", ""))
        and check_provider_health(brain, r["provider"]).get("healthy", False)
    ]
    if all_local and stage_count < ordinary_max:
        best = all_local[0]
        stages.append(ExecutionStage(
            id=f"stage-{len(stages) + 1}",
            executor="ollama",
            provider=best.get("provider"),
            model=best.get("model"),
            purpose=f"Primary local execution for '{task}'",
            selection_reason="Best available local Ollama route (local-first policy)",
            allowed_paths=list(normalized_paths),
        ))
        stage_count += 1

    # 2. FreeBuff stage (only for coding/review)
    if include_freebuff and stage_count < ordinary_max:
        stages.append(ExecutionStage(
            id=f"stage-{len(stages) + 1}",
            executor="freebuff",
            purpose=f"Interactive coding session for '{task}'",
            selection_reason="FreeBuff is available and task is coding/review",
            allowed_paths=list(normalized_paths),
        ))
        stage_count += 1

    # 3. Up to 3 healthy free/free-limited OmniRoute routes (provider diversity)
    all_omniroute = [
        r for r in list_routes_for_task(brain, task_type)
        if r.get("provider") == "local-omniroute"
        and is_model_allowed(r.get("model", ""))
        and _classify_omniroute_usage(r) == "omniroute"
        and check_provider_health(brain, r["provider"]).get("healthy", False)
    ]
    omniroute_added = 0
    for route in all_omniroute:
        if omniroute_added >= 3:
            break
        if stage_count >= ordinary_max:
            break
        # Skip if this route/prov combo would duplicate a model already used
        model_id = route.get("model", "")
        if any(s.model == model_id for s in stages):
            continue
        stages.append(ExecutionStage(
            id=f"stage-{len(stages) + 1}",
            executor="omniroute",
            provider=route.get("provider"),
            model=model_id,
            purpose=f"Free/free-limited OmniRoute specialist for '{task}'",
            selection_reason=(
                f"Cost tier: {route.get('cost_tier')}, "
                f"priority: {route.get('route_priority', '?')}"
            ),
            allowed_paths=list(normalized_paths),
        ))
        omniroute_added += 1
        stage_count += 1

    # 4. Final-review reserve route (always last among model stages).
    if has_final_review and stage_count < max_model_stages:
        best_final = all_final_candidates[0]
        stages.append(ExecutionStage(
            id=f"stage-{len(stages) + 1}",
            executor="omniroute",
            provider=best_final.get("provider"),
            model=best_final.get("model"),
            purpose="Final review reserve route",
            selection_reason="usage_class == final-review; reserved for final model review",
            allowed_paths=list(normalized_paths),
        ))
        stage_count += 1

    # 5. Manual primary-review stage (always final)
    stages.append(ExecutionStage(
        id=f"stage-{len(stages) + 1}",
        executor="primary-review",
        purpose="Manual primary-model final-green-signal",
        selection_reason="Mandatory final authority: user or configured primary model",
        allowed_paths=list(normalized_paths),
    ))


    # Create execution record
    execution_id = f"exec-{clean_id.removeprefix('orch-')}"
    record = ExecutionRecord(
        id=execution_id,
        orchestration_id=clean_id,
        task=task,
        task_type=task_type,
        status="planned",
        stages=stages,
        current_stage_index=0,
    )

    _append_event(record, "execution_planned", f"Planned {len(stages)} stages for orchestration {clean_id}")
    _save_record(brain, record)

    append_journey(
        brain,
        f"Execution Planned: {execution_id}",
        [
            f"Orchestration: {clean_id}",
            f"Task type: {task_type}",
            f"Stages: {len(stages)}",
            "No model call was performed during planning.",
        ],
    )

    return _serialize(record)


def show_execution(brain: ProjectBrain, execution_id: str) -> dict[str, Any]:
    """Return the full execution record."""
    record = _load_record(brain, execution_id)
    result = _serialize(record)
    # Do not include credential env or raw secrets in the serialized output
    for stage in result.get("stages", []):
        stage.pop("lease_id", None)
    return result


def list_executions(brain: ProjectBrain) -> list[dict[str, Any]]:
    """List all execution records with current status."""
    directory = _executions_dir(brain)
    if not directory.is_dir():
        return []
    results: list[dict[str, Any]] = []
    for path in sorted(directory.glob("exec-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            current = data.get("current_stage_index", 0)
            stages = data.get("stages", [])
            current_stage = stages[current] if 0 <= current < len(stages) else None
            results.append({
                "id": data.get("id", path.stem),
                "orchestration_id": data.get("orchestration_id"),
                "task": data.get("task", "?"),
                "task_type": data.get("task_type", "?"),
                "status": data.get("status", "?"),
                "current_stage": current_stage.get("id") if current_stage else None,
                "current_executor": current_stage.get("executor") if current_stage else None,
                "stage_count": len(stages),
                "created_at": data.get("created_at", "?"),
                "updated_at": data.get("updated_at", "?"),
            })
        except (OSError, json.JSONDecodeError):
            continue
    return results


def next_execution_stage(brain: ProjectBrain, execution_id: str) -> dict[str, Any]:
    """Read-only: return the current pending/claimed stage, if any.

    Returns a dict with the current stage info and a flag indicating whether
    execution is complete.
    """
    record = _load_record(brain, execution_id)
    idx = record.current_stage_index
    stages = record.stages

    if idx >= len(stages):
        return {
            "execution_id": execution_id,
            "status": record.status,
            "stage": None,
            "stage_count": len(stages),
            "completed": True,
        }

    current = stages[idx]
    return {
        "execution_id": execution_id,
        "status": record.status,
        "stage": _serialize_stage(current),
        "stage_index": idx,
        "stage_count": len(stages),
        "completed": False,
    }


def claim_execution_stage(
    brain: ProjectBrain,
    execution_id: str,
    stage_id: str,
    lease_seconds: int = 900,
) -> dict[str, Any]:
    """Claim the current stage for execution.

    Returns a random lease ID. Refuses wrong/non-current/already-claimed stages.

    Args:
        brain: The project brain.
        execution_id: The execution ID.
        stage_id: The exact stage ID to claim (must be the current stage).
        lease_seconds: Lease duration in seconds.

    Returns:
        Claim result including lease_id.
    """
    # Check emergency stop
    if is_kill_switch_active(brain):
        raise GuardianError(
            "The persistent emergency stop is active. "
            "Claims are blocked until the stop is resolved."
        )

    if lease_seconds < 60 or lease_seconds > 86400:
        raise GuardianError("Lease seconds must be between 60 and 86400.")

    record = _load_record(brain, execution_id)
    idx = record.current_stage_index
    stages = record.stages

    if idx >= len(stages):
        raise GuardianError(
            f"Execution {execution_id!r} has no more stages to claim."
        )

    current = stages[idx]
    if current.id != stage_id:
        raise GuardianError(
            f"Stage {stage_id!r} is not the current stage. "
            f"The current stage is {current.id!r}."
        )

    # If already claimed with a non-expired lease, refuse
    if current.state == "claimed" and current.lease_id:
        if current.lease_expires_at and current.lease_expires_at > time.time():
            raise GuardianError(
                f"Stage {stage_id!r} is already claimed by lease {current.lease_id[:12]}... "
                f"and has not expired."
            )
        # Expired lease — allow re-claim
        current.state = "pending"
        current.lease_id = None
        current.lease_expires_at = None

    if current.state != "pending":
        raise GuardianError(
            f"Stage {stage_id!r} is in state {current.state!r}, not 'pending'. "
            "Only pending stages can be claimed."
        )

    # Revalidate route policy and health at claim time.
    # If the provider/model is now prohibited, the provider is unhealthy,
    # or the route is in an observed retry/quota window, refuse the claim.
    if current.provider and current.model:
        if not is_model_allowed(current.model):
            raise GuardianError(
                f"Stage {stage_id!r} model {current.model!r} is now prohibited "
                "by model policy. Claim refused."
            )
        provider_health = check_provider_health(brain, current.provider)
        if not provider_health.get("healthy", False):
            raise GuardianError(
                f"Stage {stage_id!r} provider {current.provider!r} is now unhealthy "
                f"({provider_health.get('error_count', '?')} errors). Claim refused."
            )
        require_capacity_available(brain, current.provider, current.model)

    # Claim the stage
    lease_id = secrets.token_hex(16)
    current.state = "claimed"
    current.lease_id = lease_id
    current.lease_expires_at = time.time() + lease_seconds
    current.attempt_count = 1

    record.status = "running"
    _append_event(record, "stage_claimed", f"Stage {stage_id} ({current.executor}) claimed with lease")
    _save_record(brain, record)

    append_journey(
        brain,
        f"Execution Stage Claimed: {execution_id}/{stage_id}",
        [f"Executor: {current.executor}", f"Lease duration: {lease_seconds}s"],
    )

    return {
        "execution_id": execution_id,
        "stage_id": stage_id,
        "lease_id": lease_id,
        "lease_expires_at": current.lease_expires_at,
        "executor": current.executor,
        "provider": current.provider,
        "model": current.model,
    }


def record_execution_result(
    brain: ProjectBrain,
    execution_id: str,
    stage_id: str,
    lease_id: str,
    outcome: str,
    evidence: str,
    artifact_path: str | None = None,
    artifacts_changed: list[str] | None = None,
    dispatch_id: str | None = None,
    adapter_target: str | None = None,
    adapter_token: str | None = None,
) -> dict[str, Any]:

    """Record the result of a claimed execution stage."""
    if outcome not in ("passed", "failed", "skipped"):
        raise GuardianError("Outcome must be 'passed', 'failed', or 'skipped'.")

    record = _load_record(brain, execution_id)
    stages = record.stages

    # Idempotent replay: check across all completed stages first
    for past_stage in stages:
        if past_stage.id == stage_id and past_stage.lease_id == lease_id:
            if past_stage.state in ("passed", "failed", "skipped"):
                if past_stage.dispatch_id and past_stage.dispatch_id != dispatch_id:
                    raise GuardianError(
                        "Dispatch ID does not match the completed asynchronous dispatch."
                    )
                if past_stage.adapter_target and (not adapter_target or past_stage.adapter_target != adapter_target):
                    raise GuardianError(
                        f"Adapter target {adapter_target!r} does not match completed adapter target {past_stage.adapter_target!r}."
                    )
                if past_stage.adapter_token and (not adapter_token or past_stage.adapter_token != adapter_token):
                    raise GuardianError(
                        "Adapter token mismatch. Idempotent replay rejected: token does not match."
                    )
                return {
                    "execution_id": execution_id,
                    "status": record.status,
                    "stage_id": stage_id,
                    "outcome": past_stage.state,
                    "note": "Result already recorded. Idempotent replay accepted.",
                }

    idx = record.current_stage_index

    if idx >= len(stages):
        raise GuardianError(f"Execution {execution_id!r} has no stages to record a result for.")

    current = stages[idx]
    if current.id != stage_id:
        raise GuardianError(
            f"Stage {stage_id!r} is not the current stage. "
            f"The current stage is {current.id!r}."
        )

    # Validate the lease and, for asynchronous work, the durable dispatch ID.
    if current.lease_id != lease_id:
        raise GuardianError(
            f"Lease ID does not match. The current stage is claimed by a different lease."
        )
    if current.state == "dispatched":
        if not dispatch_id or current.dispatch_id != dispatch_id:
            raise GuardianError(
                "Dispatch ID does not match the current asynchronous dispatch."
            )
    elif current.state != "claimed":
        raise GuardianError(
            f"Stage {stage_id!r} is in state {current.state!r}, not 'claimed' or 'dispatched'."
        )

    # Validate adapter target and persistent token if bound
    if current.adapter_target:
        if not adapter_target or current.adapter_target != adapter_target:
            raise GuardianError(
                f"Adapter target {adapter_target!r} does not match dispatched adapter target {current.adapter_target!r}."
            )
    if current.adapter_token:
        if not adapter_token or current.adapter_token != adapter_token:
            raise GuardianError(
                "Adapter token mismatch. Result rejected: token does not match the persistent token bound to this stage."
            )


    # Record the result
    clean_evidence = markdown_escape(evidence)[:_MAX_EVIDENCE_LENGTH]
    if not clean_evidence:
        raise GuardianError("Evidence is required and must be non-empty after sanitization.")

    current.state = outcome
    current.evidence = clean_evidence
    if artifact_path:
        current.artifact_path = _safe_artifact_path(brain, artifact_path)

    all_artifacts = list(artifacts_changed) if artifacts_changed else []
    if current.artifact_path and current.artifact_path not in all_artifacts:
        all_artifacts.append(current.artifact_path)

    current.artifacts_changed = [_safe_artifact_path(brain, a) for a in all_artifacts]

    # Validate that EVERY changed artifact falls strictly within stage allowed_paths
    if current.allowed_paths and current.artifacts_changed:
        for art in current.artifacts_changed:
            art_clean = art.lstrip("/")
            matched = False
            for allowed in current.allowed_paths:
                allowed_clean = allowed.rstrip("/")
                if art_clean == allowed_clean or art_clean.startswith(allowed_clean + "/"):
                    matched = True
                    break
            if not matched:
                raise GuardianError(
                    f"Artifact path {art!r} is not within allowed paths for stage {stage_id}: {current.allowed_paths}"
                )



    _append_event(record, f"stage_{outcome}", f"Stage {stage_id} ({current.executor}): {clean_evidence[:200]}")

    # Determine next state
    if outcome == "passed":
        # Passed primary-review completes the execution
        if current.executor == "primary-review":
            record.status = "completed"
            _append_event(record, "execution_completed", "Primary review passed — execution complete.")
        else:
            terminal_idx = len(stages) - 1  # primary-review is always last
            for i in range(len(stages) - 2, idx, -1):
                s = stages[i]
                if s.executor == "omniroute" and "final review" in s.purpose.lower():
                    terminal_idx = i
                    break

            next_idx = idx + 1
            skipped_any = False
            while next_idx < terminal_idx:
                candidate = stages[next_idx]
                if candidate.state == "pending":
                    candidate.state = "skipped"
                    candidate.evidence = "Skipped because a prior ordinary stage passed."
                    skipped_any = True
                next_idx += 1

            record.current_stage_index = next_idx
            if skipped_any:
                _append_event(
                    record, "stage_skip",
                    f"Skipped ordinary stages {idx + 1}-{next_idx - 1} "
                    f"after ordinary stage {stage_id} passed",
                )

            if record.current_stage_index >= len(stages):
                record.status = "completed"
                _append_event(record, "execution_completed", "All stages completed.")
            else:
                next_stage = stages[record.current_stage_index]
                if next_stage.executor == "primary-review" or (
                    next_stage.executor == "omniroute"
                    and "final review" in next_stage.purpose.lower()
                ):
                    record.status = "awaiting_final_review"
                else:
                    record.status = "running"
    else:
        if current.executor == "primary-review":
            record.status = "failed"
            _append_event(record, "execution_failed", "Primary review failed — execution stopped.")
        else:
            record.current_stage_index = idx + 1
            if record.current_stage_index >= len(stages):
                record.status = "failed"
                _append_event(record, "execution_failed", "All stages exhausted without passing.")
            else:
                record.status = "running"

    _save_record(brain, record)

    append_journey(
        brain,
        f"Execution Stage Result: {execution_id}/{stage_id}",
        [f"Executor: {current.executor}", f"Outcome: {outcome}", f"Next status: {record.status}"],
    )

    return {
        "execution_id": execution_id,
        "stage_id": stage_id,
        "outcome": outcome,
        "status": record.status,
        "current_stage_index": record.current_stage_index,
        "stage_count": len(stages),
        "artifact_path": current.artifact_path,
    }


def mark_execution_dispatched(
    brain: ProjectBrain,
    execution_id: str,
    stage_id: str,
    lease_id: str,
    evidence: str,
    artifact_path: str | None = None,
    adapter_target: str | None = None,
    adapter_token: str | None = None,
) -> dict[str, Any]:
    """Persist an asynchronous dispatch without completing or advancing its stage."""
    record = _load_record(brain, execution_id)
    idx = record.current_stage_index
    if idx >= len(record.stages):
        raise GuardianError(f"Execution {execution_id!r} has no active stage to dispatch.")

    current = record.stages[idx]
    if current.id != stage_id:
        raise GuardianError(
            f"Stage {stage_id!r} is not the current stage. "
            f"The current stage is {current.id!r}."
        )
    if current.lease_id != lease_id:
        raise GuardianError("Lease ID does not match the current stage.")
    if current.state == "dispatched" and current.dispatch_id:
        return {
            "execution_id": execution_id,
            "stage_id": stage_id,
            "status": record.status,
            "state": "dispatched",
            "dispatch_id": current.dispatch_id,
            "lease_id": lease_id,
            "note": "Dispatch already recorded. Idempotent replay accepted.",
        }
    if current.state != "claimed":
        raise GuardianError(
            f"Stage {stage_id!r} is in state {current.state!r}, not 'claimed'."
        )

    clean_evidence = markdown_escape(evidence)[:_MAX_EVIDENCE_LENGTH]
    if not clean_evidence:
        raise GuardianError("Dispatch evidence is required.")

    current.state = "dispatched"
    current.dispatch_id = f"dispatch-{secrets.token_hex(16)}"
    current.dispatched_at = now_utc()
    current.evidence = clean_evidence
    current.artifact_path = _safe_artifact_path(brain, artifact_path)
    if adapter_target:
        current.adapter_target = adapter_target
    if adapter_token:
        current.adapter_token = adapter_token
    record.status = "running"
    _append_event(
        record,
        "stage_dispatched",
        f"Stage {stage_id} ({current.executor}) is awaiting verified worker result",
    )
    _save_record(brain, record)


    append_journey(
        brain,
        f"Execution Stage Dispatched: {execution_id}/{stage_id}",
        [f"Executor: {current.executor}", "State: awaiting verified result"],
    )
    return {
        "execution_id": execution_id,
        "stage_id": stage_id,
        "status": record.status,
        "state": "dispatched",
        "dispatch_id": current.dispatch_id,
        "lease_id": lease_id,
        "lease_expires_at": current.lease_expires_at,
        "artifact_path": current.artifact_path,
    }


def revert_execution_dispatch(
    brain: ProjectBrain,
    execution_id: str,
    stage_id: str,
    lease_id: str,
) -> None:
    """Revert a dispatched stage back to claimed state if handoff package creation fails."""
    record = _load_record(brain, execution_id)
    idx = record.current_stage_index
    if idx < len(record.stages):
        current = record.stages[idx]
        if current.id == stage_id and current.lease_id == lease_id and current.state == "dispatched":
            current.state = "claimed"
            current.dispatch_id = None
            current.dispatched_at = None
            current.adapter_target = None
            current.adapter_token = None
            _append_event(
                record,
                "stage_dispatch_reverted",
                f"Reverted stage {stage_id} dispatch due to package creation failure",
            )
            _save_record(brain, record)


def reconcile_dispatched_handoffs(brain: ProjectBrain) -> dict[str, Any]:
    """Startup reconciliation: check all dispatched stages across executions under project execution lock.

    If handoff package file is missing or corrupt, safely revert stage state back to claimed.
    """
    with ExecutionLockManager(brain):
        directory = _executions_dir(brain)
        if not directory.is_dir():
            return {"reconciled_count": 0, "reverted_count": 0}

        reconciled_count = 0
        reverted_count = 0

        for path in sorted(directory.glob("exec-*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                record = _deserialize(data)
                modified = False

                for stage in record.stages:
                    if stage.state == "dispatched" and stage.adapter_target:
                        reconciled_count += 1
                        pkg_file = brain.directory / "handoffs" / f"handoff_{stage.adapter_target}_{record.id}_{stage.id}.json"

                        valid_package = False
                        if pkg_file.is_file():
                            try:
                                pkg_data = json.loads(pkg_file.read_text(encoding="utf-8"))
                                if (
                                    pkg_data.get("dispatch_id") == stage.dispatch_id
                                    and pkg_data.get("adapter_token") == stage.adapter_token
                                ):
                                    valid_package = True
                            except (OSError, json.JSONDecodeError):
                                valid_package = False

                        if not valid_package:
                            stage.state = "claimed"
                            stage.dispatch_id = None
                            stage.dispatched_at = None
                            stage.adapter_target = None
                            stage.adapter_token = None
                            _append_event(
                                record,
                                "stage_dispatch_reconciled_revert",
                                f"Reconciled stage {stage.id}: missing/corrupt handoff package, reverted state to claimed",
                            )
                            modified = True
                            reverted_count += 1

                if modified:
                    _save_record(brain, record)

            except (OSError, json.JSONDecodeError, GuardianError):
                continue

        return {"reconciled_count": reconciled_count, "reverted_count": reverted_count}




def recover_execution(brain: ProjectBrain, execution_id: str) -> dict[str, Any]:
    """Recover stale claims and safely fail timed-out asynchronous dispatches.

    Idempotent: calling this on an execution with no expired claims or
    already-recovered stages returns the current state unchanged.

    Args:
        brain: The project brain.
        execution_id: The execution ID to recover.

    Returns:
        Recovery result with count of recovered claims.
    """
    record = _load_record(brain, execution_id)
    now = time.time()
    recovered = 0
    timed_out = 0

    for index, stage in enumerate(record.stages):
        if stage.state == "claimed" and stage.lease_id:
            if stage.lease_expires_at and stage.lease_expires_at <= now:
                stage.state = "pending"
                stage.lease_id = None
                stage.lease_expires_at = None
                recovered += 1
        elif stage.state == "dispatched" and stage.lease_id:
            if stage.lease_expires_at and stage.lease_expires_at <= now:
                stage.state = "failed"
                stage.evidence = "Asynchronous dispatch timed out before a verified result was received."
                timed_out += 1
                if index == record.current_stage_index:
                    record.current_stage_index = index + 1
                    if record.current_stage_index >= len(record.stages):
                        record.status = "failed"
                    else:
                        record.status = "running"

    if recovered or timed_out:
        _append_event(
            record,
            "recovery",
            f"Recovered {recovered} stale claim(s); failed {timed_out} timed-out dispatch(es)",
        )
        _save_record(brain, record)
        append_journey(
            brain,
            f"Execution Recovered: {execution_id}",
            [
                f"Stale claims expired: {recovered}",
                f"Timed-out dispatches failed: {timed_out}",
            ],
        )

    return {
        "execution_id": execution_id,
        "status": record.status,
        "stale_claims_recovered": recovered,
        "timed_out_dispatches": timed_out,
        "note": (
            "Expired claims were returned to pending and timed-out dispatches advanced safely."
            if recovered or timed_out else "No stale claims or timed-out dispatches found."
        ),
    }
