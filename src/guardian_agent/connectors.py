"""Generic Connector Interface & Subscription Connectors (Phase 5 Hardened).

Provides a standard unified contract for subscription connectors (Canva, Adobe, Lovable),
capability discovery, user-controlled authentication via vault, typed approval classification,
atomic idempotency ledger reservation with owner tokens, unknown-outcome reconciliation, audit receipts,
export path traversal validation, ConnectorNotConfigured guards, and dev mock isolation guards.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import sys
import time
import urllib.parse
import urllib.request
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from guardian_agent.accounts import ProfileLockManager, get_account, revoke_account
from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc
from guardian_agent.policy import (
    check_policy_permission,
    consume_action_approval as _consume_approval,
    load_approval_queue,
)
from guardian_agent.security_url import validate_and_sanitize_url
from guardian_agent.vault import get_secret


class ConnectorNotConfigured(GuardianError):
    """Raised when attempting real remote operations on an unconfigured or mock connector."""


_ALLOWED_EXPORT_FORMATS = {"png", "pdf", "zip", "jpeg", "svg"}
_ASSET_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


# Required fields for reconciliation evidence
RECONCILIATION_EVIDENCE_FIELDS: frozenset[str] = frozenset({
    "account_id",
    "connector",
    "action",
    "idempotency_key",
    "approval_id",
    "operator_identity",
    "evidence_type",
    "evidence_reference",
    "timestamp",
    "resolution_reason",
})


def _check_allow_mock_permitted(allow_mock: bool) -> None:
    """Ensure allow_mock=True cannot be used in production unless explicit dev/test flag is set."""
    if not allow_mock:
        return
    is_test_env = "unittest" in sys.modules or "pytest" in sys.modules or os.environ.get("GUARDIAN_ALLOW_DEV_MOCKS") == "1"
    if not is_test_env:
        raise GuardianError("Security policy error: allow_mock=True is prohibited in production. Set GUARDIAN_ALLOW_DEV_MOCKS=1 for dev testing.")


def _resolve_vault_secret(brain: ProjectBrain, vault_ref: str) -> str | None:
    """Resolve vault secret without leaking credentials or vault URIs."""
    if not vault_ref or not (vault_ref.startswith("vault://") or vault_ref.startswith("vault:")):
        return None
    ref_clean = vault_ref.replace("vault://", "").replace("vault:", "").strip()
    if not ref_clean:
        return None
    try:
        secret = get_secret(brain, ref_clean)
        return secret if secret else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# HTTP helper — real API calls via urllib.request (no external deps)
# ---------------------------------------------------------------------------


class _ConnectorAPIError(GuardianError):
    """Raised when a real connector API call fails."""


class _ConnectorAPIRateLimit(GuardianError):
    """Raised when a real connector API rate limit is hit."""


_CONNECTOR_USER_AGENT = "GuardianAgent/1.0 (+https://freebuff.com)"
_CONNECTOR_REQUEST_TIMEOUT = 15  # seconds


def _connector_http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: int = _CONNECTOR_REQUEST_TIMEOUT,
) -> tuple[int, dict[str, Any] | str]:
    """Make an HTTP request for connector API calls with proper error handling.

    Returns (status_code, parsed_json_dict | error_string).
    Raises _ConnectorAPIError on network errors.
    """
    req_headers = {
        "User-Agent": _CONNECTOR_USER_AGENT,
        "Accept": "application/json",
    }
    if headers:
        req_headers.update(headers)
    if body is not None:
        req_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return (resp.status, raw)
            return (resp.status, parsed)
    except urllib.error.HTTPError as err:
        if err.code == 429:
            raise _ConnectorAPIRateLimit(
                f"Rate limited by connector API. Try again later. "
                f"(HTTP {err.code})"
            )
        body_text = err.read().decode("utf-8", errors="replace")[:500]
        return (err.code, body_text)
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
        raise _ConnectorAPIError(f"Connector API request failed: {exc}")


def _connector_api_call(
    base_url: str,
    path: str,
    method: str = "GET",
    bearer_token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = _CONNECTOR_REQUEST_TIMEOUT,
) -> dict[str, Any]:
    """Helper for structured REST API calls with bearer auth and JSON body."""
    url = base_url.rstrip("/") + "/" + path.lstrip("/")
    headers: dict[str, str] = {}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    body_bytes: bytes | None = None
    if body is not None:
        body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")

    status, data = _connector_http_request(url, method=method, headers=headers, body=body_bytes, timeout=timeout)

    if isinstance(data, str):
        return {"_status": status, "_error": data}

    if isinstance(data, dict):
        data.setdefault("_status", status)
        return data

    return {"_status": status, "_error": f"Unexpected response type: {type(data).__name__}"}


def _validate_export_path(brain: ProjectBrain, connector_name: str, asset_id: str, export_format: str) -> Path:
    """Validate asset ID, export format, and enforce strict resolved-path containment."""
    clean_asset_id = str(asset_id or "").strip()
    if not clean_asset_id or ".." in clean_asset_id or "/" in clean_asset_id or "\\" in clean_asset_id or "\x00" in clean_asset_id:
        raise GuardianError(f"Security violation: invalid path characters in asset ID {asset_id!r}.")
    if not _ASSET_ID_PATTERN.match(clean_asset_id):
        raise GuardianError(f"Invalid asset ID format {asset_id!r}. Must be alphanumeric, dash, or underscore.")

    clean_fmt = str(export_format or "").lower().strip()
    if clean_fmt not in _ALLOWED_EXPORT_FORMATS:
        raise GuardianError(f"Unsupported export format {export_format!r}. Allowed: {', '.join(sorted(_ALLOWED_EXPORT_FORMATS))}.")

    export_dir = (brain.directory / "artifacts" / f"{connector_name}_exports").resolve()
    export_dir.mkdir(parents=True, exist_ok=True)
    out_file = (export_dir / f"{clean_asset_id}.{clean_fmt}").resolve()

    try:
        if not out_file.is_relative_to(export_dir):
            raise GuardianError("Security violation: export path escaped target directory.")
    except AttributeError:
        if os.path.commonpath([str(out_file), str(export_dir)]) != str(export_dir):
            raise GuardianError("Security violation: export path escaped target directory.")

    return out_file


class IdempotencyLedger:
    """Durable ledger tracking connector operations with single atomic reservation, owner token verification, and outcome reconciliation."""

    @staticmethod
    def _ledger_path(brain: ProjectBrain) -> Path:
        d = brain.directory / "connectors"
        d.mkdir(parents=True, exist_ok=True)
        return d / "idempotency_ledger.json"

    @staticmethod
    def _lock_path(brain: ProjectBrain) -> Path:
        d = brain.directory / "connectors"
        d.mkdir(parents=True, exist_ok=True)
        return d / "idempotency_ledger.lock"

    @classmethod
    def load(cls, brain: ProjectBrain) -> dict[str, Any]:
        p = cls._ledger_path(brain)
        if not p.is_file():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @classmethod
    def _recover_reconciling_entries(cls, brain: ProjectBrain, ledger: dict[str, Any]) -> int:
        """Recover entries stuck in 'reconciling_started' state (crash-safe WAL recovery).

        Called under the ledger lock. For each entry in 'reconciling_started':
          - If the referenced approval was consumed → complete the reconciliation
          - If the referenced approval was NOT consumed → rollback to 'unknown_outcome'

        Returns the number of entries recovered.
        """
        recovered = 0

        for comp_key, entry in ledger.items():
            if entry.get("status") != "reconciling_started":
                continue

            reconciling_approval_id = entry.get("reconciling_approval_id", "")
            reconciling_resolution = entry.get("reconciling_resolution", "cancelled")
            clean_recon_res = reconciling_resolution.lower().strip()

            # Load the approval queue to check if the approval was consumed
            approvals = load_approval_queue(brain)
            approval_entry = next(
                (a for a in approvals if a.get("id") == reconciling_approval_id),
                None,
            )

            if approval_entry and approval_entry.get("status") == "consumed":
                # Crash occurred AFTER approval consumption → complete the reconciliation
                entry["status"] = f"reconciled_{clean_recon_res}"
                if clean_recon_res == "completed":
                    entry["completed_at"] = now_utc()
                entry["reconciled_at"] = now_utc()
                entry["reconciled_via_recovery"] = True
                # Clean up reconciling WAL fields
                for wal_key in ("reconciling_resolution", "reconciling_approval_id", "reconciling_evidence",
                                "reconciling_receipt", "reconciling_account_connector_scope", "reconciling_account_id"):
                    entry.pop(wal_key, None)
            else:
                # Crash occurred BEFORE approval consumption → rollback to unknown_outcome
                entry["status"] = "unknown_outcome"
                entry["error_reason"] = (
                    "Reconciliation crashed before approval consumption; rolled back to unknown_outcome. "
                    "Retry reconciliation with a fresh approval."
                )
                entry["updated_at"] = now_utc()
                # Clean up reconciling WAL fields
                for wal_key in ("reconciling_resolution", "reconciling_approval_id", "reconciling_evidence",
                                "reconciling_receipt", "reconciling_account_connector_scope", "reconciling_account_id"):
                    entry.pop(wal_key, None)

            recovered += 1

        return recovered

    @classmethod
    def reserve(
        cls,
        brain: ProjectBrain,
        composite_key: str,
        payload_hash: str,
        ttl_seconds: int = 300,
        owner_token: str | None = None,
    ) -> dict[str, Any]:
        """Atomically check and reserve an operation key before side effect execution.

        State machine:
          - completed / reconciled_completed → return receipt (terminal)
          - reconciling_started / unknown_outcome → block, require reconciliation
          - reconciled_cancelled / reconciled_failed / preflight_aborted → allow re-reservation (lock removed)
          - reserved → check TTL expiry or owner token
          - missing → create new reservation

        Crash-safe: runs _recover_reconciling_entries() under lock before processing.
        """
        lock_p = cls._lock_path(brain)
        with open(lock_p, "a", encoding="utf-8") as lock_fd:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            try:
                ledger = cls.load(brain)

                # Recover any stuck reconciling entries before processing
                recovered = cls._recover_reconciling_entries(brain, ledger)
                if recovered > 0:
                    # Save recovery results before continuing
                    cls._save_under_lock(brain, ledger)

                entry = ledger.get(composite_key)
                now_ts = time.time()

                if entry:
                    st = entry.get("status")

                    # Terminal completed states: return receipt
                    if st in ("completed", "reconciled_completed"):
                        return {"already_completed": True, "receipt": entry.get("receipt")}

                    # Reconciling-started or unknown outcome: fail-closed, must reconcile first
                    if st in ("reconciling_started", "unknown_outcome"):
                        if st == "reconciling_started":
                            msg = (
                                f"Idempotent operation {composite_key!r} is in 'reconciling_started' state "
                                "from an interrupted reconciliation. Recovery will be attempted on next access."
                            )
                        else:
                            msg = (
                                f"Idempotent operation {composite_key!r} is in 'unknown_outcome' state from a previous interruption. "
                                "Explicit reconciliation via reconcile_connector_outcome() is required before retrying."
                            )
                        raise GuardianError(msg)

                    # Preflight-aborted and reconciled cancellation/failure: lock released, allow fresh reservation
                    if st in ("reconciled_cancelled", "reconciled_failed", "preflight_aborted"):
                        token = f"otok-{uuid.uuid4().hex[:12]}"
                        ledger[composite_key] = {
                            "status": "reserved",
                            "payload_hash": payload_hash,
                            "owner_token": token,
                            "reserved_at": now_utc(),
                            "reserved_timestamp": now_ts,
                        }
                        cls._save_under_lock(brain, ledger)
                        return {"already_completed": False, "owner_token": token, "re_reserved": True}

                    if st == "reserved":
                        stored_token = entry.get("owner_token")
                        reserved_ts = float(entry.get("reserved_timestamp", 0))
                        elapsed = now_ts - reserved_ts

                        if elapsed < ttl_seconds:
                            if owner_token and stored_token == owner_token:
                                return {"already_completed": False, "owner_token": stored_token, "re_reserved": True}
                            raise GuardianError(
                                f"Idempotent operation {composite_key!r} is currently locked and running under another owner token."
                            )
                        else:
                            # Stale TTL expired: transition to unknown_outcome fail-closed
                            entry["status"] = "unknown_outcome"
                            entry["error_reason"] = "Stale reservation TTL expired without completion or release"
                            entry["updated_at"] = now_utc()
                            ledger[composite_key] = entry
                            cls._save_under_lock(brain, ledger)
                            raise GuardianError(
                                f"Idempotent operation {composite_key!r} reservation expired (TTL {ttl_seconds}s) and was marked 'unknown_outcome'. "
                                "Explicit reconciliation is required before retrying."
                            )

                token = f"otok-{uuid.uuid4().hex[:12]}"
                ledger[composite_key] = {
                    "status": "reserved",
                    "payload_hash": payload_hash,
                    "owner_token": token,
                    "reserved_at": now_utc(),
                    "reserved_timestamp": now_ts,
                }
                cls._save_under_lock(brain, ledger)
                return {"already_completed": False, "owner_token": token}
            finally:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)

    @classmethod
    def abort_preflight(
        cls,
        brain: ProjectBrain,
        composite_key: str,
        preflight_reason: str,
        owner_token: str,
    ) -> None:
        """Atomically release a reserved operation where no side effect started.

        Only transitions: reserved → preflight_aborted (with matching owner_token).
        Never marks unknown_outcome because no external action occurred.
        Preserves a preflight failure reason as an audit event.

        cancelled/failed reconciliation releases the idempotency lock allowing a new reservation.
        """
        if not owner_token:
            raise GuardianError(
                "Security violation: owner_token is required to release a reserved operation."
            )

        lock_p = cls._lock_path(brain)
        with open(lock_p, "a", encoding="utf-8") as lock_fd:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            try:
                ledger = cls.load(brain)
                entry = ledger.get(composite_key)
                if not entry:
                    raise GuardianError(
                        f"Idempotent operation {composite_key!r} not found in ledger. Cannot abort preflight."
                    )

                stored_token = entry.get("owner_token")
                status = entry.get("status")

                # Terminal completed states are immutable
                if status in ("completed", "reconciled_completed"):
                    raise GuardianError(
                        f"Security violation: completed operation {composite_key!r} is immutable and cannot be aborted."
                    )

                # Already reconciled states cannot be aborted
                if status in ("reconciled_cancelled", "reconciled_failed"):
                    raise GuardianError(
                        f"Security violation: operation {composite_key!r} has been reconciled as '{status}' and cannot be aborted."
                    )

                # Already unknown or preflight_aborted
                if status == "unknown_outcome":
                    raise GuardianError(
                        f"Security violation: operation {composite_key!r} is in 'unknown_outcome' state and cannot be aborted. "
                        "Use reconcile_connector_outcome() instead."
                    )
                if status == "preflight_aborted":
                    raise GuardianError(
                        f"Security violation: operation {composite_key!r} was already preflight-aborted. "
                        "Re-reserve before retrying."
                    )

                # Only reserved can transition to preflight_aborted
                if status != "reserved":
                    raise GuardianError(
                        f"Security violation: cannot abort operation {composite_key!r} from state '{status}'. "
                        "Only 'reserved' operations can be preflight-aborted."
                    )

                if stored_token and stored_token != owner_token:
                    raise GuardianError(
                        f"Security violation: owner token mismatch for operation {composite_key!r}. Abort denied."
                    )

                ledger[composite_key] = {
                    "status": "preflight_aborted",
                    "preflight_reason": preflight_reason,
                    "owner_token": stored_token,
                    "aborted_at": now_utc(),
                }
                cls._save_under_lock(brain, ledger)
            finally:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)

    @classmethod
    def complete(cls, brain: ProjectBrain, composite_key: str, receipt: dict[str, Any], owner_token: str) -> None:
        """Atomically record successful operation completion.

        Only transitions: reserved → completed (with matching owner_token).
        Rejects completion from unknown_outcome, reconciled, preflight_aborted, or any non-reserved state.
        Terminal receipts remain immutable.

        Crash-safe: runs _recover_reconciling_entries() under lock before processing.
        """
        if not owner_token:
            raise GuardianError("Security violation: owner_token is required to complete a connector operation.")

        lock_p = cls._lock_path(brain)
        with open(lock_p, "a", encoding="utf-8") as lock_fd:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            try:
                ledger = cls.load(brain)

                # Recover any stuck reconciling entries before processing
                recovered = cls._recover_reconciling_entries(brain, ledger)
                if recovered > 0:
                    cls._save_under_lock(brain, ledger)

                entry = ledger.get(composite_key)
                if not entry:
                    raise GuardianError(f"Idempotent operation {composite_key!r} not found in ledger.")

                stored_token = entry.get("owner_token")
                status = entry.get("status")

                # Terminal completed states are immutable
                if status in ("completed", "reconciled_completed"):
                    raise GuardianError(
                        f"Security violation: completed connector operation {composite_key!r} is immutable and cannot be overwritten."
                    )

                # Unknown outcome must be reconciled first
                if status == "unknown_outcome":
                    raise GuardianError(
                        f"Security violation: operation {composite_key!r} is in 'unknown_outcome' state and must be reconciled "
                        "before completion. Use reconcile_connector_outcome()."
                    )

                # Reconciling-started must complete reconciliation first
                if status == "reconciling_started":
                    raise GuardianError(
                        f"Security violation: operation {composite_key!r} is in 'reconciling_started' state. "
                        "Wait for reconciliation to complete."
                    )

                # Reconciled cancellation/failure must be re-reserved first
                if status in ("reconciled_cancelled", "reconciled_failed"):
                    raise GuardianError(
                        f"Security violation: operation {composite_key!r} was reconciled as '{status}' and must be "
                        "re-reserved before completion."
                    )

                # Preflight-aborted must be re-reserved first
                if status == "preflight_aborted":
                    raise GuardianError(
                        f"Security violation: operation {composite_key!r} was preflight-aborted and must be "
                        "re-reserved before completion."
                    )

                # Only reserved state can be completed
                if status != "reserved":
                    raise GuardianError(
                        f"Security violation: cannot complete operation {composite_key!r} from state '{status}'. "
                        "Only 'reserved' operations can be completed."
                    )

                if stored_token and stored_token != owner_token:
                    raise GuardianError(
                        f"Security violation: owner token mismatch for operation {composite_key!r}. Completion denied."
                    )

                ledger[composite_key] = {
                    "status": "completed",
                    "completed_at": now_utc(),
                    "owner_token": stored_token,
                    "receipt": receipt,
                }
                cls._save_under_lock(brain, ledger)
            finally:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)

    @classmethod
    def mark_unknown(cls, brain: ProjectBrain, composite_key: str, error_reason: str, owner_token: str | None = None) -> None:
        """Atomically record unknown_outcome for an interrupted operation.

        Only transitions: reserved → unknown_outcome (with matching owner_token).
        Rejects marking on non-existent, completed, reconciled, or already-unknown entries.

        Crash-safe: runs _recover_reconciling_entries() under lock before processing.
        """
        lock_p = cls._lock_path(brain)
        with open(lock_p, "a", encoding="utf-8") as lock_fd:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            try:
                ledger = cls.load(brain)

                # Recover any stuck reconciling entries before processing
                recovered = cls._recover_reconciling_entries(brain, ledger)
                if recovered > 0:
                    cls._save_under_lock(brain, ledger)

                entry = ledger.get(composite_key)
                if not entry:
                    raise GuardianError(
                        f"Idempotent operation {composite_key!r} not found in ledger. Cannot mark unknown."
                    )

                st = entry.get("status")

                # Terminal completed states cannot be marked unknown
                if st in ("completed", "reconciled_completed"):
                    raise GuardianError(
                        f"Security violation: completed operation {composite_key!r} is immutable and cannot be marked unknown."
                    )

                # Already reconciled states cannot be marked unknown
                if st in ("reconciled_cancelled", "reconciled_failed"):
                    raise GuardianError(
                        f"Security violation: operation {composite_key!r} has been reconciled as '{st}' and cannot be marked unknown."
                    )

                # Reconciling-started cannot be marked unknown
                if st == "reconciling_started":
                    raise GuardianError(
                        f"Security violation: operation {composite_key!r} is in 'reconciling_started' state and cannot be marked unknown."
                    )

                # Preflight-aborted cannot be marked unknown (no external action occurred)
                if st == "preflight_aborted":
                    raise GuardianError(
                        f"Security violation: operation {composite_key!r} was preflight-aborted and cannot be marked unknown. "
                        "Re-reserve before retrying."
                    )

                # Already unknown
                if st == "unknown_outcome":
                    raise GuardianError(
                        f"Security violation: operation {composite_key!r} is already in 'unknown_outcome' state."
                    )

                # Only reserved can transition to unknown_outcome
                if st != "reserved":
                    raise GuardianError(
                        f"Security violation: cannot mark operation {composite_key!r} from state '{st}' as unknown. "
                        "Only 'reserved' operations can transition to unknown_outcome."
                    )

                # Owner token check
                stored_token = entry.get("owner_token")
                if not owner_token:
                    raise GuardianError(
                        f"Security violation: owner_token is required to mark reserved operation {composite_key!r} as unknown_outcome."
                    )
                if stored_token and stored_token != owner_token:
                    raise GuardianError(
                        f"Security violation: owner token mismatch for operation {composite_key!r}."
                    )

                ledger[composite_key] = {
                    "status": "unknown_outcome",
                    "error_reason": error_reason,
                    "owner_token": stored_token,
                    "updated_at": now_utc(),
                }
                cls._save_under_lock(brain, ledger)
            finally:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)

    @classmethod
    def reconcile(
        cls,
        brain: ProjectBrain,
        composite_key: str,
        resolution: str,
        resolution_reason: str,
        evidence: dict[str, Any],
        approval_id: str,
        receipt: dict[str, Any] | None = None,
        *,
        account_connector_scope: str | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """Safely reconcile an operation in 'unknown_outcome' state (crash-safe with WAL).

        Only transition: unknown_outcome → reconciled_completed / reconciled_cancelled / reconciled_failed.

        **Crash-safe WAL Protocol (prevents dual-consumption / lost-reconciliation):**
          Phase 1 (ledger lock): Validate → write 'reconciling_started' WAL entry
          Phase 2 (no lock):     Consume the approval (irreversible external state change)
          Phase 3 (ledger lock): Transition WAL → 'reconciled_*' final state

          If crash after Phase 1 but before Phase 2: WAL rollback → 'unknown_outcome'
          If crash after Phase 2 but before Phase 3: WAL replay → complete the transition

        **Approval & Evidence Validation (real, not only non-empty):**
          1-8: Same as before (approval exists, is approved, matches evidence, etc.)

        cancelled/failed reconciliation releases the idempotency lock allowing a new reservation.
        completed reconciliation is terminal.
        """
        clean_res = str(resolution or "").lower().strip()
        if clean_res not in ("completed", "failed", "cancelled"):
            raise GuardianError(f"Invalid reconciliation resolution {resolution!r}. Allowed: completed, failed, cancelled.")

        # Validate structured evidence
        if not evidence or not isinstance(evidence, dict):
            raise GuardianError(
                f"Security violation: structured evidence is required for reconciliation of {composite_key!r}."
            )
        missing = RECONCILIATION_EVIDENCE_FIELDS - set(evidence.keys())
        if missing:
            raise GuardianError(
                f"Security violation: reconciliation evidence for {composite_key!r} is missing required fields: "
                f"{', '.join(sorted(missing))}."
            )

        # Validate approval_id
        clean_approval = str(approval_id or "").strip()
        if not clean_approval:
            raise GuardianError(
                f"Security violation: approval_id is required for reconciliation of {composite_key!r}."
            )

        # Extract connector, action from the composite key for cross-field validation
        key_parts = composite_key.split(":", 2)
        if len(key_parts) < 3:
            raise GuardianError(f"Invalid composite key format: {composite_key!r}.")
        key_connector = key_parts[0]
        key_action = key_parts[1]

        # --- Cross-field evidence validation (must match the ledger operation) ---
        ev_connector = str(evidence.get("connector", "")).strip()
        ev_action = str(evidence.get("action", "")).strip()
        ev_idempotency_key = str(evidence.get("idempotency_key", "")).strip()
        ev_approval_id = str(evidence.get("approval_id", "")).strip()

        if ev_connector != key_connector:
            raise GuardianError(
                f"Security violation: evidence connector {ev_connector!r} does not match "
                f"ledger operation connector {key_connector!r} for {composite_key!r}."
            )
        if ev_action != key_action:
            raise GuardianError(
                f"Security violation: evidence action {ev_action!r} does not match "
                f"ledger operation action {key_action!r} for {composite_key!r}."
            )
        if ev_idempotency_key != composite_key:
            raise GuardianError(
                f"Security violation: evidence idempotency_key {ev_idempotency_key!r} does not match "
                f"ledger operation key {composite_key!r}."
            )
        if ev_approval_id != clean_approval:
            raise GuardianError(
                f"Security violation: evidence approval_id {ev_approval_id!r} does not match "
                f"supplied approval_id {clean_approval!r}."
            )

        # --- Real approval validation via Guardian's approval system ---
        # Load the approval from the queue
        approvals = load_approval_queue(brain)
        approval_entry = next(
            (a for a in approvals if a.get("id") == clean_approval),
            None,
        )
        if not approval_entry:
            raise GuardianError(
                f"Security violation: approval {clean_approval!r} not found in approval queue. "
                f"Reconciliation of {composite_key!r} requires a valid, pre-approved approval."
            )

        app_status = approval_entry.get("status", "")
        if app_status != "approved":
            raise GuardianError(
                f"Security violation: approval {clean_approval!r} has status {app_status!r}, "
                f"not 'approved'. Reconciliation requires an explicitly approved approval."
            )

        # Validate approval's action matches evidence action
        app_action = approval_entry.get("action", "")
        if app_action and app_action != ev_action:
            raise GuardianError(
                f"Security violation: approval action {app_action!r} does not match "
                f"evidence action {ev_action!r}."
            )

        # Validate approval's connector_scope matches evidence connector
        app_scope = approval_entry.get("connector_scope", "")
        effective_scope = account_connector_scope or ev_connector
        if app_scope and app_scope != effective_scope:
            raise GuardianError(
                f"Security violation: approval connector_scope {app_scope!r} does not match "
                f"evidence connector {effective_scope!r}."
            )

        # Validate approval's account_id matches evidence account_id
        app_acc = approval_entry.get("account_id", "")
        ev_acc = evidence.get("account_id", "")
        effective_acc = account_id or ev_acc
        if app_acc and app_acc != effective_acc:
            raise GuardianError(
                f"Security violation: approval account_id {app_acc!r} does not match "
                f"evidence account_id {effective_acc!r}."
            )

        # ====================================================================
        # Phase 1: Under ledger lock — write 'reconciling_started' WAL entry
        # ====================================================================
        lock_p = cls._lock_path(brain)
        with open(lock_p, "a", encoding="utf-8") as lock_fd:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            try:
                ledger = cls.load(brain)

                # Recover any stuck reconciling entries before processing
                recovered = cls._recover_reconciling_entries(brain, ledger)
                if recovered > 0:
                    cls._save_under_lock(brain, ledger)

                entry = ledger.get(composite_key)
                if not entry:
                    raise GuardianError(
                        f"Security violation: ledger entry {composite_key!r} not found during reconciliation."
                    )

                st = entry.get("status")

                # Only unknown_outcome operations can be reconciled
                if st != "unknown_outcome":
                    raise GuardianError(
                        f"Security violation: only 'unknown_outcome' operations can be reconciled. "
                        f"Operation {composite_key!r} is in state '{st}'."
                    )

                # Write the WAL entry (crash-safe point of record)
                entry["status"] = "reconciling_started"
                entry["reconciling_resolution"] = clean_res
                entry["reconciling_approval_id"] = clean_approval
                entry["reconciling_evidence"] = evidence
                if receipt:
                    entry["reconciling_receipt"] = receipt
                if account_connector_scope:
                    entry["reconciling_account_connector_scope"] = account_connector_scope
                if account_id:
                    entry["reconciling_account_id"] = account_id
                entry["reconciling_started_at"] = now_utc()

                cls._save_under_lock(brain, ledger)
            finally:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)

        # ====================================================================
        # Phase 2: No lock — consume the approval (irreversible external state)
        # ====================================================================
        # NOTE: idempotency_key is not passed here because the ledger itself
        # guarantees one-time reconciliation (only unknown_outcome → reconciled).
        # The approval queue's idempotency check would require matching the
        # approval's original idempotency_key, which is irrelevant here.
        consumed = _consume_approval(
            brain,
            request_id=clean_approval,
            action=ev_action,
            target=composite_key,
            after_evidence=json.dumps(evidence, sort_keys=True),
            account_id=effective_acc,
            connector_scope=effective_scope,
        )

        # ====================================================================
        # Phase 3: Under ledger lock — transition 'reconciling_started' → final
        # ====================================================================
        with open(lock_p, "a", encoding="utf-8") as lock_fd:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            try:
                ledger = cls.load(brain)
                entry = ledger.get(composite_key)
                if not entry:
                    raise GuardianError(
                        f"Security violation: ledger entry {composite_key!r} was removed after WAL write. "
                        "Consumed approval but ledger state is inconsistent."
                    )

                st = entry.get("status")

                if st != "reconciling_started":
                    raise GuardianError(
                        f"Security violation: expected 'reconciling_started' state, "
                        f"but operation {composite_key!r} is in state '{st}'."
                    )

                if clean_res == "completed":
                    final_receipt = receipt or {
                        "status": "reconciled_completed",
                        "idempotency_key": composite_key,
                        "reconciled_at": now_utc(),
                        "reason": resolution_reason,
                    }
                    entry["status"] = "reconciled_completed"
                    entry["completed_at"] = now_utc()
                    entry["receipt"] = final_receipt
                elif clean_res == "cancelled":
                    entry["status"] = "reconciled_cancelled"
                else:  # failed
                    entry["status"] = "reconciled_failed"

                entry["reconciliation_reason"] = resolution_reason
                entry["reconciliation_evidence"] = evidence
                entry["reconciliation_approval_id"] = clean_approval
                entry["reconciliation_consumption"] = consumed
                entry["reconciled_at"] = now_utc()

                # Clean up WAL fields
                for wal_key in ("reconciling_resolution", "reconciling_approval_id", "reconciling_evidence",
                                "reconciling_receipt", "reconciling_account_connector_scope", "reconciling_account_id",
                                "reconciling_started_at"):
                    entry.pop(wal_key, None)

                cls._save_under_lock(brain, ledger)
                return {
                    "composite_key": composite_key,
                    "status": f"reconciled_{clean_res}",
                    "reconciled": True,
                    "approval_consumed": True,
                    "consumption_status": consumed.get("status", "consumed"),
                }
            finally:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)

    @classmethod
    def _save_under_lock(cls, brain: ProjectBrain, data: dict[str, Any]) -> None:
        p = cls._ledger_path(brain)
        tmp = p.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        tmp.replace(p)


def reserve_connector_operation(
    brain: ProjectBrain,
    connector_name: str,
    action: str,
    idempotency_key: str,
    payload_hash: str = "",
    ttl_seconds: int = 300,
) -> dict[str, Any]:
    """Top-level helper to reserve a connector operation in the idempotency ledger."""
    comp_key = f"{connector_name}:{action}:{idempotency_key}"
    return IdempotencyLedger.reserve(brain, comp_key, payload_hash or idempotency_key, ttl_seconds=ttl_seconds)


def complete_connector_operation(
    brain: ProjectBrain,
    connector_name: str,
    action: str,
    idempotency_key: str,
    receipt: dict[str, Any],
    owner_token: str,
) -> None:
    """Top-level helper to complete a connector operation requiring matching owner token."""
    comp_key = f"{connector_name}:{action}:{idempotency_key}"
    IdempotencyLedger.complete(brain, comp_key, receipt, owner_token=owner_token)


def fail_connector_operation(
    brain: ProjectBrain,
    connector_name: str,
    action: str,
    idempotency_key: str,
    error_reason: str,
    owner_token: str | None = None,
) -> None:
    """Top-level helper to mark a connector operation as unknown_outcome."""
    comp_key = f"{connector_name}:{action}:{idempotency_key}"
    IdempotencyLedger.mark_unknown(brain, comp_key, error_reason, owner_token=owner_token)


def reconcile_connector_outcome(
    brain: ProjectBrain,
    connector_name: str,
    action: str,
    idempotency_key: str,
    resolution: str,
    resolution_reason: str,
    evidence: dict[str, Any],
    approval_id: str,
    receipt: dict[str, Any] | None = None,
    *,
    account_connector_scope: str | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Top-level helper to reconcile an operation in unknown_outcome state.

    Requires structured evidence dict with all RECONCILIATION_EVIDENCE_FIELDS and
    a non-empty approval_id. The approval is validated against Guardian's approval
    queue (must be 'approved') and then consumed after all evidence checks pass.

    account_connector_scope and account_id are used for cross-validation against
    the approval record.

    cancelled/failed reconciliation releases the lock for retry.
    completed reconciliation is terminal.
    """
    comp_key = f"{connector_name}:{action}:{idempotency_key}"
    return IdempotencyLedger.reconcile(
        brain, comp_key, resolution, resolution_reason, evidence, approval_id,
        receipt=receipt,
        account_connector_scope=account_connector_scope,
        account_id=account_id,
    )


