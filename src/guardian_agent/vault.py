"""Local secret vault with authenticated encryption and safe references.

Secrets are never written to the project brain.  New vault entries use a
Fernet key derived from ``GUARDIAN_VAULT_PASSPHRASE`` and a per-vault salt.
An existing legacy obfuscated vault is readable only for migration; writing to
it upgrades it automatically.  A passphrase is intentionally not persisted.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from guardian_agent.core import GuardianError, ProjectBrain, now_utc


VAULT_FILE = "vault.json.enc"
VAULT_VERSION = 2
PASSPHRASE_ENV = "GUARDIAN_VAULT_PASSPHRASE"


def vault_file_path(brain: ProjectBrain) -> Path:
    return brain.directory / VAULT_FILE


def _normalise_key(key: str) -> str:
    clean = key.strip().upper()
    if not clean or not all(char.isalnum() or char == "_" for char in clean):
        raise GuardianError("Vault keys may contain only letters, numbers, and underscores.")
    return clean


def _legacy_deobfuscate(cipher_b64: str, key_seed: str = "GuardianVaultKey2026") -> str:
    raw = base64.b64decode(cipher_b64.encode("ascii"))
    seed = key_seed.encode("utf-8")
    return bytes(byte ^ seed[index % len(seed)] for index, byte in enumerate(raw)).decode("utf-8")


def _fernet(salt_b64: str) -> Fernet:
    passphrase = os.environ.get(PASSPHRASE_ENV)
    if not passphrase:
        raise GuardianError(
            f"Set {PASSPHRASE_ENV} before storing or reading vault secrets. "
            "Guardian never saves this passphrase."
        )
    from hashlib import pbkdf2_hmac

    salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
    material = pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 600_000, dklen=32)
    return Fernet(base64.urlsafe_b64encode(material))


def _load_payload(brain: ProjectBrain) -> dict:
    path = vault_file_path(brain)
    if not path.exists():
        return {"version": VAULT_VERSION, "salt": base64.urlsafe_b64encode(os.urandom(16)).decode("ascii"), "entries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise GuardianError("Vault file is corrupted; restore it from a backup.") from error
    if payload.get("version") == VAULT_VERSION and isinstance(payload.get("entries"), dict):
        return payload
    # Old format contained {KEY: {value: XOR-base64, updated_at: ...}}.
    if all(isinstance(value, dict) and "value" in value for value in payload.values()):
        return {"version": 1, "entries": payload}
    raise GuardianError("Vault file has an unsupported format.")


def _decrypt_entries(brain: ProjectBrain, payload: dict) -> dict[str, dict]:
    if payload["version"] == 1:
        return {
            key: {"value": _legacy_deobfuscate(info["value"]), "updated_at": info.get("updated_at")}
            for key, info in payload["entries"].items()
        }
    cipher = _fernet(payload["salt"])
    result = {}
    for key, token in payload["entries"].items():
        try:
            result[key] = {"value": cipher.decrypt(token.encode("ascii")).decode("utf-8")}
        except InvalidToken as error:
            raise GuardianError("Vault cannot be decrypted: incorrect passphrase or corrupted data.") from error
    return result


def _write_entries(brain: ProjectBrain, entries: dict[str, dict], old_payload: dict | None = None) -> None:
    salt = old_payload.get("salt") if old_payload and old_payload.get("version") == VAULT_VERSION else base64.urlsafe_b64encode(os.urandom(16)).decode("ascii")
    cipher = _fernet(salt)
    payload = {
        "version": VAULT_VERSION,
        "salt": salt,
        "entries": {key: cipher.encrypt(info["value"].encode("utf-8")).decode("ascii") for key, info in entries.items()},
    }
    vault_file_path(brain).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def store_secret(brain: ProjectBrain, key: str, secret_value: str) -> dict:
    clean_key = _normalise_key(key)
    if not secret_value:
        raise GuardianError("Refusing to store an empty secret.")
    payload = _load_payload(brain)
    entries = _decrypt_entries(brain, payload) if payload.get("entries") else {}
    entries[clean_key] = {"value": secret_value, "updated_at": now_utc()}
    _write_entries(brain, entries, payload)
    return {"key": clean_key, "vault_uri": f"vault://{clean_key}"}


def has_secret(brain: ProjectBrain, key: str) -> bool:
    clean_key = _normalise_key(key.removeprefix("vault://"))
    if clean_key in os.environ:
        return True
    payload = _load_payload(brain)
    entries = payload.get("entries", {}) if payload.get("version") == VAULT_VERSION else payload
    return clean_key in entries


def get_secret(brain: ProjectBrain, uri_or_key: str) -> str | None:
    clean_key = _normalise_key(uri_or_key.removeprefix("vault://"))
    if clean_key in os.environ:
        return os.environ[clean_key]
    payload = _load_payload(brain)
    entries = payload.get("entries", {}) if payload.get("version") == VAULT_VERSION else payload
    if clean_key not in entries:
        return None
    return _decrypt_entries(brain, payload)[clean_key]["value"]


def redact_secrets(brain: ProjectBrain, text: str) -> str:
    try:
        payload = _load_payload(brain)
        entries = _decrypt_entries(brain, payload) if payload.get("entries") else {}
    except GuardianError:
        # Redaction must never turn a harmless error report into a crash.
        return text
    cleaned = text
    for info in entries.values():
        secret = info["value"]
        if len(secret) >= 4:
            cleaned = cleaned.replace(secret, "[REDACTED_SECRET]")
    return cleaned
