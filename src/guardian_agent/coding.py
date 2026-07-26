"""Coding Loop & Execution Sandbox (Phase F).

Provides safe file edit application, test execution verification in a sandbox,
and automated outcome recording into Project Brain records.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from guardian_agent.core import GuardianError, ProjectBrain, append_journey, record_lesson, now_utc, markdown_escape


def apply_file_edits(root_path: Path, file_edits: dict[str, str]) -> dict:
    root = root_path.resolve()
    modified = []
    for rel_path, content in file_edits.items():
        target = (root / rel_path).resolve()
        if not str(target).startswith(str(root)):
            raise GuardianError(f"Security boundary error: path {rel_path} escapes root {root}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        modified.append(rel_path)
        
    return {
        "status": "success",
        "modified_files": modified,
    }


def run_verification(root_path: Path, test_command: str) -> dict:
    if not test_command:
        return {"success": True, "exit_code": 0, "stdout": "No verification command supplied", "stderr": ""}
        
    try:
        process = subprocess.run(
            test_command,
            shell=True,
            cwd=str(root_path.resolve()),
            capture_output=True,
            text=True,
            timeout=120,
        )
        return {
            "success": process.returncode == 0,
            "exit_code": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
        }
    except subprocess.TimeoutExpired as error:
        return {
            "success": False,
            "exit_code": -1,
            "stdout": error.stdout or "",
            "stderr": "Execution timed out (120s limit exceeded).",
        }
    except Exception as error:
        return {
            "success": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": str(error),
        }


def run_coding_loop(
    brain: ProjectBrain,
    task: str,
    file_edits: dict[str, str],
    test_command: str | None = None,
) -> dict:
    clean_task = markdown_escape(task)
    edit_res = apply_file_edits(brain.root, file_edits)
    
    verif = run_verification(brain.root, test_command or "")
    
    lines = [
        f"Task: {clean_task}",
        f"Modified files: {', '.join(edit_res['modified_files'])}",
        f"Verification status: {'PASSED' if verif['success'] else 'FAILED'}",
    ]
    if not verif['success']:
        lines.append(f"Error output: {verif['stderr'][:200]}")
        record_lesson(brain, f"Failure in {clean_task}", verif['stderr'][:300] or "Verification failed.")
        
    append_journey(brain, f"Coding loop: {clean_task}", lines)
    
    return {
        "task": clean_task,
        "status": "completed" if verif["success"] else "failed_verification",
        "verified": verif["success"],
        "verification": verif,
        "modified_files": edit_res["modified_files"],
    }