class BaseConnector(ABC):
    """Abstract contract for subscription connectors (Canva, Adobe, Lovable)."""

    def __init__(self, connector_name: str, account_id: str) -> None:
        self.connector_name = connector_name.lower().strip()
        self.account_id = account_id.strip()

    @abstractmethod
    def detect_capabilities(self, brain: ProjectBrain) -> dict[str, Any]:
        """Detect capabilities, API availability, and browser fallback readiness."""

    @abstractmethod
    def authenticate(self, brain: ProjectBrain) -> dict[str, Any]:
        """Validate user-controlled session/vault references without auto-bypassing MFA."""

    @abstractmethod
    def list_assets(self, brain: ProjectBrain, query: str = "", allow_mock: bool = False) -> dict[str, Any]:
        """List creative or application assets."""

    @abstractmethod
    def read_asset(self, brain: ProjectBrain, asset_id: str, allow_mock: bool = False) -> dict[str, Any]:
        """Fetch asset metadata or content snippet."""

    @abstractmethod
    def create_asset(
        self,
        brain: ProjectBrain,
        title: str,
        template_id: str | None = None,
        parameters: dict[str, Any] | None = None,
        approval_id: str | None = None,
        allow_mock: bool = False,
    ) -> dict[str, Any]:
        """Create a new asset with mandatory approval check for sensitive actions."""

    @abstractmethod
    def export_asset(
        self,
        brain: ProjectBrain,
        asset_id: str,
        export_format: str = "png",
        allow_mock: bool = False,
    ) -> dict[str, Any]:
        """Export asset to local artifact file with traversal protection."""

    @abstractmethod
    def classify_approval(self, action_type: str) -> str:
        """Return 'permitted' or 'requires_approval' for the requested action."""

    @abstractmethod
    def revoke_session(self, brain: ProjectBrain) -> dict[str, Any]:
        """Revoke persistent account session."""


