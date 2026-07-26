"""Computer Operator & Vault Security Boundary (Phase G).

Handles vault:// secret reference resolution, browser/desktop action policy checks,
and structured action logging to .agent/audit/.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from guardian_agent.core import ProjectBrain, append_journey, now_utc, markdown_escape


def resolve_vault_reference(uri: str, env: dict[str, str] | None = None) -> str | None:
    if not uri.startswith("vault://"):
        return uri
    var_name = uri.removeprefix("vault://").strip()
    source = env if env is not None else os.environ
    return source.get(var_name)


def audit_log_action(
    brain: ProjectBrain,
    action: str,
    target: str,
    status: str = "success",
    detail: str | None = None,
) -> dict:
    clean_action = markdown_escape(action)
    clean_target = markdown_escape(target)
    clean_status = markdown_escape(status)
    clean_detail = markdown_escape(detail or "")
    
    audit_dir = brain.directory / "audit"
    audit_dir.mkdir(exist_ok=True)
    jsonl_file = audit_dir / "audit.jsonl"
    
    entry = {
        "timestamp": now_utc(),
        "action": clean_action,
        "target": clean_target,
        "status": clean_status,
        "detail": clean_detail,
    }
    
    with jsonl_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
        
    append_journey(
        brain,
        f"Operator Action: {clean_action}",
        [f"Target: {clean_target}", f"Status: {clean_status}", f"Detail: {clean_detail}"],
    )
    
    return entry
