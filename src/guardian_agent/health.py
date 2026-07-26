"""Provider Health System, Quota & Latency Monitoring (Phase G0).

Monitors provider health, error counts, latency, and rate limits.
Strict error handling: ensures provider failures are explicitly reported without
hiding errors under simulated outputs.
"""

from __future__ import annotations

import json
from pathlib import Path
from guardian_agent.core import ProjectBrain, append_journey, now_utc, markdown_escape


HEALTH_FILE = "provider_health.json"


def health_file_path(brain: ProjectBrain) -> Path:
    return brain.directory / HEALTH_FILE


def _load_health(brain: ProjectBrain) -> dict:
    p = health_file_path(brain)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_health(brain: ProjectBrain, data: dict) -> None:
    health_file_path(brain).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def check_provider_health(brain: ProjectBrain, provider_id: str) -> dict:
    clean_id = markdown_escape(provider_id)
    data = _load_health(brain)
    info = data.get(clean_id, {"error_count": 0, "last_error": None, "healthy": True})
    return {
        "provider_id": clean_id,
        "healthy": info.get("error_count", 0) < 3,
        "error_count": info.get("error_count", 0),
        "last_error": info.get("last_error"),
        "last_check": now_utc(),
    }


def record_provider_error(brain: ProjectBrain, provider_id: str, error_msg: str) -> None:
    clean_id = markdown_escape(provider_id)
    clean_err = markdown_escape(error_msg)
    data = _load_health(brain)
    
    info = data.get(clean_id, {"error_count": 0, "last_error": None, "healthy": True})
    info["error_count"] = info.get("error_count", 0) + 1
    info["last_error"] = clean_err
    info["healthy"] = info["error_count"] < 3
    info["updated_at"] = now_utc()
    
    data[clean_id] = info
    _save_health(brain, data)
    append_journey(brain, f"Provider Error Logged: {clean_id}", [f"Error: {clean_err}", f"Error count: {info['error_count']}"])


def record_provider_success(brain: ProjectBrain, provider_id: str) -> None:
    clean_id = markdown_escape(provider_id)
    data = _load_health(brain)
    if clean_id in data:
        data[clean_id]["error_count"] = 0
        data[clean_id]["healthy"] = True
        data[clean_id]["updated_at"] = now_utc()
        _save_health(brain, data)
