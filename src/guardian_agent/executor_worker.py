"""Ticket Executor Worker (Phase 2).

Consumes supervisor tickets, claims stage leases, executes bounded work packages
through appropriate executor adapters (deterministic, Ollama, FreeBuff, Aider, OmniRoute),
and records execution results and evidence.
"""

from __future__ import annotations

import json
import os
import urllib.error
from pathlib import Path
from typing import Any

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, markdown_escape, now_utc
from guardian_agent.execution import (
    claim_execution_stage,
    mark_execution_dispatched,
    next_execution_stage,
    record_execution_result,
    show_execution,
)
from guardian_agent.gateway import complete_task_with_model, resolve_configured_route
from guardian_agent.freebuff import create_freebuff_handoff
from guardian_agent.aider import create_aider_handoff
from guardian_agent.model_policy import is_model_allowed
from guardian_agent.vault import redact_secrets
from guardian_agent.runtime import is_kill_switch_active
from guardian_agent.supervisor import (
    _atomic_write as _write_supervisor_json,
    _read_json,
    _supervisor_directory,
    _ticket_path,
)

_MAX_TICKETS_DISCOVERY = 100


def _tickets_dir(brain: ProjectBrain) -> Path:
    return _supervisor_directory(brain)


def _mark_ticket_processed(
    brain: ProjectBrain,
    execution_id: str,
    stage_id: str,
    state: str,
) -> None:
    """Move a persisted ticket out of ready after its durable transition."""
    path = _ticket_path(brain, execution_id, stage_id)
    ticket = _read_json(path)
    if not ticket:
        return
    ticket["state"] = state
    ticket["updated_at"] = now_utc()
    _write_supervisor_json(path, ticket)


def list_ready_tickets(brain: ProjectBrain, limit: int = _MAX_TICKETS_DISCOVERY) -> list[dict[str, Any]]:
    """List bounded supervisor tickets ready for execution using bounded streaming discovery."""
    if limit < 1 or limit > _MAX_TICKETS_DISCOVERY:
        raise GuardianError(f"limit must be between 1 and {_MAX_TICKETS_DISCOVERY}.")

    directory = _tickets_dir(brain)
    if not directory.is_dir():
        return []

    ready: list[dict[str, Any]] = []
    inspected = 0
    max_inspected = limit * 10

    for entry in directory.glob("ticket-*.json"):
        if len(ready) >= limit or inspected >= max_inspected:
            break
        inspected += 1
        try:
            ticket = _read_json(entry)
            if ticket.get("state") == "ready":
                ready.append(ticket)
        except (GuardianError, OSError, json.JSONDecodeError):
            continue
    return ready


