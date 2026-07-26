"""Adaptive development lifecycle with enforced review and evidence gates."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from guardian_agent.coding import run_verification
from guardian_agent.core import GuardianError, ProjectBrain, append_journey, markdown_escape, now_utc
from guardian_agent.policy import consume_action_approval
from guardian_agent.skills import select_builtin_skills


PROFILES = {
    "fast": ["implementation", "verification", "completed"],
    "standard": [
        "design_approval", "planning", "implementation",
        "specification_review", "quality_review", "verification", "completed",
    ],
    "high_assurance": [
        "design_approval", "planning", "implementation",
        "specification_review", "quality_review", "verification",
        "final_approval", "completed",
    ],
}
HIGH_RISK_TERMS = {
    "payment", "billing", "authentication", "authorization", "security", "production",
    "deploy", "migration", "delete", "legal", "identity", "account", "credential",
}
FAST_TERMS = {"readme", "documentation", "typo", "comment", "status", "explain"}


def workflows_dir(brain: ProjectBrain) -> Path:
    path = brain.directory / "tasks" / "workflows"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _workflow_path(brain: ProjectBrain, workflow_id: str) -> Path:
    clean = markdown_escape(workflow_id)
    if not clean.startswith("wf-") or not all(char.isalnum() or char == "-" for char in clean):
        raise GuardianError("Invalid workflow ID.")
    return workflows_dir(brain) / f"{clean}.json"


def assess_profile(request: str, risk: str = "auto") -> dict:
    if risk not in {"auto", "low", "medium", "high"}:
        raise GuardianError("Risk must be auto, low, medium, or high.")
    text = request.lower()
    reasons: list[str] = []
    if risk == "high" or any(term in text for term in HIGH_RISK_TERMS):
        profile = "high_assurance"
        reasons.append("High-impact or security-sensitive language detected.")
    elif risk == "low" or (len(request) < 140 and any(term in text for term in FAST_TERMS)):
        profile = "fast"
        reasons.append("Small, reversible, low-risk task.")
    else:
        profile = "standard"
        reasons.append("Multi-step implementation requires design, review, and verification.")
    return {"profile": profile, "reasons": reasons}


def start_workflow(brain: ProjectBrain, request: str, risk: str = "auto") -> dict:
    clean_request = markdown_escape(request)
    if not clean_request:
        raise GuardianError("A workflow request is required.")
    assessment = assess_profile(clean_request, risk)
    workflow_id = f"wf-{uuid.uuid4().hex[:8]}"
    stages = PROFILES[assessment["profile"]]
    record = {
        "id": workflow_id,
        "request": clean_request,
        "profile": assessment["profile"],
        "profile_reasons": assessment["reasons"],
        "stages": stages,
        "current_stage": stages[0],
        "stage_index": 0,
        "status": "active",
        "selected_skills": select_builtin_skills(clean_request, assessment["profile"]),
        "evidence": [],
        "reviews": {},
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    _workflow_path(brain, workflow_id).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    append_journey(
        brain,
        f"Adaptive Workflow Started: {workflow_id}",
        [f"Profile: {record['profile']}", f"Request: {clean_request}", f"Stage: {record['current_stage']}"],
    )
    return record


def load_workflow(brain: ProjectBrain, workflow_id: str) -> dict:
    path = _workflow_path(brain, workflow_id)
    if not path.is_file():
        raise GuardianError(f"Workflow {workflow_id!r} was not found.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise GuardianError(f"Workflow {workflow_id!r} is corrupted.") from error


def _save_workflow(brain: ProjectBrain, record: dict) -> None:
    record["updated_at"] = now_utc()
    _workflow_path(brain, record["id"]).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def _move_next(brain: ProjectBrain, record: dict, evidence_type: str, detail: str) -> dict:
    record["evidence"].append(
        {"timestamp": now_utc(), "stage": record["current_stage"], "type": evidence_type, "detail": markdown_escape(detail)}
    )
    record["stage_index"] += 1
    record["current_stage"] = record["stages"][record["stage_index"]]
    if record["current_stage"] == "completed":
        record["status"] = "completed"
        record["completed_at"] = now_utc()
    _save_workflow(brain, record)
    return record


def advance_workflow(
    brain: ProjectBrain,
    workflow_id: str,
    evidence: str,
    approval_id: str | None = None,
) -> dict:
    record = load_workflow(brain, workflow_id)
    stage = record["current_stage"]
    if stage in {"specification_review", "quality_review"}:
        raise GuardianError("Review stages must use workflow review so pass/fail findings are retained.")
    if stage == "verification":
        raise GuardianError("Verification must use workflow verify and fresh command evidence.")
    if stage == "completed":
        raise GuardianError("Workflow is already completed.")
    approval_action = {
        "design_approval": "workflow_design_approval",
        "final_approval": "workflow_final_approval",
    }.get(stage)
    if approval_action:
        if not approval_id:
            raise GuardianError(f"{stage} requires a one-time {approval_action} approval for {workflow_id}.")
        consume_action_approval(brain, approval_id, approval_action, workflow_id)
    return _move_next(brain, record, "stage_evidence", evidence)


def record_workflow_review(
    brain: ProjectBrain,
    workflow_id: str,
    review_type: str,
    passed: bool,
    findings: list[str],
) -> dict:
    record = load_workflow(brain, workflow_id)
    expected = {
        "specification": "specification_review",
        "quality": "quality_review",
    }.get(review_type)
    if not expected:
        raise GuardianError("Review type must be specification or quality.")
    if record["current_stage"] != expected:
        raise GuardianError(f"Workflow is at {record['current_stage']!r}, not {expected!r}.")
    clean_findings = [markdown_escape(item) for item in findings if markdown_escape(item)]
    record["reviews"][review_type] = {
        "passed": bool(passed), "findings": clean_findings, "reviewed_at": now_utc(),
    }
    if not passed:
        record["status"] = "blocked"
        _save_workflow(brain, record)
        return record
    record["status"] = "active"
    return _move_next(brain, record, f"{review_type}_review", "; ".join(clean_findings) or "Passed with no findings.")


def verify_workflow(brain: ProjectBrain, workflow_id: str, command: str) -> dict:
    record = load_workflow(brain, workflow_id)
    if record["current_stage"] != "verification":
        raise GuardianError(f"Workflow is at {record['current_stage']!r}, not verification.")
    result = run_verification(brain.root, command)
    record["verification"] = {**result, "command": command, "verified_at": now_utc()}
    if not result["success"]:
        record["status"] = "blocked"
        _save_workflow(brain, record)
        return record
    record["status"] = "active"
    return _move_next(
        brain, record, "fresh_verification",
        f"Command: {command}; exit code: {result['exit_code']}",
    )
