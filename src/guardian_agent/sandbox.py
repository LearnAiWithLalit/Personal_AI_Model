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
    if not clean_branch or not all(char.isalnum() or char in "-_/" for char in clean_branch):
        raise GuardianError("Worktree branch contains unsupported characters.")
    wt_path = worktrees_dir(brain) / clean_branch
    
    if wt_path.exists():
        raise GuardianError(f"Refusing to overwrite existing sandbox path {wt_path}.")

    git_check = subprocess.run(
        ["git", "-C", str(brain.root), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    if git_check.returncode == 0 and git_check.stdout.strip() == "true":
        branch_check = subprocess.run(
            ["git", "-C", str(brain.root), "show-ref", "--verify", "--quiet", f"refs/heads/{clean_branch}"],
            check=False,
        )
        if branch_check.returncode == 0:
            raise GuardianError(f"Refusing to reuse existing branch {clean_branch!r}.")
        process = subprocess.run(
            ["git", "-C", str(brain.root), "worktree", "add", "-b", clean_branch, str(wt_path), "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            raise GuardianError(f"Git worktree creation failed: {process.stderr.strip()}")
        mode = "git-worktree"
    else:
        # Explicit compatibility fallback for projects not yet initialized as git repositories.
        wt_path.mkdir(parents=True, exist_ok=False)
        mode = "copy-fallback"
        _copy_project(brain, wt_path)

    append_journey(brain, f"Sandbox Worktree Created: {clean_branch}", [f"Path: {wt_path}", f"Mode: {mode}"])
    return {
        "branch": clean_branch,
        "worktree_path": str(wt_path),
        "mode": mode,
        "created_at": now_utc(),
    }


def _copy_project(brain: ProjectBrain, wt_path: Path) -> None:
    ignored = {".git", ".agent", "__pycache__", ".venv", "node_modules"}
    for item in brain.root.iterdir():
        if item.name not in ignored:
            target = wt_path / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)


def generate_diff_preview(brain: ProjectBrain, worktree_path: str) -> dict:
    wt = _validated_worktree_path(brain, worktree_path)
    if not wt.is_dir():
        raise GuardianError(f"Worktree path {worktree_path!r} does not exist.")
    git_check = subprocess.run(
        ["git", "-C", str(wt), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    if git_check.returncode == 0:
        status = subprocess.run(
            ["git", "-C", str(wt), "status", "--short"],
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "worktree_path": str(wt),
            "mode": "git-worktree",
            "diff": status.stdout.strip() or "No changes detected.",
        }

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
    wt = _validated_worktree_path(brain, worktree_path)
    if wt.exists():
        git_marker = wt / ".git"
        if git_marker.exists():
            process = subprocess.run(
                ["git", "-C", str(brain.root), "worktree", "remove", "--force", str(wt)],
                capture_output=True,
                text=True,
                check=False,
            )
            if process.returncode != 0:
                raise GuardianError(f"Git worktree rollback failed: {process.stderr.strip()}")
        else:
            shutil.rmtree(wt)

    append_journey(brain, "Sandbox Rolled Back", [f"Removed worktree: {worktree_path}"])
    return {"status": "rolled_back", "worktree_path": worktree_path}


def _validated_worktree_path(brain: ProjectBrain, worktree_path: str) -> Path:
    base = worktrees_dir(brain).resolve()
    candidate = Path(worktree_path).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as error:
        raise GuardianError("Sandbox path must remain inside this project's Guardian worktree directory.") from error
    if candidate == base:
        raise GuardianError("The worktree directory itself cannot be used as a sandbox target.")
    return candidate
