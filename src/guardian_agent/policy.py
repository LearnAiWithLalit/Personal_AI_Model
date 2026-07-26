"""Policy-as-Code Engine & Approval Queue (Phase G0).

Provides policy evaluation, permission boundary checks, approval queue management,
and human checkpoint enforcement for sensitive or irreversible actions.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc, markdown_escape


POLICY_FILE = "policy.json"
APPROVAL_QUEUE_FILE = "approval_queue.jsonl"


def default_policy() -> dict:
    return {
        "version": "1.0.0",
        "policy": {
            "allow_local_read": True,
            "allow_local_write": True,
            "allow_local_cmd": True,
            "allow_free_providers": True,
            "allow_paid_providers": False,
            "require_approval_for": [
                "submit_payment",
                "delete_file",
                "irreversible_git_push",
                "create_external_account",
                "browser_submit",
                "accept_legal_terms",
                "identity_verification",
                "captcha_or_mfa_bypass",
            ],
        },
    }


def policy_path(brain: ProjectBrain) -> Path:
    return brain.directory / POLICY_FILE


def get_policy(brain: ProjectBrain) -> dict:
    p = policy_path(brain)
    if not p.is_file():
        p.write_text(json.dumps(default_policy(), indent=2) + "\n", encoding="utf-8")
        return default_policy()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default_policy()


def check_policy_permission(brain: ProjectBrain, action: str, target: str) -> str:
    clean_action = markdown_escape(action)
    policy_data = get_policy(brain)["policy"]
    
    requires_approval = policy_data.get("require_approval_for", [])
    if clean_action in requires_approval:
        return "requires_approval"
        
    return "permitted"


def approval_queue_path(brain: ProjectBrain) -> Path:
    audit_d = brain.directory / "audit"
    audit_d.mkdir(exist_ok=True)
    return audit_d / APPROVAL_QUEUE_FILE


def request_action_approval(
    brain: ProjectBrain,
    action: str,
    target: str,
    reason: str,
) -> dict:
    clean_act = markdown_escape(action)
    clean_tgt = markdown_escape(target)
    clean_rsn = markdown_escape(reason)
    
    req_id = f"req-{uuid.uuid4().hex[:8]}"
    entry = {
        "id": req_id,
        "timestamp": now_utc(),
        "action": clean_act,
        "target": clean_tgt,
        "reason": clean_rsn,
        "status": "pending",
    }
    
    with approval_queue_path(brain).open("a", encoding="utf-8") as h:
        h.write(json.dumps(entry) + "\n")
        
    append_journey(brain, f"Approval Requested: {clean_act}", [f"Target: {clean_tgt}", f"Reason: {clean_rsn}"])
    return entry


def load_approval_queue(brain: ProjectBrain) -> list[dict]:
    p = approval_queue_path(brain)
    if not p.is_file():
        return []
    entries = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
    return entries


def approve_action_request(brain: ProjectBrain, request_id: str) -> dict:
    entries = load_approval_queue(brain)
    req = next((e for e in entries if e["id"] == request_id), None)
    if not req:
        raise GuardianError(f"Approval request {request_id!r} not found.")
        
    req["status"] = "approved"
    req["approved_at"] = now_utc()
    
    # Write back full queue
    with approval_queue_path(brain).open("w", encoding="utf-8") as h:
        for e in entries:
            h.write(json.dumps(e) + "\n")
            
    append_journey(brain, f"Action Approved: {req['action']}", [f"Request ID: {request_id}"])
    return req


def consume_action_approval(brain: ProjectBrain, request_id: str, action: str, target: str) -> dict:
    """Consume one approved request for its exact action and target."""
    entries = load_approval_queue(brain)
    request = next((entry for entry in entries if entry["id"] == request_id), None)
    if not request:
        raise GuardianError(f"Approval request {request_id!r} not found.")
    clean_action = markdown_escape(action)
    clean_target = markdown_escape(target)
    if request.get("status") != "approved":
        raise GuardianError(f"Approval request {request_id!r} is not approved.")
    if request.get("action") != clean_action or request.get("target") != clean_target:
        raise GuardianError("Approval request does not match this action and target.")
    request["status"] = "consumed"
    request["consumed_at"] = now_utc()
    with approval_queue_path(brain).open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")
    append_journey(brain, f"Approval Consumed: {clean_action}", [f"Request ID: {request_id}"])
    return request
