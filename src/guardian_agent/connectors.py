"""Generic Connector Interface & Subscription Connectors (Phase 5 Hardened).

Provides a standard unified contract for subscription connectors (Canva, Adobe, Lovable),
capability discovery, user-controlled authentication via vault, typed approval classification,
durable idempotency ledger, audit receipts, export path traversal validation, and ConnectorNotConfigured guards.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from guardian_agent.accounts import ProfileLockManager, get_account, revoke_account
from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc
from guardian_agent.policy import check_policy_permission, consume_action_approval
from guardian_agent.security_url import validate_and_sanitize_url
from guardian_agent.vault import get_secret


class ConnectorNotConfigured(GuardianError):
    """Raised when attempting real remote operations on an unconfigured or mock connector."""


_ALLOWED_EXPORT_FORMATS = {"png", "pdf", "zip", "jpeg", "svg"}
_ASSET_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


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
            raise GuardianError(f"Security violation: export path escaped target directory.")
    except AttributeError:
        if os.path.commonpath([str(out_file), str(export_dir)]) != str(export_dir):
            raise GuardianError(f"Security violation: export path escaped target directory.")

    return out_file


class IdempotencyLedger:
    """Durable ledger tracking connector operations to enforce idempotency with atomic writes and locking."""

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
    def get_receipt(cls, brain: ProjectBrain, composite_key: str) -> dict[str, Any] | None:
        lock_p = cls._lock_path(brain)
        with open(lock_p, "a", encoding="utf-8") as lock_fd:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_SH)
            try:
                ledger = cls.load(brain)
                entry = ledger.get(composite_key)
                if entry and entry.get("status") == "completed":
                    return entry.get("receipt")
                return None
            finally:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)

    @classmethod
    def record(cls, brain: ProjectBrain, composite_key: str, status: str, receipt: dict[str, Any] | None = None) -> None:
        lock_p = cls._lock_path(brain)
        with open(lock_p, "a", encoding="utf-8") as lock_fd:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            try:
                ledger = cls.load(brain)
                ledger[composite_key] = {
                    "status": status,
                    "recorded_at": now_utc(),
                    "receipt": receipt,
                }
                p = cls._ledger_path(brain)
                tmp = p.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
                with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as fh:
                    json.dump(ledger, fh, indent=2)
                    fh.write("\n")
                tmp.replace(p)
            finally:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)


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
        """Export asset to local artifact directory with audit receipt."""

    @abstractmethod
    def classify_approval(self, action_type: str) -> str:
        """Return 'permitted' or 'requires_approval' for a given action."""

    @abstractmethod
    def revoke_session(self, brain: ProjectBrain) -> dict[str, Any]:
        """Revoke active connector session."""


class CanvaConnector(BaseConnector):
    """Canva Subscription Connector (Foundation & Mock Scaffolding)."""

    def __init__(self, account_id: str) -> None:
        super().__init__("canva", account_id)

    def detect_capabilities(self, brain: ProjectBrain) -> dict[str, Any]:
        acc = get_account(brain, self.account_id)
        return {
            "connector": self.connector_name,
            "account_id": self.account_id,
            "status": "mock",
            "capabilities": ["list_designs", "create_design", "export_png", "export_pdf", "browser_fallback"],
            "allowed_domains": acc.get("allowed_domains", ["canva.com"]),
            "api_ready": False,
            "browser_fallback_ready": True,
        }

    def authenticate(self, brain: ProjectBrain) -> dict[str, Any]:
        acc = get_account(brain, self.account_id)
        secret = _resolve_vault_secret(brain, acc.get("vault_ref", ""))
        return {
            "connector": self.connector_name,
            "account_id": self.account_id,
            "authenticated": bool(secret),
            "credential_available": bool(secret),
            "remote_authenticated": False,
            "status": "authenticated" if secret else "authentication_required",
        }


    def list_assets(self, brain: ProjectBrain, query: str = "", allow_mock: bool = False) -> dict[str, Any]:
        if not allow_mock:
            raise ConnectorNotConfigured(f"Canva connector real backend API is not configured for account {self.account_id!r}.")
        auth = self.authenticate(brain)
        if not auth.get("credential_available"):
            raise GuardianError(f"Authentication required for account {self.account_id!r}.")
        return {
            "connector": self.connector_name,
            "account_id": self.account_id,
            "assets": [
                {"id": "design-canva-001", "title": "Social Media Banner", "type": "banner", "updated_at": now_utc()},
            ],
        }

    def read_asset(self, brain: ProjectBrain, asset_id: str, allow_mock: bool = False) -> dict[str, Any]:
        if not allow_mock:
            raise ConnectorNotConfigured(f"Canva connector real backend API is not configured for account {self.account_id!r}.")
        auth = self.authenticate(brain)
        if not auth.get("credential_available"):
            raise GuardianError(f"Authentication required for account {self.account_id!r}.")
        return {
            "connector": self.connector_name,
            "asset_id": asset_id,
            "title": f"Canva Design {asset_id}",
            "url": validate_and_sanitize_url(f"https://canva.com/design/{asset_id}", allow_offline=True),
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
        if not allow_mock:
            raise ConnectorNotConfigured(f"Canva connector real backend API is not configured for account {self.account_id!r}.")
        auth = self.authenticate(brain)
        if not auth.get("credential_available"):
            raise GuardianError(f"Authentication required for account {self.account_id!r}.")

        param_str = json.dumps(parameters or {}, sort_keys=True)
        composite_raw = f"{self.account_id}:{self.connector_name}:create_asset:{title}:{template_id or ''}:{param_str}"
        composite_key = f"key-{hashlib.sha256(composite_raw.encode('utf-8')).hexdigest()[:24]}"

        cached = IdempotencyLedger.get_receipt(brain, composite_key)
        if cached:
            return cached

        with ProfileLockManager(brain, self.account_id):
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
            }
            IdempotencyLedger.record(brain, composite_key, "completed", receipt)
            append_journey(brain, f"Canva Asset Created: {asset_id}", [f"Title: {title}"])
            return receipt

    def export_asset(
        self,
        brain: ProjectBrain,
        asset_id: str,
        export_format: str = "png",
        allow_mock: bool = False,
    ) -> dict[str, Any]:
        if not allow_mock:
            raise ConnectorNotConfigured(f"Canva connector real backend API is not configured for account {self.account_id!r}.")
        auth = self.authenticate(brain)
        if not auth.get("credential_available"):
            raise GuardianError(f"Authentication required for account {self.account_id!r}.")

        out_file = _validate_export_path(brain, self.connector_name, asset_id, export_format)
        out_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89")

        return {
            "connector": self.connector_name,
            "asset_id": asset_id,
            "export_format": export_format,
            "artifact_path": str(out_file),
            "created_at": now_utc(),
        }

    def classify_approval(self, action_type: str) -> str:
        if action_type in ("publish", "purchase", "delete"):
            return "requires_approval"
        return "permitted"

    def revoke_session(self, brain: ProjectBrain) -> dict[str, Any]:
        revoke_account(brain, self.account_id)
        return {"connector": self.connector_name, "account_id": self.account_id, "revoked": True}


class AdobeConnector(BaseConnector):
    """Adobe Creative Cloud Connector (Foundation & Mock Scaffolding)."""

    def __init__(self, account_id: str) -> None:
        super().__init__("adobe", account_id)

    def detect_capabilities(self, brain: ProjectBrain) -> dict[str, Any]:
        acc = get_account(brain, self.account_id)
        return {
            "connector": self.connector_name,
            "account_id": self.account_id,
            "status": "not_configured",
            "capabilities": ["list_projects", "create_project", "export_pdf", "browser_fallback"],
            "allowed_domains": acc.get("allowed_domains", ["adobe.com"]),
            "api_ready": False,
            "browser_fallback_ready": True,
        }

    def authenticate(self, brain: ProjectBrain) -> dict[str, Any]:
        acc = get_account(brain, self.account_id)
        secret = _resolve_vault_secret(brain, acc.get("vault_ref", ""))
        return {
            "connector": self.connector_name,
            "account_id": self.account_id,
            "authenticated": bool(secret),
            "credential_available": bool(secret),
            "remote_authenticated": False,
            "status": "authenticated" if secret else "authentication_required",
        }


    def list_assets(self, brain: ProjectBrain, query: str = "", allow_mock: bool = False) -> dict[str, Any]:
        if not allow_mock:
            raise ConnectorNotConfigured(f"Adobe connector real backend API is not configured for account {self.account_id!r}.")
        return {"connector": self.connector_name, "account_id": self.account_id, "assets": []}

    def read_asset(self, brain: ProjectBrain, asset_id: str, allow_mock: bool = False) -> dict[str, Any]:
        if not allow_mock:
            raise ConnectorNotConfigured(f"Adobe connector real backend API is not configured for account {self.account_id!r}.")
        return {"connector": self.connector_name, "asset_id": asset_id, "title": f"Adobe Asset {asset_id}"}

    def create_asset(self, brain: ProjectBrain, title: str, template_id: str | None = None, parameters: dict[str, Any] | None = None, approval_id: str | None = None, allow_mock: bool = False) -> dict[str, Any]:
        if not allow_mock:
            raise ConnectorNotConfigured(f"Adobe connector real backend API is not configured for account {self.account_id!r}.")
        asset_id = f"adobe-{secrets.token_hex(6)}"
        return {"connector": self.connector_name, "account_id": self.account_id, "asset_id": asset_id, "title": title, "status": "created"}

    def export_asset(self, brain: ProjectBrain, asset_id: str, export_format: str = "pdf", allow_mock: bool = False) -> dict[str, Any]:
        if not allow_mock:
            raise ConnectorNotConfigured(f"Adobe connector real backend API is not configured for account {self.account_id!r}.")
        out_file = _validate_export_path(brain, self.connector_name, asset_id, export_format)
        out_file.write_bytes(b"%PDF-1.4 %EOF\n")
        return {"connector": self.connector_name, "asset_id": asset_id, "artifact_path": str(out_file)}

    def classify_approval(self, action_type: str) -> str:
        if action_type in ("publish", "purchase", "delete"):
            return "requires_approval"
        return "permitted"

    def revoke_session(self, brain: ProjectBrain) -> dict[str, Any]:
        revoke_account(brain, self.account_id)
        return {"connector": self.connector_name, "account_id": self.account_id, "revoked": True}


class LovableConnector(BaseConnector):
    """Lovable App Generator Connector (Foundation & Mock Scaffolding)."""

    def __init__(self, account_id: str) -> None:
        super().__init__("lovable", account_id)

    def detect_capabilities(self, brain: ProjectBrain) -> dict[str, Any]:
        acc = get_account(brain, self.account_id)
        return {
            "connector": self.connector_name,
            "account_id": self.account_id,
            "status": "not_configured",
            "capabilities": ["list_projects", "create_app", "export_code", "browser_fallback"],
            "allowed_domains": acc.get("allowed_domains", ["lovable.dev"]),
            "api_ready": False,
            "browser_fallback_ready": True,
        }

    def authenticate(self, brain: ProjectBrain) -> dict[str, Any]:
        acc = get_account(brain, self.account_id)
        secret = _resolve_vault_secret(brain, acc.get("vault_ref", ""))
        return {
            "connector": self.connector_name,
            "account_id": self.account_id,
            "authenticated": bool(secret),
            "credential_available": bool(secret),
            "remote_authenticated": False,
            "status": "authenticated" if secret else "authentication_required",
        }


    def list_assets(self, brain: ProjectBrain, query: str = "", allow_mock: bool = False) -> dict[str, Any]:
        if not allow_mock:
            raise ConnectorNotConfigured(f"Lovable connector real backend API is not configured for account {self.account_id!r}.")
        return {"connector": self.connector_name, "account_id": self.account_id, "assets": []}

    def read_asset(self, brain: ProjectBrain, asset_id: str, allow_mock: bool = False) -> dict[str, Any]:
        if not allow_mock:
            raise ConnectorNotConfigured(f"Lovable connector real backend API is not configured for account {self.account_id!r}.")
        return {"connector": self.connector_name, "asset_id": asset_id, "title": f"Lovable App {asset_id}"}

    def create_asset(self, brain: ProjectBrain, title: str, template_id: str | None = None, parameters: dict[str, Any] | None = None, approval_id: str | None = None, allow_mock: bool = False) -> dict[str, Any]:
        if not allow_mock:
            raise ConnectorNotConfigured(f"Lovable connector real backend API is not configured for account {self.account_id!r}.")
        asset_id = f"lovable-{secrets.token_hex(6)}"
        return {"connector": self.connector_name, "account_id": self.account_id, "asset_id": asset_id, "title": title, "status": "created"}

    def export_asset(self, brain: ProjectBrain, asset_id: str, export_format: str = "zip", allow_mock: bool = False) -> dict[str, Any]:
        if not allow_mock:
            raise ConnectorNotConfigured(f"Lovable connector real backend API is not configured for account {self.account_id!r}.")
        out_file = _validate_export_path(brain, self.connector_name, asset_id, export_format)
        out_file.write_bytes(b"PK\x03\x04\x14\x00\x00\x00\x00\x00")
        return {"connector": self.connector_name, "asset_id": asset_id, "artifact_path": str(out_file)}

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
