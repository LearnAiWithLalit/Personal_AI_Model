"""Persistent evidence ledger for systematic root-cause debugging."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, markdown_escape, now_utc


def debug_dir(brain: ProjectBrain) -> Path:
    path = brain.directory / "tasks" / "debug"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _case_path(brain: ProjectBrain, case_id: str) -> Path:
    clean = markdown_escape(case_id)
    if not clean.startswith("dbg-") or not all(char.isalnum() or char == "-" for char in clean):
        raise GuardianError("Invalid debugging case ID.")
    return debug_dir(brain) / f"{clean}.json"


def start_debug_case(brain: ProjectBrain, symptom: str, reproduction: str) -> dict:
    if not symptom.strip() or not reproduction.strip():
        raise GuardianError("Debugging requires both a symptom and reproduction evidence.")
    case_id = f"dbg-{uuid.uuid4().hex[:8]}"
    record = {
        "id": case_id,
        "symptom": markdown_escape(symptom),
        "reproduction": markdown_escape(reproduction),
        "state": "root_cause_investigation",
        "hypotheses": [],
        "attempts": [],
        "failed_attempts": 0,
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    _case_path(brain, case_id).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    append_journey(brain, f"Debug Case Started: {case_id}", [f"Symptom: {record['symptom']}"])
    return record


def load_debug_case(brain: ProjectBrain, case_id: str) -> dict:
    path = _case_path(brain, case_id)
    if not path.is_file():
        raise GuardianError(f"Debugging case {case_id!r} was not found.")
    return json.loads(path.read_text(encoding="utf-8"))


def _save(brain: ProjectBrain, record: dict) -> None:
    record["updated_at"] = now_utc()
    _case_path(brain, record["id"]).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def add_debug_hypothesis(brain: ProjectBrain, case_id: str, hypothesis: str, evidence: str) -> dict:
    record = load_debug_case(brain, case_id)
    if record["state"] == "architecture_review_required":
        raise GuardianError("Three fixes failed; architecture review is required before another hypothesis.")
    if not hypothesis.strip() or not evidence.strip():
        raise GuardianError("A hypothesis must state both the theory and supporting evidence.")
    record["hypotheses"].append(
        {"hypothesis": markdown_escape(hypothesis), "evidence": markdown_escape(evidence), "recorded_at": now_utc()}
    )
    record["state"] = "hypothesis_testing"
    _save(brain, record)
    return record


def record_debug_attempt(
    brain: ProjectBrain,
    case_id: str,
    change: str,
    command: str,
    passed: bool,
    evidence: str,
) -> dict:
    record = load_debug_case(brain, case_id)
    if not record["hypotheses"]:
        raise GuardianError("Record a root-cause hypothesis before attempting a fix.")
    if record["state"] == "architecture_review_required":
        raise GuardianError("Architecture review is required before another fix attempt.")
    record["attempts"].append(
        {
            "change": markdown_escape(change),
            "command": markdown_escape(command),
            "passed": bool(passed),
            "evidence": markdown_escape(evidence),
            "recorded_at": now_utc(),
        }
    )
    if passed:
        record["state"] = "resolved_pending_verification"
    else:
        record["failed_attempts"] += 1
        record["state"] = (
            "architecture_review_required"
            if record["failed_attempts"] >= 3
            else "root_cause_investigation"
        )
    _save(brain, record)
    append_journey(
        brain,
        f"Debug Attempt Recorded: {case_id}",
        [f"Outcome: {'passed' if passed else 'failed'}", f"State: {record['state']}"],
    )
    return record
