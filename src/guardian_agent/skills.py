"""Skill Factory and Learning Loop (Phase E).

Manages skill lifecycles (draft -> validation -> trusted), versioning, and
automatic lesson injection into task context.
"""

from __future__ import annotations

import json
from pathlib import Path
from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc, markdown_escape


def skills_dir(brain: ProjectBrain) -> Path:
    d = brain.directory / "skills"
    d.mkdir(exist_ok=True)
    (d / "drafts").mkdir(exist_ok=True)
    (d / "trusted").mkdir(exist_ok=True)
    (d / "deprecated").mkdir(exist_ok=True)
    return d


def create_skill_draft(
    brain: ProjectBrain,
    name: str,
    description: str,
    instructions: str,
) -> dict:
    clean_name = markdown_escape(name).lower().replace(" ", "-")
    if not clean_name:
        raise GuardianError("Skill name cannot be empty.")
    
    base = skills_dir(brain) / "drafts" / clean_name
    base.mkdir(parents=True, exist_ok=True)
    
    skill_md = base / "SKILL.md"
    meta_json = base / "metadata.json"
    
    content = f"# Skill: {clean_name}\n\n## Description\n{description}\n\n## Instructions\n{instructions}\n"
    skill_md.write_text(content, encoding="utf-8")
    
    meta = {
        "name": clean_name,
        "description": description,
        "status": "draft",
        "created_at": now_utc(),
        "version": "0.1.0",
    }
    meta_json.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    
    append_journey(brain, f"Skill draft created: {clean_name}", [description])
    
    return {
        "name": clean_name,
        "status": "draft",
        "path": str(skill_md),
    }


def validate_skill(brain: ProjectBrain, name: str) -> dict:
    clean_name = markdown_escape(name).lower().replace(" ", "-")
    draft_path = skills_dir(brain) / "drafts" / clean_name
    if not draft_path.exists():
        raise GuardianError(f"Skill draft {clean_name!r} does not exist.")
    
    skill_md = draft_path / "SKILL.md"
    meta_json = draft_path / "metadata.json"
    
    if not skill_md.is_file() or not meta_json.is_file():
        return {"valid": False, "reason": "Missing SKILL.md or metadata.json"}
    
    meta = json.loads(meta_json.read_text(encoding="utf-8"))
    meta["validated_at"] = now_utc()
    meta_json.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    
    return {"valid": True, "name": clean_name}


def promote_skill(brain: ProjectBrain, name: str) -> dict:
    clean_name = markdown_escape(name).lower().replace(" ", "-")
    val = validate_skill(brain, clean_name)
    if not val.get("valid"):
        raise GuardianError(f"Cannot promote skill {clean_name!r}: validation failed.")
    
    draft_path = skills_dir(brain) / "drafts" / clean_name
    trusted_path = skills_dir(brain) / "trusted" / clean_name
    
    if trusted_path.exists():
        for f in trusted_path.glob("*"):
            f.unlink()
        trusted_path.rmdir()
        
    draft_path.rename(trusted_path)
    
    meta_json = trusted_path / "metadata.json"
    meta = json.loads(meta_json.read_text(encoding="utf-8"))
    meta["status"] = "trusted"
    meta["promoted_at"] = now_utc()
    meta_json.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    
    # Also update SKILLS.md in brain
    skills_doc = brain.document("SKILLS.md")
    content = skills_doc.read_text(encoding="utf-8")
    skills_doc.write_text(
        content + f"\n\n## Trusted: {clean_name}\n- {meta.get('description', '')}\n",
        encoding="utf-8",
    )
    
    append_journey(brain, f"Skill promoted to trusted: {clean_name}", [meta.get('description', '')])
    return {"name": clean_name, "status": "trusted", "path": str(trusted_path / "SKILL.md")}


def list_skills(brain: ProjectBrain) -> dict:
    base = skills_dir(brain)
    drafts = [d.name for d in (base / "drafts").iterdir() if d.is_dir()] if (base / "drafts").exists() else []
    trusted = [d.name for d in (base / "trusted").iterdir() if d.is_dir()] if (base / "trusted").exists() else []
    deprecated = [d.name for d in (base / "deprecated").iterdir() if d.is_dir()] if (base / "deprecated").exists() else []
    return {"drafts": drafts, "trusted": trusted, "deprecated": deprecated}


def inject_relevant_lessons(brain: ProjectBrain, task_query: str) -> str:
    lessons_path = brain.document("LESSONS.md")
    if not lessons_path.exists():
        return ""
    text = lessons_path.read_text(encoding="utf-8")
    query_words = set(task_query.lower().split())
    matched_lines = []
    for line in text.splitlines():
        if any(word in line.lower() for word in query_words if len(word) > 3):
            matched_lines.append(line)
    if matched_lines:
        return "\n## Relevant Lessons\n" + "\n".join(matched_lines[:5])
    return ""
