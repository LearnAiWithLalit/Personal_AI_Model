"""Two-Layer Quality Assurance (QA) Pipeline Engine (Phase 8).

Implements QA1 compact evaluation payload formatting, QA1 result schema validation
(clear, flagged, uncertain, failed_tests, security_sensitive), and QA2 conditional
OmniRoute escalation criteria.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from guardian_agent.core import GuardianError, ProjectBrain, now_utc

VALID_QA1_STATUSES = {
    "clear",
    "flagged",
    "uncertain",
    "failed_tests",
    "security_sensitive",
}


def build_qa1_payload(
    brain: ProjectBrain,
    task: str,
    diff_text: str = "",
    test_results: dict[str, Any] | None = None,
    acceptance_criteria: list[str] | None = None,
    risks: list[str] | None = None,
) -> dict[str, Any]:
    """Build a compact, secret-safe QA1 evaluation payload for Gemini/Nemotron free routes."""
    clean_diff = str(diff_text or "").strip()[:5000]
    clean_tests = test_results or {"passed": 0, "failed": 0, "output": "No test output provided"}

    return {
        "task": str(task or "").strip()[:500],
        "diff_snippet": clean_diff,
        "test_results": clean_tests,
        "acceptance_criteria": acceptance_criteria or ["All code must compile cleanly", "All unit tests must pass"],
        "risks": risks or ["Potential security boundary changes", "Path control locks"],
        "created_at": now_utc(),
    }


def evaluate_qa1_result(result_data: dict[str, Any]) -> dict[str, Any]:
    """Validate QA1 result schema against allowed status values."""
    if not isinstance(result_data, dict):
        raise GuardianError("Invalid QA1 result format: expected a dictionary.")

    status = str(result_data.get("status", "")).lower().strip()
    if status not in VALID_QA1_STATUSES:
        raise GuardianError(
            f"Invalid QA1 status {status!r}. Must be one of: {', '.join(sorted(VALID_QA1_STATUSES))}."
        )

    return {
        "status": status,
        "summary": str(result_data.get("summary", "")).strip()[:1000],
        "flagged_issues": list(result_data.get("flagged_issues", [])),
        "evaluated_at": now_utc(),
    }


def should_escalate_to_qa2(qa1_result: dict[str, Any]) -> bool:
    """Return True if QA1 outcome requires QA2 escalation to strong OmniRoute route.

    Only 'clear' QA1 outcomes skip QA2. Any flagged, uncertain, failed_tests, or
    security_sensitive outcome escalates to QA2.
    """
    clean_eval = evaluate_qa1_result(qa1_result)
    status = clean_eval["status"]
    return status != "clear"
