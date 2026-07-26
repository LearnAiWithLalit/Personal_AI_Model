"""Account Registry & Persistent Browser Session Control (Phase 5 Hardened).

Manages user-owned creative/service subscription accounts (Canva, Adobe, Lovable),
encrypted vault credential references (never plaintext passwords in handoffs),
isolated persistent Playwright browser profiles (0700 permissions), profile-level process locks,
session expiration tracking, domain allowlists, and revocation controls.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc
from guardian_agent.security_url import validate_and_sanitize_url


@dataclass
class AccountRecord:
    """Registered subscription account record."""

    id: str
    service_name: str  # "canva" | "adobe" | "lovable" | "custom"
    account_label: str
    vault_ref: str     # Vault secret key reference (never raw passwords!)
    allowed_domains: list[str]
    created_at: str = field(default_factory=now_utc)
    session_expires_at: float | None = None
    revoked: bool = False


_ACCOUNT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_VALID_SERVICES = {"canva", "adobe", "lovable", "custom"}


def _validate_account_id(account_id: str) -> str:
    """Central account ID validation preventing path traversal and null-byte injection."""
    clean_id = str(account_id or "").strip()
    if not clean_id:
        raise GuardianError("Account ID cannot be empty.")
    if ".." in clean_id or "/" in clean_id or "\\" in clean_id or "\x00" in clean_id:
        raise GuardianError(f"Security violation: invalid path characters in account ID {account_id!r}.")
    if not _ACCOUNT_ID_PATTERN.match(clean_id):
        raise GuardianError(
            f"Invalid account ID format {account_id!r}. Must contain only alphanumeric, dash, or underscore characters."
        )
    return clean_id


def _accounts_dir(brain: ProjectBrain) -> Path:
    d = (brain.directory / "accounts").resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _account_path(brain: ProjectBrain, account_id: str) -> Path:
    clean_id = _validate_account_id(account_id)
    base = _accounts_dir(brain)
    target = (base / f"{clean_id}.json").resolve()
    if target.parent != base:
        raise GuardianError(f"Security violation: account path {account_id!r} escaped base directory.")
    return target


def _browser_profiles_dir(brain: ProjectBrain) -> Path:
    d = (brain.directory / "browser_profiles").resolve()
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def profile_path(brain: ProjectBrain, account_id: str) -> Path:
    """Return persistent user data directory path for an account with strict 0700 permissions and containment."""
    clean_id = _validate_account_id(account_id)
    base = _browser_profiles_dir(brain)
    target = (base / clean_id).resolve()
    try:
        if not target.is_relative_to(base):
            raise GuardianError(f"Security violation: profile path {account_id!r} escaped profiles directory.")
    except AttributeError:
        if os.path.commonpath([str(target), str(base)]) != str(base):
            raise GuardianError(f"Security violation: profile path {account_id!r} escaped profiles directory.")
    target.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target, 0o700)
    except OSError:
        pass
    return target


def profile_lock_path(brain: ProjectBrain, account_id: str) -> Path:
    """Return profile lock file path for an account with strict containment."""
    clean_id = _validate_account_id(account_id)
    base = _browser_profiles_dir(brain)
    target = (base / f"{clean_id}.lock").resolve()
    if target.parent != base:
        raise GuardianError(f"Security violation: lock path {account_id!r} escaped profiles directory.")
    return target


class ProfileLockManager:
    """Process lock for isolated persistent browser profile access."""

    def __init__(self, brain: ProjectBrain, account_id: str) -> None:
        self.brain = brain
        self.account_id = account_id
        self.lock_file = profile_lock_path(brain, account_id)
        self._fd = None

    def __enter__(self) -> ProfileLockManager:
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self._fd = open(self.lock_file, "w", encoding="utf-8")
        try:
            fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._fd.write(f"{os.getpid()}\n")
            self._fd.flush()
        except (OSError, IOError) as err:
            self._fd.close()
            self._fd = None
            raise GuardianError(
                f"Browser profile for account {self.account_id!r} is currently locked by another process."
            ) from err
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._fd:
            try:
                fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
                self._fd.close()
            except OSError:
                pass
            self._fd = None


def register_account(
    brain: ProjectBrain,
    account_id: str,
    service_name: str,
    account_label: str,
    vault_ref: str,
    allowed_domains: list[str],
) -> dict[str, Any]:
    """Register or update a subscription account with vault secret reference and domain validation."""
    clean_id = _validate_account_id(account_id)
    clean_service = service_name.lower().strip()

    if clean_service not in _VALID_SERVICES:
        raise GuardianError(f"Invalid service name {service_name!r}. Supported: {', '.join(sorted(_VALID_SERVICES))}.")

    if not vault_ref or not (vault_ref.startswith("vault://") or vault_ref.startswith("vault:")):
        raise GuardianError("Credentials must be passed via a valid 'vault://KEY' reference.")

    if not allowed_domains or len(allowed_domains) == 0:
        raise GuardianError("At least one allowed domain must be specified for account registration.")

    clean_domains = []
    for d in allowed_domains:
        cd = str(d or "").lower().strip()
        if not cd or "/" in cd or " " in cd:
            raise GuardianError(f"Invalid domain format {d!r} in allowed_domains.")
        clean_domains.append(cd)

    record = AccountRecord(
        id=clean_id,
        service_name=clean_service,
        account_label=account_label.strip(),
        vault_ref=vault_ref.strip(),
        allowed_domains=clean_domains,
    )

    data = {
        "id": record.id,
        "service_name": record.service_name,
        "account_label": record.account_label,
        "vault_ref": record.vault_ref,
        "allowed_domains": record.allowed_domains,
        "created_at": record.created_at,
        "session_expires_at": record.session_expires_at,
        "revoked": record.revoked,
    }

    path = _account_path(brain, clean_id)
    tmp = path.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    # Initialize profile directory with 0700 permissions
    profile_path(brain, clean_id)

    append_journey(brain, f"Account Registered: {clean_id}", [f"Service: {service_name}", f"Label: {account_label}"])
    return data


def get_account(brain: ProjectBrain, account_id: str) -> dict[str, Any]:
    """Load an account record and check revocation/expiry status."""
    path = _account_path(brain, account_id)
    if not path.is_file():
        raise GuardianError(f"Account {account_id!r} is not registered.")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GuardianError(f"Account file {account_id!r} is corrupted.") from exc

    if data.get("revoked"):
        raise GuardianError(f"Account {account_id!r} session has been revoked.")

    exp = data.get("session_expires_at")
    if exp and time.time() > float(exp):
        raise GuardianError(f"Account {account_id!r} session has expired. Re-authentication required.")

    return data


def revoke_account(brain: ProjectBrain, account_id: str) -> dict[str, Any]:
    """Revoke an account session and wipe its browser profile."""
    acc = get_account(brain, account_id)
    acc["revoked"] = True

    path = _account_path(brain, account_id)
    tmp = path.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as fh:
        json.dump(acc, fh, indent=2)
        fh.write("\n")
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    # Wipe profile directory
    p_dir = profile_path(brain, account_id)
    if p_dir.is_dir():
        try:
            shutil.rmtree(p_dir)
        except OSError as err:
            raise GuardianError(f"Failed to wipe browser profile for revoked account {account_id!r}: {err}") from err

    append_journey(brain, f"Account Revoked: {account_id}", ["Session revoked & profile wiped"])
    return acc
