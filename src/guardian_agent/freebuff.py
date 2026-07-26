"""Freebuff CLI adapter for token-saving interactive coding sessions.

Freebuff is an interactive terminal agent, not a provider API. Guardian keeps
the integration explicit: it creates a compact handoff file and launches or
continues a Freebuff session only when the user runs the corresponding command.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, render_context


def _freebuff_path() -> str | None:
    extra_paths = ["/home/lalit/.local/bin", "/home/lalit/.local/node/bin"]
    search_path = os.pathsep.join([*extra_paths, os.environ.get("PATH", "")])
    return shutil.which("freebuff", path=search_path)


def freebuff_status() -> dict:
    executable = _freebuff_path()
    if not executable:
        return {"available": False, "message": "Freebuff CLI was not found on PATH."}
    try:
        version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=10, check=True)
        return {"available": True, "executable": executable, "version": version.stdout.strip()}
    except (subprocess.SubprocessError, OSError) as error:
        return {"available": False, "executable": executable, "message": str(error)}


def create_freebuff_handoff(brain: ProjectBrain, task: str) -> dict:
    clean_task = task.strip()
    if not clean_task:
        raise GuardianError("A non-empty Freebuff task is required.")
    context = render_context(brain)
    handoff_dir = brain.directory / "research"
    handoff_dir.mkdir(exist_ok=True)
    handoff = handoff_dir / "FREEBUFF_HANDOFF.md"
    handoff.write_text(
        "# Freebuff Coding Handoff\n\n"
        f"## Requested task\n\n{clean_task}\n\n"
        "## Instructions for the coding session\n\n"
        "Read the compact context below. Follow confirmed requirements, make only scoped changes, run relevant tests, and report changed files plus remaining risks. Do not expose secrets or perform external side effects.\n\n"
        f"{context}\n",
        encoding="utf-8",
    )
    append_journey(brain, "Freebuff Handoff Prepared", [f"Task: {clean_task}", f"Handoff: {handoff.name}"])
    return {"task": clean_task, "handoff": str(handoff), "instruction": f"Start Freebuff in {brain.root} and ask it to read {handoff}."}


def launch_freebuff(brain: ProjectBrain, conversation_id: str | None = None) -> int:
    executable = _freebuff_path()
    if not executable:
        raise GuardianError("Freebuff CLI is not installed. Install it or add it to PATH before launching a session.")
    command = [executable]
    if conversation_id:
        command.extend(["--continue", conversation_id])
    command.extend(["--cwd", str(brain.root)])
    append_journey(brain, "Freebuff Session Launched", [f"Conversation: {conversation_id or 'new'}"])
    # Deliberately inherit the terminal: Freebuff owns its login and interactive
    # session, while Guardian does not collect passwords, session cookies, or keys.
    return subprocess.run(command, cwd=str(brain.root), check=False).returncode