def _run_adapter(
    brain: ProjectBrain,
    ticket: dict[str, Any],
) -> tuple[str, str, str | None]:
    """Execute work for a ticket using the appropriate executor adapter.

    Returns:
        (outcome, evidence, artifact_path)
    """
    executor = ticket.get("executor", "deterministic")
    task_text = ticket.get("task", "")
    purpose = ticket.get("purpose", "")
    model = ticket.get("model")
    provider = ticket.get("provider")
    task_type = "coding" if "code" in task_text.lower() or "auth" in task_text.lower() else "routing"

    if executor == "deterministic":
        evidence = (
            f"DISPATCHED HANDOFF PACKAGE PREPARED:\n"
            f"Task: {task_text!r} ({purpose}). Awaiting worker implementation and verification."
        )
        return "dispatched", evidence, None

    elif executor in ("ollama", "omniroute"):
        prompt = f"Task: {task_text}\nPurpose: {purpose}"
        
        # Fail closed: Provider and model MUST be explicitly specified for model executors
        if not provider or not model:
            raise GuardianError(
                f"Executor {executor!r} requires explicit provider and model parameters."
            )

        try:
            route_dict = resolve_configured_route(brain, task_type, provider, model)
            res = complete_task_with_model(
                brain,
                task=task_type,
                prompt=prompt,
                route=route_dict,
            )
            response_text = str(res.get("response", "")).strip()

            # Empty or insufficient model response fails closed
            if not response_text or len(response_text) < 10:
                evidence = f"Model completion via {executor} returned empty or insufficient response."
                return "failed", evidence, None

            clean_text = redact_secrets(brain, response_text[:400])
            evidence = (
                f"DISPATCHED MODEL COMPLETION RECORDED via {executor} ({res.get('model', model)}):\n"
                f"{clean_text}\n\n"
                "Model response generated; awaiting code modification and independent verification."
            )
            return "dispatched", evidence, None
        except (GuardianError, OSError, urllib.error.URLError, json.JSONDecodeError, ValueError) as err:
            clean_err = redact_secrets(brain, str(err))
            evidence = f"Model execution via {executor} failed closed: {clean_err}"
            return "failed", evidence, None

    elif executor == "freebuff":
        try:
            handoff = create_freebuff_handoff(brain, task_text)
            saved_path = handoff.get("saved_path")
            evidence = (
                f"DISPATCHED FREEBUFF HANDOFF CREATED at {saved_path}.\n"
                "Worker handoff saved; awaiting worker implementation and verification."
            )
            return "dispatched", evidence, saved_path
        except (GuardianError, OSError, json.JSONDecodeError) as err:
            clean_err = redact_secrets(brain, str(err))
            evidence = f"FreeBuff execution failed: {clean_err}"
            return "failed", evidence, None

    elif executor == "aider":
        try:
            handoff = create_aider_handoff(brain, task_text)
            saved_path = handoff.get("saved_path")
            evidence = (
                f"DISPATCHED AIDER HANDOFF CREATED at {saved_path}.\n"
                "Worker handoff saved; awaiting worker implementation and verification."
            )
            return "dispatched", evidence, saved_path
        except (GuardianError, OSError, json.JSONDecodeError) as err:
            clean_err = redact_secrets(brain, str(err))
            evidence = f"Aider execution failed: {clean_err}"
            return "failed", evidence, None



    else:
        evidence = f"Unknown or unsupported executor kind {executor!r}."
        return "failed", evidence, None