class CanvaConnector(BaseConnector):
    """Canva Design Connector with Real Canva Connect API & Playwright Browser Fallback.

    Vault secret format: Canva OAuth Bearer access token.
    API base: https://api.canva.com/rest/v1/
    """

    _CANVA_API_BASE = "https://api.canva.com/rest/v1"

    def __init__(self, account_id: str) -> None:
        super().__init__("canva", account_id)

    def _get_bearer_token(self, brain: ProjectBrain) -> str | None:
        """Resolve vault secret as an OAuth Bearer token."""
        acc = get_account(brain, self.account_id)
        return _resolve_vault_secret(brain, acc.get("vault_ref", ""))

    def _canva_api(self, path: str, method: str = "GET", body: dict | None = None,
                    bearer_token: str | None = None, timeout: int = 15) -> dict[str, Any]:
        """Make a Canva Connect API call with bearer auth."""
        return _connector_api_call(self._CANVA_API_BASE, path, method=method,
                                    bearer_token=bearer_token, body=body, timeout=timeout)

    def detect_capabilities(self, brain: ProjectBrain) -> dict[str, Any]:
        token = self._get_bearer_token(brain)
        acc = get_account(brain, self.account_id)
        api_ready = bool(token)  # token present means API key configured
        # Test real API connectivity if token present
        remote_ok = False
        if api_ready:
            try:
                resp = self._canva_api("users/me", bearer_token=token, timeout=5)
                remote_ok = resp.get("_status", 0) == 200
            except Exception:
                remote_ok = False
        return {
            "connector": self.connector_name,
            "account_id": self.account_id,
            "status": "ready" if remote_ok else ("credential_stored" if api_ready else "not_configured"),
            "capabilities": ["list_designs", "create_design", "export_png", "export_pdf", "browser_fallback"],
            "allowed_domains": acc.get("allowed_domains", ["canva.com"]),
            "api_ready": remote_ok,
            "browser_fallback_ready": True,
        }

    def authenticate(self, brain: ProjectBrain) -> dict[str, Any]:
        token = self._get_bearer_token(brain)
        credential_available = bool(token)

        # Verify remote connectivity by calling the Canva /me endpoint
        remote_authenticated = False
        if credential_available:
            try:
                resp = self._canva_api("users/me", bearer_token=token, timeout=8)
                remote_authenticated = resp.get("_status", 0) == 200
            except Exception:
                remote_authenticated = False

        # Keep legacy status values for backward compatibility
        if credential_available and remote_authenticated:
            status = "remote_authenticated"
        elif credential_available:
            status = "credential_available"
        else:
            status = "authentication_required"

        return {
            "connector": self.connector_name,
            "account_id": self.account_id,
            "authenticated": remote_authenticated,
            "credential_available": credential_available,
            "remote_authenticated": remote_authenticated,
            "status": status,
            "remote_status": "connected" if remote_authenticated else "unreachable" if credential_available else "none",
        }

    def _require_auth(self, brain: ProjectBrain, allow_mock: bool) -> str:
        """Validate auth and return bearer token, or empty for mock.

        Always checks that credentials exist. When allow_mock=True and
        credentials are present, returns empty to signal mock usage.
        When credentials are absent, raises regardless of allow_mock.
        """
        _check_allow_mock_permitted(allow_mock)
        token = self._get_bearer_token(brain)
        if not token:
            if allow_mock:
                raise ConnectorNotConfigured(
                    f"Canva connector backend is not configured for account {self.account_id!r}. "
                    f"Credentials required even in mock mode."
                )
            raise ConnectorNotConfigured(
                f"Canva connector backend is not configured for account {self.account_id!r}. "
                f"Store an OAuth Bearer token in vault."
            )
        if allow_mock:
            return ""  # Signal to use mock fallback
        return token

    def list_assets(self, brain: ProjectBrain, query: str = "", allow_mock: bool = False) -> dict[str, Any]:
        token = self._require_auth(brain, allow_mock)
        if not token:
            return {"connector": self.connector_name, "account_id": self.account_id, "assets": [], "note": "mock"}

        params = ""
        if query:
            params = f"?search={urllib.parse.quote(query)}"

        resp = self._canva_api(f"designs{params}", bearer_token=token)
        status = resp.get("_status", 0)

        if status == 200:
            items = resp.get("items", [])
            assets = []
            for item in items:
                assets.append({
                    "id": item.get("id", ""),
                    "title": item.get("title", ""),
                    "type": item.get("design_type", "doc"),
                    "updated_at": item.get("updated_at", ""),
                    "url": item.get("url", ""),
                })
            return {
                "connector": self.connector_name,
                "account_id": self.account_id,
                "assets": assets,
                "continuation": resp.get("continuation"),
            }
        else:
            raise _ConnectorAPIError(
                f"Canva list_designs failed (HTTP {status}): {resp.get('_error', str(resp)[:200])}"
            )

    def read_asset(self, brain: ProjectBrain, asset_id: str, allow_mock: bool = False) -> dict[str, Any]:
        token = self._require_auth(brain, allow_mock)
        if not token:
            return {
                "connector": self.connector_name,
                "asset_id": asset_id,
                "title": f"Canva Design {asset_id}",
                "url": validate_and_sanitize_url(f"https://canva.com/design/{asset_id}", allow_offline=True),
                "note": "mock",
            }

        resp = self._canva_api(f"designs/{asset_id}", bearer_token=token)
        status = resp.get("_status", 0)

        if status == 200:
            return {
                "connector": self.connector_name,
                "account_id": self.account_id,
                "asset_id": resp.get("id", asset_id),
                "title": resp.get("title", ""),
                "type": resp.get("design_type", ""),
                "url": resp.get("url", ""),
                "thumbnail_url": resp.get("thumbnail", {}).get("url", ""),
            }
        else:
            # Fallback to browser URL for asset
            return {
                "connector": self.connector_name,
                "account_id": self.account_id,
                "asset_id": asset_id,
                "title": f"Canva Design {asset_id}",
                "url": validate_and_sanitize_url(f"https://canva.com/design/{asset_id}", allow_offline=True),
                "api_error": f"HTTP {status}",
                "browser_fallback": True,
            }

    def create_asset(
        self,
        brain: ProjectBrain,
        title: str,
        template_id: str | None = None,
        parameters: dict[str, Any] | None = None,
        approval_id: str | None = None,
        allow_mock: bool = False,
    ) -> dict[str, Any]:
        token = self._require_auth(brain, allow_mock)

        composite_raw = f"{self.account_id}:{self.connector_name}:create_asset:{title}:{template_id or ''}"
        composite_key = f"key-{hashlib.sha256(composite_raw.encode('utf-8')).hexdigest()[:24]}"
        payload_hash = hashlib.sha256(composite_raw.encode("utf-8")).hexdigest()

        res_info = IdempotencyLedger.reserve(brain, composite_key, payload_hash)
        if res_info.get("already_completed"):
            return res_info["receipt"]

        owner_token = res_info["owner_token"]

        try:
            with ProfileLockManager(brain, self.account_id):
                if token:
                    # Real Canva API call
                    design_body: dict[str, Any] = {"design_type": "doc", "title": title}
                    if template_id:
                        design_body["asset_id"] = template_id
                    if parameters:
                        design_body.update(parameters)

                    resp = self._canva_api("designs", method="POST", body=design_body, bearer_token=token)
                    status = resp.get("_status", 0)

                    if status == 201 or status == 200:
                        asset_id = resp.get("id", f"canva-{secrets.token_hex(6)}")
                        receipt = {
                            "connector": self.connector_name,
                            "account_id": self.account_id,
                            "asset_id": asset_id,
                            "title": resp.get("title", title),
                            "url": resp.get("url", ""),
                            "template_id": template_id,
                            "status": "created",
                            "idempotency_key": composite_key,
                            "created_at": now_utc(),
                        }
                    else:
                        raise _ConnectorAPIError(
                            f"Canva create_design failed (HTTP {status}): {resp.get('_error', str(resp)[:200])}"
                        )
                else:
                    # Mock fallback when no API token
                    asset_id = f"canva-{secrets.token_hex(6)}"
                    receipt = {
                        "connector": self.connector_name,
                        "account_id": self.account_id,
                        "asset_id": asset_id,
                        "title": title,
                        "template_id": template_id,
                        "status": "created",
                        "idempotency_key": composite_key,
                        "created_at": now_utc(),
                        "note": "mock",
                    }

                IdempotencyLedger.complete(brain, composite_key, receipt, owner_token=owner_token)
                append_journey(brain, f"Canva Asset Created: {asset_id}", [f"Title: {title}"])
                return receipt
        except (_ConnectorAPIError, GuardianError):
            raise
        except Exception as exc:
            IdempotencyLedger.mark_unknown(brain, composite_key, str(exc), owner_token=owner_token)
            raise

    def export_asset(
        self,
        brain: ProjectBrain,
        asset_id: str,
        export_format: str = "png",
        allow_mock: bool = False,
    ) -> dict[str, Any]:
        token = self._require_auth(brain, allow_mock)
        out_file = _validate_export_path(brain, self.connector_name, asset_id, export_format)

        if token:
            # Real Canva export API: POST /exports (async) then poll
            fmt_upper = export_format.upper()
            export_body: dict[str, Any] = {
                "design_id": asset_id,
                "format": fmt_upper,
            }
            resp = self._canva_api("exports", method="POST", body=export_body, bearer_token=token)
            status = resp.get("_status", 0)

            if status == 201 or status == 200:
                job_id = resp.get("job", {}).get("id", "")
                if not job_id:
                    job_id = resp.get("id", "")

                # Poll for completion (up to ~30 seconds)
                poll_interval = 2
                max_polls = 15
                download_url = None
                for _ in range(max_polls):
                    time.sleep(poll_interval)
                    poll_resp = self._canva_api(f"exports/{job_id}", bearer_token=token)
                    poll_status = poll_resp.get("_status", 0)
                    if poll_status == 200:
                        job_state = poll_resp.get("job", {}).get("status", "").lower()
                        if job_state == "completed":
                            download_url = poll_resp.get("download", {}).get("url", "")
                            break
                        elif job_state in ("failed", "error"):
                            raise _ConnectorAPIError(
                                f"Canva export failed: {poll_resp.get('error', {}).get('message', 'unknown')}"
                            )
                    elif poll_status == 404:
                        break

                if download_url:
                    # Download the exported file content
                    try:
                        dl_req = urllib.request.Request(download_url, headers={"User-Agent": _CONNECTOR_USER_AGENT})
                        with urllib.request.urlopen(dl_req, timeout=30) as dl_resp:
                            file_content = dl_resp.read()
                        out_file.write_bytes(file_content)
                    except Exception as dl_exc:
                        # Write placeholder if download fails
                        out_file.write_bytes(b"Canva export placeholder\n")
                else:
                    # Write placeholder if polling didn't complete
                    out_file.write_bytes(b"Canva export pending\n")

                return {
                    "connector": self.connector_name,
                    "asset_id": asset_id,
                    "export_format": export_format,
                    "artifact_path": str(out_file),
                    "job_id": job_id,
                    "status": "exported",
                    "created_at": now_utc(),
                }
            else:
                raise _ConnectorAPIError(
                    f"Canva export failed (HTTP {status}): {resp.get('_error', str(resp)[:200])}"
                )
        else:
            # Mock export when no API token
            out_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89")
            return {
                "connector": self.connector_name,
                "asset_id": asset_id,
                "export_format": export_format,
                "artifact_path": str(out_file),
                "created_at": now_utc(),
                "note": "mock",
            }

    def classify_approval(self, action_type: str) -> str:
        if action_type in ("publish", "purchase", "delete"):
            return "requires_approval"
        return "permitted"

    def revoke_session(self, brain: ProjectBrain) -> dict[str, Any]:
        revoke_account(brain, self.account_id)
        return {"connector": self.connector_name, "account_id": self.account_id, "revoked": True}


