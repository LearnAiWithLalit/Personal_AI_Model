"""Research & Compact Handoff (Phase D).

Provides repository inspection, source structure analysis, and compact
work-package generation for specialist workers.
"""

from __future__ import annotations

import os
from pathlib import Path
from guardian_agent.core import ProjectBrain, render_context


def inspect_repository(root_path: Path) -> dict:
    root = root_path.resolve()
    files = []
    ignored = {".git", ".agent", "__pycache__", ".venv", "node_modules"}
    
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignored]
        for f in filenames:
            rel = Path(dirpath, f).relative_to(root)
            files.append(str(rel))
            if len(files) >= 200:
                break
        if len(files) >= 200:
            break
            
    return {
        "root": str(root),
        "total_files": len(files),
        "files": files,
    }


def build_handoff_package(
    brain: ProjectBrain,
    task_name: str,
    target_files: list[str] | None = None,
) -> dict:
    target_files = target_files or []
    context_text = render_context(brain)
    
    file_snippets = []
    for tf in target_files:
        full_p = brain.root / tf
        if full_p.is_file():
            try:
                snippet = full_p.read_text(encoding="utf-8")[:1500]
                file_snippets.append(f"### File: {tf}\n```\n{snippet}\n```")
            except Exception:
                file_snippets.append(f"### File: {tf} (Binary or Unreadable)")
                
    markdown_output = (
        f"# Work Package: {task_name}\n\n"
        f"## Confirmed Project Context\n{context_text}\n\n"
        f"## Target Files\n" + ("\n\n".join(file_snippets) if file_snippets else "No specific target files specified.")
    )
    
    research_dir = brain.directory / "research"
    research_dir.mkdir(exist_ok=True)
    pkg_file = research_dir / f"handoff_{task_name.lower().replace(' ', '_')}.md"
    pkg_file.write_text(markdown_output, encoding="utf-8")
    
    return {
        "task_name": task_name,
        "confirmed_goal": task_name,
        "target_files": target_files,
        "handoff_markdown": markdown_output,
        "saved_path": str(pkg_file),
    }