def execute_ticket(
    brain: ProjectBrain,
    ticket: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute a single supervisor ticket."""
    if is_kill_switch_active(brain):
        raise GuardianError("Emergency stop is active; execution blocked.")

    # Validate ticket schema version
    if ticket.get("version") != 1:
        raise GuardianError(f"Unsupported ticket schema version {ticket.get('version')!r}.")

    state = ticket.get("state")
    if state != "ready":
        raise GuardianError(
            f"Ticket {ticket.get('stage_id')!r} state is {state!r}, not 'ready'. "
            "Only 'ready' tickets can be executed."
        )

    model = ticket.get("model")
    if model and not is_model_allowed(model):
        raise GuardianError(
            f"Model {model!r} is prohibited by policy. Ticket execution refused."
        )

    execution_id = ticket.get("execution_id")
    stage_id = ticket.get("stage_id")
    if not execution_id or not stage_id:
        raise GuardianError("Ticket is missing required execution_id or stage_id.")

    executor = ticket.get("executor", "deterministic")

    # Re-validate ticket metadata strictly against canonical current execution stage
    next_stage_info = next_execution_stage(brain, execution_id)
    curr_stage = next_stage_info.get("stage")
    if not curr_stage:
        raise GuardianError(f"Execution {execution_id!r} has no active current stage.")

    if curr_stage.get("id") != stage_id:
        raise GuardianError(
            f"Ticket stage {stage_id!r} does not match canonical current stage {curr_stage.get('id')!r}."
        )
    if curr_stage.get("state") != "pending":
        raise GuardianError(
            f"Canonical current stage {stage_id!r} is in state {curr_stage.get('state')!r}, not 'pending'."
        )

    # Exact equality checks against canonical execution record task
    ex_record = show_execution(brain, execution_id)
    canonical_task = ex_record.get("task")
    if canonical_task and ticket.get("task") != canonical_task:
        raise GuardianError(
            f"Ticket task {ticket.get('task')!r} does not match canonical execution task {canonical_task!r}."
        )


    if curr_stage.get("purpose") and ticket.get("purpose") != curr_stage.get("purpose"):
        raise GuardianError(
            f"Ticket purpose {ticket.get('purpose')!r} does not match canonical stage purpose {curr_stage.get('purpose')!r}."
        )
    if curr_stage.get("executor") != ticket.get("executor"):
        raise GuardianError(
            f"Ticket executor {ticket.get('executor')!r} does not match canonical stage executor {curr_stage.get('executor')!r}."
        )
    if curr_stage.get("provider") != ticket.get("provider"):
        raise GuardianError(
            f"Ticket provider {ticket.get('provider')!r} does not match canonical stage provider {curr_stage.get('provider')!r}."
        )
    if curr_stage.get("model") != ticket.get("model"):
        raise GuardianError(
            f"Ticket model {ticket.get('model')!r} does not match canonical stage model {curr_stage.get('model')!r}."
        )


    # Safe Dry-Run Semantics: DO NOT claim leases, mutate state, or record results in dry_run!
    if dry_run:
        return {
            "dry_run": True,
            "execution_id": execution_id,
            "stage_id": stage_id,
            "executor": executor,
            "model": model,
            "task": ticket.get("task", ""),
            "purpose": ticket.get("purpose", ""),
            "would_claim_lease": True,
            "status": "simulated",
        }

    # Live Execution: Claim lease on stage
    claim = claim_execution_stage(brain, execution_id, stage_id, lease_seconds=900)
    lease_id = claim["lease_id"]

    # Run adapter
    outcome, evidence, artifact_path = _run_adapter(brain, ticket)

    # A handoff/model response starts asynchronous work; it is not a result.
    if outcome == "dispatched":
        res = mark_execution_dispatched(
            brain,
            execution_id=execution_id,
            stage_id=stage_id,
            lease_id=lease_id,
            evidence=evidence,
            artifact_path=artifact_path,
        )
    else:
        res = record_execution_result(
            brain,
            execution_id=execution_id,
            stage_id=stage_id,
            lease_id=lease_id,
            outcome=outcome,
            evidence=evidence,
            artifact_path=artifact_path,
        )
    _mark_ticket_processed(
        brain,
        execution_id,
        stage_id,
        "dispatched" if outcome == "dispatched" else "processed",
    )

    append_journey(
        brain,
        f"Ticket Processed: {execution_id}/{stage_id}",
        [
            f"Executor: {executor}",
            f"Outcome: {outcome}",
            f"Dry run: False",
        ],
    )

    return {
        "execution_id": execution_id,
        "stage_id": stage_id,
        "executor": executor,
        "outcome": outcome,
        "evidence": evidence,
        "artifact_path": artifact_path,
        "dispatch_id": res.get("dispatch_id"),
        "lease_id": lease_id,
        "record_summary": res,
    }


def process_ready_tickets(
    brain: ProjectBrain,
    max_tickets: int = 10,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Find and execute ready supervisor tickets up to max_tickets limit."""
    if max_tickets < 1 or max_tickets > 100:
        raise GuardianError("max_tickets must be between 1 and 100.")

    if is_kill_switch_active(brain):
        raise GuardianError("Emergency stop is active; process tickets blocked.")

    tickets = list_ready_tickets(brain, limit=max_tickets)
    executed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for ticket in tickets:
        if is_kill_switch_active(brain):
            break
        try:
            result = execute_ticket(brain, ticket, dry_run=dry_run)
            executed.append(result)
        except (GuardianError, OSError, json.JSONDecodeError, ValueError) as err:
            clean_err = redact_secrets(brain, str(err))
            errors.append({
                "ticket_id": ticket.get("stage_id"),
                "error": clean_err,
            })

    return {
        "tickets_inspected": len(tickets),
        "executed_count": len(executed),
        "error_count": len(errors),
        "executed": executed,
        "errors": errors,
    }