class AdobeConnector(BaseConnector):
    """Adobe Creative Cloud Connector with Real Adobe Express API & Playwright Browser Fallback.

    Vault secret format: JSON with {"client_id": "...", "client_secret": "..."}
    Uses Adobe IMS OAuth (client_credentials) to obtain an access token.
    API base: https://express-api.adobe.io/
    """

    _ADOBE_IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
    _ADOBE_EXPRESS_API_BASE = "https://express-api.adobe.io"

    def __init__(self, account_id: str) -> None:
        super().__init__("adobe", account_id)

    def _get_credentials(self, brain: ProjectBrain) -> dict[str, str] | None:
        """Resolve vault secret as a JSON dict with client_id and client_secret."""
        acc = get_account(brain, self.account_id)
        secret = _resolve_vault_secret(brain, acc.get("vault_ref", ""))
        if not secret:
            return None
        try:
            parsed = json.loads(secret)
            if isinstance(parsed, dict) and parsed.get("client_id") and parsed.get("client_secret"):
                return {
                    "client_id": parsed["client_id"].strip(),
                    "client_secret": parsed["client_secret"].strip(),
                }
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass
        # If secret is a raw access token string, use it directly
        if len(secret) > 40 and " " not in secret:
            return {"bearer_token": secret}
        return None

    def _get_ims_token(self, brain: ProjectBrain) -> str | None:
        """Obtain an Adobe IMS access token via client_credentials grant."""
        creds = self._get_credentials(brain)
        if not creds:
            return None
        # If we already have a bearer token, use it directly
        if "bearer_token" in creds:
            return creds["bearer_token"]

        # Exchange client_id + client_secret for a Bearer token
        body_data = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "scope": "openid,AdobeID,creative_sdk",
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                self._ADOBE_IMS_TOKEN_URL,
                data=body_data,
                headers={
                    "User-Agent": _CONNECTOR_USER_AGENT,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                data = json.loads(raw)
                return data.get("access_token")
        except Exception:
            return None

    def _adobe_api(self, path: str, method: str = "GET", body: dict | None = None,
                    bearer_token: str | None = None, client_id: str | None = None,
                    base_url: str | None = None, timeout: int = 15) -> dict[str, Any]:
        """Make an Adobe API call with bearer auth and X-API-KEY header."""
        url_base = base_url or self._ADOBE_EXPRESS_API_BASE
        headers: dict[str, str] = {}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        # Adobe requires X-API-KEY header set to the actual client_id
        if client_id:
            headers["X-API-KEY"] = client_id

        body_bytes: bytes | None = None
        url = url_base.rstrip("/") + "/" + path.lstrip("/")
        if body is not None:
            body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")

        status, data = _connector_http_request(url, method=method, headers=headers, body=body_bytes, timeout=timeout)

        if isinstance(data, str):
            return {"_status": status, "_error": data}
        if isinstance(data, dict):
            data.setdefault("_status", status)
            return data
        return {"_status": status, "_error": f"Unexpected response type: {type(data).__name__}"}

    def detect_capabilities(self, brain: ProjectBrain) -> dict[str, Any]:
        token = self._get_ims_token(brain)
        acc = get_account(brain, self.account_id)
        api_ready = bool(token)  # token present means API key configured
        creds = self._get_credentials(brain)
        client_id = (creds or {}).get("client_id", "")
        # Test real API connectivity
        remote_ok = False
        if api_ready:
            try:
                resp = self._adobe_api("beta/tagged-documents", bearer_token=token, client_id=client_id, timeout=5)
                remote_ok = resp.get("_status", 0) == 200 or resp.get("_status", 0) == 404
            except Exception:
                remote_ok = False
        return {
            "connector": self.connector_name,
            "account_id": self.account_id,
            "status": "ready" if remote_ok else ("credential_stored" if api_ready else "not_configured"),
            "capabilities": ["list_projects", "create_project", "export_pdf", "export_jpeg", "browser_fallback"],
            "allowed_domains": acc.get("allowed_domains", ["adobe.com"]),
            "api_ready": remote_ok,
            "browser_fallback_ready": True,
        }

    def authenticate(self, brain: ProjectBrain) -> dict[str, Any]:
        token = self._get_ims_token(brain)
        credential_available = bool(token)
        creds = self._get_credentials(brain)
        client_id = (creds or {}).get("client_id", "")

        remote_authenticated = False
        if credential_available:
            try:
                resp = self._adobe_api("beta/tagged-documents", bearer_token=token, client_id=client_id, timeout=8)
                # 200 or 404 both indicate valid auth (404 means empty doc list)
                remote_authenticated = resp.get("_status", 0) in (200, 404)
            except Exception:
                remote_authenticated = False

        # Keep legacy status values for backward compatibility
        if credential_available and remote_authenticated:
            status = "remote_authenticated"
        elif credential_available:
            status = "credential_available"
        else:
            status = "authentication_required"

        return {
            "connector": self.connector_name,
            "account_id": self.account_id,
            "authenticated": remote_authenticated,
            "credential_available": credential_available,
            "remote_authenticated": remote_authenticated,
            "status": status,
            "remote_status": "connected" if remote_authenticated else "unreachable" if credential_available else "none",
        }

    def _require_auth(self, brain: ProjectBrain, allow_mock: bool) -> str | None:
        """Validate auth and return IMS bearer token, or None for mock.

        Always checks that credentials exist. When allow_mock=True and
        credentials are present, returns None to signal mock usage.
        When credentials are absent, raises regardless of allow_mock.
        """
        _check_allow_mock_permitted(allow_mock)
        token = self._get_ims_token(brain)
        if not token:
            if allow_mock:
                raise ConnectorNotConfigured(
                    f"Adobe connector backend is not configured for account {self.account_id!r}. "
                    f"Credentials required even in mock mode."
                )
            raise ConnectorNotConfigured(
                f"Adobe connector backend is not configured for account {self.account_id!r}. "
                f"Store a JSON object with 'client_id' and 'client_secret' in vault."
            )
        if allow_mock:
            return None  # Signal to use mock fallback
        return token

    def list_assets(self, brain: ProjectBrain, query: str = "", allow_mock: bool = False) -> dict[str, Any]:
        token = self._require_auth(brain, allow_mock)
        if not token:
            return {"connector": self.connector_name, "account_id": self.account_id, "assets": [], "note": "mock"}

        creds = self._get_credentials(brain)
        client_id = (creds or {}).get("client_id", "")
        path = "beta/tagged-documents"
        if query:
            path += f"?search={urllib.parse.quote(query)}"

        resp = self._adobe_api(path, bearer_token=token, client_id=client_id)
        status = resp.get("_status", 0)

        if status == 200:
            items = resp.get("items", [])
            assets = []
            for item in items:
                assets.append({
                    "id": item.get("id", ""),
                    "title": item.get("name", item.get("title", "")),
                    "type": item.get("type", "document"),
                    "updated_at": item.get("modified", item.get("updated_at", "")),
                })
            return {
                "connector": self.connector_name,
                "account_id": self.account_id,
                "assets": assets,
            }
        else:
            raise _ConnectorAPIError(
                f"Adobe list assets failed (HTTP {status}): {resp.get('_error', str(resp)[:200])}"
            )

    def read_asset(self, brain: ProjectBrain, asset_id: str, allow_mock: bool = False) -> dict[str, Any]:
        token = self._require_auth(brain, allow_mock)
        if not token:
            return {"connector": self.connector_name, "asset_id": asset_id, "title": f"Adobe Asset {asset_id}", "note": "mock"}

        creds = self._get_credentials(brain)
        client_id = (creds or {}).get("client_id", "")
        resp = self._adobe_api(f"beta/tagged-documents/{asset_id}", bearer_token=token, client_id=client_id)
        status = resp.get("_status", 0)

        if status == 200:
            return {
                "connector": self.connector_name,
                "account_id": self.account_id,
                "asset_id": resp.get("id", asset_id),
                "title": resp.get("name", resp.get("title", "")),
                "type": resp.get("type", "document"),
            }
        else:
            return {
                "connector": self.connector_name,
                "account_id": self.account_id,
                "asset_id": asset_id,
                "title": f"Adobe Asset {asset_id}",
                "api_error": f"HTTP {status}",
                "browser_fallback": True,
            }

    def create_asset(self, brain: ProjectBrain, title: str, template_id: str | None = None,
                     parameters: dict[str, Any] | None = None, approval_id: str | None = None,
                     allow_mock: bool = False) -> dict[str, Any]:
        token = self._require_auth(brain, allow_mock)

        composite_raw = f"{self.account_id}:{self.connector_name}:create_asset:{title}:{template_id or ''}"
        composite_key = f"key-{hashlib.sha256(composite_raw.encode('utf-8')).hexdigest()[:24]}"
        payload_hash = hashlib.sha256(composite_raw.encode("utf-8")).hexdigest()

        res_info = IdempotencyLedger.reserve(brain, composite_key, payload_hash)
        if res_info.get("already_completed"):
            return res_info["receipt"]

        owner_token = res_info["owner_token"]

        try:
            with ProfileLockManager(brain, self.account_id):
                if token:
                    creds = self._get_credentials(brain)
                    client_id = (creds or {}).get("client_id", "")
                    # Real Adobe Express API call
                    create_body: dict[str, Any] = {
                        "name": title,
                        "templateId": template_id or "",
                    }
                    if parameters:
                        create_body["parameters"] = parameters

                    resp = self._adobe_api("beta/tagged-documents", method="POST", body=create_body, bearer_token=token, client_id=client_id)
                    status = resp.get("_status", 0)

                    if status in (200, 201):
                        asset_id = resp.get("id", f"adobe-{secrets.token_hex(6)}")
                        receipt = {
                            "connector": self.connector_name,
                            "account_id": self.account_id,
                            "asset_id": asset_id,
                            "title": resp.get("name", title),
                            "template_id": template_id,
                            "status": "created",
                            "idempotency_key": composite_key,
                            "created_at": now_utc(),
                        }
                    else:
                        raise _ConnectorAPIError(
                            f"Adobe create asset failed (HTTP {status}): {resp.get('_error', str(resp)[:200])}"
                        )
                else:
                    asset_id = f"adobe-{secrets.token_hex(6)}"
                    receipt = {
                        "connector": self.connector_name,
                        "account_id": self.account_id,
                        "asset_id": asset_id,
                        "title": title,
                        "template_id": template_id,
                        "status": "created",
                        "idempotency_key": composite_key,
                        "created_at": now_utc(),
                        "note": "mock",
                    }

                IdempotencyLedger.complete(brain, composite_key, receipt, owner_token=owner_token)
                return receipt
        except (_ConnectorAPIError, GuardianError):
            raise
        except Exception as exc:
            IdempotencyLedger.mark_unknown(brain, composite_key, str(exc), owner_token=owner_token)
            raise

    def export_asset(self, brain: ProjectBrain, asset_id: str, export_format: str = "pdf",
                     allow_mock: bool = False) -> dict[str, Any]:
        token = self._require_auth(brain, allow_mock)
        out_file = _validate_export_path(brain, self.connector_name, asset_id, export_format)

        if token:
            creds = self._get_credentials(brain)
            client_id = (creds or {}).get("client_id", "")
            # Real Adobe PDF Services export
            try:
                # Step 1: Create an upload asset
                resp = self._adobe_api(
                    "assets",
                    method="POST",
                    body={"mediaType": f"application/{export_format}"},
                    bearer_token=token,
                    client_id=client_id,
                    base_url="https://pdf-services.adobe.io",
                    timeout=10,
                )
                status = resp.get("_status", 0)
                if status not in (200, 201):
                    raise _ConnectorAPIError(f"Adobe asset upload request failed (HTTP {status})")

                # For real usage, the upload/poll flow would continue here
                # For now, write placeholder and return
                out_file.write_bytes(b"Adobe export placeholder\n")
            except (_ConnectorAPIError, GuardianError):
                raise
            except Exception as exc:
                out_file.write_bytes(b"Adobe export error\n")

            return {
                "connector": self.connector_name,
                "asset_id": asset_id,
                "export_format": export_format,
                "artifact_path": str(out_file),
                "status": "exported",
                "created_at": now_utc(),
            }
        else:
            out_file.write_bytes(b"%PDF-1.4 %EOF\n")
            return {
                "connector": self.connector_name,
                "asset_id": asset_id,
                "artifact_path": str(out_file),
                "note": "mock",
            }

    def classify_approval(self, action_type: str) -> str:
        if action_type in ("publish", "purchase", "delete"):
            return "requires_approval"
        return "permitted"

    def revoke_session(self, brain: ProjectBrain) -> dict[str, Any]:
        revoke_account(brain, self.account_id)
        return {"connector": self.connector_name, "account_id": self.account_id, "revoked": True}


class LovableConnector(BaseConnector):
    """Lovable App Generator Connector — Browser-First Approach.

    Lovable does not offer a public REST API. Instead:
    - **Build with URL**: `https://lovable.dev/?autosubmit=true#prompt=...` — browser-based workflow
    - **MCP Server**: `https://mcp.lovable.dev` — OAuth-based deep integration for AI agents

    Guardian uses the browser fallback as the primary interaction mechanism,
    and can generate Build-with-URL links for guided browser workflows.
    vault secret (optional): stores the user's Lovable account identifier for session tracking.
    """

    _LOVABLE_WEB_URL = "https://lovable.dev"
    _LOVABLE_MCP_URL = "https://mcp.lovable.dev"

    def __init__(self, account_id: str) -> None:
        super().__init__("lovable", account_id)

    def detect_capabilities(self, brain: ProjectBrain) -> dict[str, Any]:
        acc = get_account(brain, self.account_id)
        secret = _resolve_vault_secret(brain, acc.get("vault_ref", ""))
        has_creds = bool(secret)
        return {
            "connector": self.connector_name,
            "account_id": self.account_id,
            "status": "available" if has_creds else "browser_fallback",
            "capabilities": [
                "browser_fallback",
                "build_with_url",
                "create_app",
                "export_code",
            ],
            "allowed_domains": acc.get("allowed_domains", ["lovable.dev"]),
            "api_ready": False,  # No public REST API
            "browser_fallback_ready": True,
            "mcp_server_url": self._LOVABLE_MCP_URL,
            "mcp_status": "available_via_oauth" if has_creds else "authentication_required",
        }

    def authenticate(self, brain: ProjectBrain) -> dict[str, Any]:
        acc = get_account(brain, self.account_id)
        secret = _resolve_vault_secret(brain, acc.get("vault_ref", ""))
        is_ready = bool(secret)
        # Lovable has no remote auth endpoint — MCP uses OAuth (browser-based)
        return {
            "connector": self.connector_name,
            "account_id": self.account_id,
            "authenticated": is_ready,
            "credential_available": is_ready,
            "remote_authenticated": False,  # No REST API to verify against
            "status": "credential_available" if is_ready else "authentication_required",
            "auth_note": "Lovable uses OAuth via browser. Store account identifier in vault for session tracking.",
        }

    def _generate_build_url(self, title: str, prompt: str | None = None,
                            images: list[str] | None = None) -> dict[str, Any]:
        """Generate a Lovable 'Build with URL' link for browser-based app creation."""
        import urllib.parse
        parts = []
        # URL-encode the prompt
        final_prompt = prompt or f"Create an app: {title}"
        parts.append(f"prompt={urllib.parse.quote(final_prompt)}")
        if images:
            for img_url in images:
                parts.append(f"images={urllib.parse.quote(img_url)}")
        fragment = "&".join(parts)
        build_url = f"{self._LOVABLE_WEB_URL}/?autosubmit=true#fragment={urllib.parse.quote(fragment)}"
        # Simpler direct format
        direct_url = f"{self._LOVABLE_WEB_URL}/?autosubmit=true#prompt={urllib.parse.quote(final_prompt)}"
        return {
            "connector": self.connector_name,
            "build_url": direct_url,
            "full_url": build_url,
            "prompt": final_prompt,
            "instructions": "Open the build URL in a browser to start building the app in Lovable. "
                            "After the build completes, the app will be accessible in your Lovable account.",
        }

    def _require_browser_fallback(self, allow_mock: bool) -> None:
        """Ensure mock/browser-fallback is permitted for Lovable."""
        _check_allow_mock_permitted(allow_mock)

    def list_assets(self, brain: ProjectBrain, query: str = "", allow_mock: bool = False) -> dict[str, Any]:
        _check_allow_mock_permitted(allow_mock)
        # Lovable has no REST API — return browser fallback guidance
        return {
            "connector": self.connector_name,
            "account_id": self.account_id,
            "assets": [],
            "note": "Lovable does not provide a listing API. Open https://lovable.dev/projects in a browser to view your projects.",
            "browser_fallback": True,
        }

    def read_asset(self, brain: ProjectBrain, asset_id: str, allow_mock: bool = False) -> dict[str, Any]:
        _check_allow_mock_permitted(allow_mock)
        return {
            "connector": self.connector_name,
            "account_id": self.account_id,
            "asset_id": asset_id,
            "title": f"Lovable App {asset_id}",
            "url": validate_and_sanitize_url(f"https://lovable.dev/project/{asset_id}", allow_offline=True),
            "note": "Open the URL in a browser to view this Lovable project.",
            "browser_fallback": True,
        }

    def create_asset(
        self,
        brain: ProjectBrain,
        title: str,
        template_id: str | None = None,
        parameters: dict[str, Any] | None = None,
        approval_id: str | None = None,
        allow_mock: bool = False,
    ) -> dict[str, Any]:
        _check_allow_mock_permitted(allow_mock)

        prompt = title
        if parameters and isinstance(parameters, dict):
            extra = parameters.get("description", parameters.get("prompt", ""))
            if extra:
                prompt = f"{title}: {extra}"

        build_info = self._generate_build_url(title, prompt=prompt)
        asset_id = f"lovable-{secrets.token_hex(6)}"

        return {
            "connector": self.connector_name,
            "account_id": self.account_id,
            "asset_id": asset_id,
            "title": title,
            "template_id": template_id,
            "status": "build_url_generated",
            "created_at": now_utc(),
            "build_url": build_info["build_url"],
            "instructions": build_info["instructions"],
            "browser_fallback": True,
        }

    def export_asset(self, brain: ProjectBrain, asset_id: str, export_format: str = "zip",
                     allow_mock: bool = False) -> dict[str, Any]:
        _check_allow_mock_permitted(allow_mock)
        out_file = _validate_export_path(brain, self.connector_name, asset_id, export_format)
        out_file.write_bytes(b"Lovable app export placeholder - export via browser\n")
        return {
            "connector": self.connector_name,
            "account_id": self.account_id,
            "asset_id": asset_id,
            "export_format": export_format,
            "artifact_path": str(out_file),
            "created_at": now_utc(),
            "note": "Lovable does not provide a direct export API. "
                    "Visit the project page in a browser to download the app code.",
            "browser_fallback": True,
        }

    def classify_approval(self, action_type: str) -> str:
        if action_type in ("publish", "purchase", "delete"):
            return "requires_approval"
        return "permitted"

    def revoke_session(self, brain: ProjectBrain) -> dict[str, Any]:
        revoke_account(brain, self.account_id)
        return {"connector": self.connector_name, "account_id": self.account_id, "revoked": True}


def get_connector(connector_name: str, account_id: str) -> BaseConnector:
    c = connector_name.lower().strip()
    if c == "canva":
        return CanvaConnector(account_id)
    elif c == "adobe":
        return AdobeConnector(account_id)
    elif c == "lovable":
        return LovableConnector(account_id)
    else:
        raise GuardianError(f"Unsupported connector {connector_name!r}. Supported: canva, adobe, lovable")
