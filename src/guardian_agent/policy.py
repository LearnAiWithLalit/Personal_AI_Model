"""Policy-as-Code Engine & Approval Queue (Phase 5 Hardened).

Provides policy evaluation, permission boundary checks, approval queue management,
two-stage approval reservation (pending -> approved -> reserved(token) -> consumed | unknown_outcome),
atomic queue locking, evidence tracking, strict scope verification, and human checkpoint enforcement.
"""

from __future__ import annotations

import fcntl
import json
import os
import uuid
from pathlib import Path
from typing import Any

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, markdown_escape, now_utc
from guardian_agent.security_url import sanitize_url_for_audit


POLICY_FILE = "policy.json"
APPROVAL_QUEUE_FILE = "approval_queue.jsonl"

_SENSITIVE_ACTIONS = {
    "submit_payment",
    "delete_file",
    "irreversible_git_push",
    "create_external_account",
    "browser_submit",
    "browser_publish",
    "browser_purchase",
    "browser_delete",
    "browser_create_account",
    "browser_accept_terms",
    "browser_identity_verification",
    "browser_fill_credential",
    "accept_legal_terms",
    "identity_verification",
    "captcha_or_mfa_bypass",
}


def default_policy() -> dict:
    return {
        "version": "1.0.0",
        "policy": {
            "allow_local_read": True,
            "allow_local_write": True,
            "allow_local_cmd": True,
            "allow_free_providers": True,
            "allow_paid_providers": False,
            "require_approval_for": sorted(list(_SENSITIVE_ACTIONS) + [
                "mcp_trust_server",
                "mcp_write_tool",
                "workflow_design_approval",
                "workflow_final_approval",
                "skill_import_accept",
                "skill_generated_promote",
                "runtime_resume",
                "learning_export",
                "learning_delete",
            ]),
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


def _lock_file_path(brain: ProjectBrain) -> Path:
    audit_d = brain.directory / "audit"
    audit_d.mkdir(exist_ok=True)
    return audit_d / "approval_queue.lock"


def load_approval_queue(brain: ProjectBrain) -> list[dict[str, Any]]:
    p = approval_queue_path(brain)
    if not p.is_file():
        return []
    entries = []
    lock_path = _lock_file_path(brain)
    with open(lock_path, "a", encoding="utf-8") as lock_fd:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_SH)
        try:
            with open(p, "r", encoding="utf-8") as h:
                for line in h.read().splitlines():
                    if line.strip():
                        try:
                            entries.append(json.loads(line))
                        except Exception:
                            pass
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
    return entries


def _validate_approval_scope(
    request: dict[str, Any],
    action: str,
    target: str,
    *,
    user_id: str | None = None,
    account_id: str | None = None,
    connector_scope: str | None = None,
    idempotency_key: str | None = None,
    reservation_token: str | None = None,
    require_token: bool = False,
) -> None:
    """Shared exact-scope validator used by reservation and consumption."""
    clean_action = markdown_escape(action)
    clean_target = sanitize_url_for_audit(target)
    is_sensitive = clean_action in _SENSITIVE_ACTIONS

    # Action validation
    if request.get("action") != clean_action:
        raise GuardianError(
            f"Approval action mismatch: expected {clean_action!r}, got {request.get('action')!r}."
        )

    # Target validation
    req_canonical = request.get("canonical_target") or sanitize_url_for_audit(request.get("target", ""))
    if req_canonical and req_canonical != clean_target and request.get("target") != target:
        raise GuardianError(
            f"Approval target mismatch: approval was granted for target {req_canonical!r}, "
            f"cannot be used for target {clean_target!r}."
        )

    # Expiry validation
    expires_at = request.get("expires_at")
    if expires_at and expires_at <= now_utc():
        raise GuardianError(f"Approval request {request.get('id')!r} has expired.")

    # Scope validation
    req_user = request.get("user_id")
    req_acc = request.get("account_id")
    req_scope = request.get("connector_scope")

    eff_user = user_id or "user_default"

    if is_sensitive:
        if not req_user or req_user != eff_user:
            raise GuardianError(
                f"Security violation: approval {request.get('id')!r} lacks or has mismatched mandatory user_id scope for sensitive action {clean_action!r}."
            )
        if (account_id or req_acc) and (not req_acc or not account_id or req_acc != account_id):
            raise GuardianError(
                f"Security violation: approval {request.get('id')!r} lacks or has mismatched mandatory account_id scope for sensitive action {clean_action!r}."
            )
        if (connector_scope or req_scope) and (not req_scope or not connector_scope or req_scope != connector_scope):
            raise GuardianError(
                f"Security violation: approval {request.get('id')!r} lacks or has mismatched mandatory connector_scope for sensitive action {clean_action!r}."
            )

    else:
        if user_id and req_user and req_user != eff_user:
            raise GuardianError(f"Approval user ID mismatch: expected {eff_user!r}, got {req_user!r}.")

        if account_id and req_acc and req_acc != account_id:
            raise GuardianError(f"Approval account ID mismatch: expected {account_id!r}, got {req_acc!r}.")
        if connector_scope and req_scope and req_scope != connector_scope:
            raise GuardianError(f"Approval connector scope mismatch: expected {connector_scope!r}, got {req_scope!r}.")

    # Idempotency key validation
    req_idem = request.get("idempotency_key")
    if idempotency_key and req_idem and req_idem != idempotency_key:
        raise GuardianError(f"Approval idempotency key mismatch: expected {idempotency_key!r}, got {req_idem!r}.")

    # Token validation
    if require_token:
        stored_token = request.get("reservation_token")
        if not reservation_token or not stored_token or stored_token != reservation_token:
            raise GuardianError(
                f"Security violation: reserved approval {request.get('id')!r} requires a valid matching reservation token to be processed."
            )


def request_action_approval(
    brain: ProjectBrain,
    action: str,
    target: str,
    reason: str,
    *,
    user_id: str = "user_default",
    account_id: str | None = None,
    connector_scope: str | None = None,
    idempotency_key: str | None = None,
    before_evidence: str | None = None,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Request approval with user identity, connector scope, idempotency, evidence, and atomic locking."""
    clean_act = markdown_escape(action)
    clean_tgt = sanitize_url_for_audit(target)
    clean_rsn = markdown_escape(reason)

    req_id = f"req-{uuid.uuid4().hex[:8]}"
    entry = {
        "id": req_id,
        "timestamp": now_utc(),
        "expires_at": expires_at,
        "user_id": user_id,
        "account_id": account_id,
        "connector_scope": connector_scope,
        "action": clean_act,
        "target": target,
        "canonical_target": clean_tgt,
        "reason": clean_rsn,
        "idempotency_key": idempotency_key or req_id,
        "before_evidence": before_evidence,
        "after_evidence": None,
        "reservation_token": None,
        "status": "pending",
    }

    lock_path = _lock_file_path(brain)
    with open(lock_path, "a", encoding="utf-8") as lock_fd:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        try:
            q_path = approval_queue_path(brain)
            with open(q_path, "a", encoding="utf-8") as h:
                h.write(json.dumps(entry) + "\n")
                h.flush()
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)

    append_journey(brain, f"Approval Requested: {clean_act}", [f"Target: {clean_tgt}", f"User: {user_id}"])
    return entry


def approve_action_request(brain: ProjectBrain, request_id: str) -> dict[str, Any]:
    """Approve a pending action request under exclusive queue lock with atomic rewrite.

    Guarantees one-time approval lifecycle: only 'pending' requests can be approved.
    """
    lock_path = _lock_file_path(brain)
    with open(lock_path, "a", encoding="utf-8") as lock_fd:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        try:
            q_path = approval_queue_path(brain)
            entries = _read_queue_entries(q_path)
            req = next((e for e in entries if e["id"] == request_id), None)
            if not req:
                raise GuardianError(f"Approval request {request_id!r} not found.")

            if req.get("status") != "pending":
                raise GuardianError(
                    f"Approval request {request_id!r} is in status {req.get('status')!r}, not 'pending'. "
                    "Cannot re-approve an already processed or consumed request."
                )

            req["status"] = "approved"
            req["approved_at"] = now_utc()

            _rewrite_queue_under_lock(q_path, entries)
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)

    append_journey(brain, f"Action Approved: {req['action']}", [f"Request ID: {request_id}"])
    return req


def reserve_action_approval(
    brain: ProjectBrain,
    request_id: str,
    action: str,
    target: str,
    *,
    user_id: str | None = None,
    account_id: str | None = None,
    connector_scope: str | None = None,
    idempotency_key: str | None = None,
    reservation_token: str | None = None,
) -> dict[str, Any]:
    """Atomically validate and reserve an approval BEFORE side effect execution (Stage 1 pre-click lock).

    Generates a secret reservation_token. Only an 'approved' request can be reserved.
    """
    lock_path = _lock_file_path(brain)
    with open(lock_path, "a", encoding="utf-8") as lock_fd:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        try:
            q_path = approval_queue_path(brain)
            entries = _read_queue_entries(q_path)
            request = next((entry for entry in entries if entry["id"] == request_id), None)
            if not request:
                raise GuardianError(f"Approval request {request_id!r} not found.")

            st = request.get("status")
            if st == "reserved":
                existing_token = request.get("reservation_token")
                if reservation_token and existing_token == reservation_token:
                    return request
                raise GuardianError(f"Approval request {request_id!r} is already reserved by another process.")

            if st != "approved":
                raise GuardianError(f"Approval request {request_id!r} is in status {st!r}, not 'approved'.")

            _validate_approval_scope(
                request,
                action,
                target,
                user_id=user_id,
                account_id=account_id,
                connector_scope=connector_scope,
                idempotency_key=idempotency_key,
                require_token=False,
            )

            token = f"tok-{uuid.uuid4().hex[:12]}"
            request["status"] = "reserved"
            request["reservation_token"] = token
            request["reserved_at"] = now_utc()
            _rewrite_queue_under_lock(q_path, entries)
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)

    return request


def consume_action_approval(
    brain: ProjectBrain,
    request_id: str,
    action: str,
    target: str,
    after_evidence: str | None = None,
    user_id: str | None = None,
    account_id: str | None = None,
    connector_scope: str | None = None,
    idempotency_key: str | None = None,
    reservation_token: str | None = None,
) -> dict[str, Any]:
    """Consume one approved or reserved request atomically (Stage 2 post-click completion)."""
    clean_action = markdown_escape(action)

    lock_path = _lock_file_path(brain)
    with open(lock_path, "a", encoding="utf-8") as lock_fd:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        try:
            q_path = approval_queue_path(brain)
            entries = _read_queue_entries(q_path)
            request = next((entry for entry in entries if entry["id"] == request_id), None)
            if not request:
                raise GuardianError(f"Approval request {request_id!r} not found.")

            st = request.get("status")
            if st not in ("approved", "reserved"):
                raise GuardianError(f"Approval request {request_id!r} is in status {st!r}, cannot be consumed.")

            _validate_approval_scope(
                request,
                action,
                target,
                user_id=user_id,
                account_id=account_id,
                connector_scope=connector_scope,
                idempotency_key=idempotency_key,
                reservation_token=reservation_token,
                require_token=(st == "reserved"),
            )

            request["status"] = "consumed"
            request["consumed_at"] = now_utc()
            if after_evidence:
                request["after_evidence"] = after_evidence

            _rewrite_queue_under_lock(q_path, entries)
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)

    append_journey(brain, f"Approval Consumed: {clean_action}", [f"Request ID: {request_id}"])
    return request


def mark_approval_unknown_outcome(
    brain: ProjectBrain,
    request_id: str,
    error_reason: str,
    action: str | None = None,
    target: str | None = None,
    reservation_token: str | None = None,
) -> dict[str, Any]:
    """Mark an approval request as unknown_outcome after an interrupted action."""
    lock_path = _lock_file_path(brain)
    with open(lock_path, "a", encoding="utf-8") as lock_fd:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        try:
            q_path = approval_queue_path(brain)
            entries = _read_queue_entries(q_path)
            request = next((entry for entry in entries if entry["id"] == request_id), None)
            if not request:
                raise GuardianError(f"Approval request {request_id!r} not found.")

            st = request.get("status")
            if action and target:
                _validate_approval_scope(
                    request,
                    action,
                    target,
                    reservation_token=reservation_token,
                    require_token=(st == "reserved"),
                )
            elif st == "reserved" and reservation_token and request.get("reservation_token") != reservation_token:
                raise GuardianError(f"Reservation token mismatch for approval request {request_id!r}.")

            request["status"] = "unknown_outcome"
            request["error_reason"] = error_reason
            request["updated_at"] = now_utc()

            _rewrite_queue_under_lock(q_path, entries)
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)

    return request


def _read_queue_entries(q_path: Path) -> list[dict[str, Any]]:
    entries = []
    if q_path.is_file():
        for line in q_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
    return entries


def _rewrite_queue_under_lock(q_path: Path, entries: list[dict[str, Any]]) -> None:
    tmp = q_path.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
    with open(tmp, "w", encoding="utf-8") as fh:
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")
        fh.flush()
    tmp.replace(q_path)
    try:
        os.chmod(q_path, 0o600)
    except OSError:
        pass
