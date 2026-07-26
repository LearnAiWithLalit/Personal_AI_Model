"""Creative Subscription Integrations & Artifact Tracker (Phase H).

Records design and creative assets (Canva, Adobe, Lovable, Figma) into .agent/artifacts/
and maintains project brain audit tracking.
"""

from __future__ import annotations

import json
from pathlib import Path
from guardian_agent.core import ProjectBrain, append_journey, now_utc, markdown_escape


def record_creative_artifact(
    brain: ProjectBrain,
    tool_name: str,
    asset_name: str,
    asset_url: str,
    notes: str | None = None,
) -> dict:
    clean_tool = markdown_escape(tool_name).lower()
    clean_name = markdown_escape(asset_name)
    clean_url = markdown_escape(asset_url)
    clean_notes = markdown_escape(notes or "")
    
    artifacts_dir = brain.directory / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    manifest = artifacts_dir / "creative_manifest.json"
    
    existing = []
    if manifest.is_file():
        try:
            existing = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            existing = []
            
    entry = {
        "timestamp": now_utc(),
        "tool": clean_tool,
        "asset_name": clean_name,
        "asset_url": clean_url,
        "notes": clean_notes,
    }
    existing.append(entry)
    manifest.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    
    append_journey(
        brain,
        f"Creative Asset Tracked: {clean_name}",
        [f"Tool: {clean_tool}", f"URL: {clean_url}", f"Notes: {clean_notes}"],
    )
    
    return entry


def list_creative_artifacts(brain: ProjectBrain) -> list[dict]:
    manifest = brain.directory / "artifacts" / "creative_manifest.json"
    if not manifest.is_file():
        return []
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return []
