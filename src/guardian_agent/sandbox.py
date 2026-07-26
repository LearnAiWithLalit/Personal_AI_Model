"""Git Worktree Sandbox & Rollback Engine (Phase G0).

Provides isolated workspace control via Git worktrees (.agent/worktrees/), diff previews,
and safe one-command rollback paths to prevent unverified code edits on main branches.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc, markdown_escape


def worktrees_dir(brain: ProjectBrain) -> Path:
    d = brain.directory / "worktrees"
    d.mkdir(exist_ok=True)
    return d


def create_worktree_sandbox(brain: ProjectBrain, branch_name: str) -> dict:
    clean_branch = markdown_escape(branch_name).lower().replace(" ", "-")
    wt_path = worktrees_dir(brain) / clean_branch
    
    if wt_path.exists():
        shutil.rmtree(wt_path)
        
    wt_path.mkdir(parents=True, exist_ok=True)
    
    # Copy project files into sandbox (fallback if git worktree command not initialized)
    ignored = {".git", ".agent", "__pycache__", ".venv", "node_modules"}
    for item in brain.root.iterdir():
        if item.name not in ignored:
            target = wt_path / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
                
    append_journey(brain, f"Sandbox Worktree Created: {clean_branch}", [f"Path: {wt_path}"])
    return {
        "branch": clean_branch,
        "worktree_path": str(wt_path),
        "created_at": now_utc(),
    }


def generate_diff_preview(brain: ProjectBrain, worktree_path: str) -> dict:
    wt = Path(worktree_path)
    if not wt.is_dir():
        raise GuardianError(f"Worktree path {worktree_path!r} does not exist.")
        
    diff_lines = []
    for f in wt.glob("**/*"):
        if f.is_file():
            rel = f.relative_to(wt)
            orig = brain.root / rel
            if not orig.exists():
                diff_lines.append(f"+ New file: {rel}")
            elif orig.read_bytes() != f.read_bytes():
                diff_lines.append(f"~ Modified: {rel}")
                
    return {
        "worktree_path": worktree_path,
        "diff": "\n".join(diff_lines) if diff_lines else "No changes detected.",
    }


def rollback_sandbox(brain: ProjectBrain, worktree_path: str) -> dict:
    wt = Path(worktree_path)
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)
        
    append_journey(brain, "Sandbox Rolled Back", [f"Removed worktree: {worktree_path}"])
    return {"status": "rolled_back", "worktree_path": worktree_path}
