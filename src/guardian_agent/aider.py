"""Bounded Aider worker adapter for local Ollama or the user's OmniRoute."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

from guardian_agent.core import GuardianError, ProjectBrain, append_journey
from guardian_agent.model_policy import require_model_allowed
from guardian_agent.profiles import prepare_profile_handoff


BACKENDS = {
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "host": "127.0.0.1",
        "port": 11434,
        "credential_env": None,
        "credential_required": False,
    },
    "omniroute": {
        "base_url": "http://localhost:3000/v1",
        "host": "127.0.0.1",
        "port": 3000,
        "credential_env": "OMNIROUTE_API_KEY",
        "credential_required": False,
    },
}


def _aider_path() -> str | None:
    search_path = os.pathsep.join([
        "/home/lalit/.local/bin",
        os.environ.get("PATH", ""),
    ])
    return shutil.which("aider", path=search_path)


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def aider_status() -> dict:
    executable = _aider_path()
    result = {
        "available": bool(executable),
        "executable": executable,
        "backends": {
            name: {
                "base_url": config["base_url"],
                "reachable": _port_open(config["host"], config["port"]),
                "credential_env": config["credential_env"],
                "credential_required": config["credential_required"],
                "credential_available": (
                    True if config["credential_env"] is None
                    else bool(os.environ.get(config["credential_env"]))
                ),
            }
            for name, config in BACKENDS.items()
        },
    }
    if executable:
        try:
            completed = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            result["version"] = completed.stdout.strip()
        except (OSError, subprocess.SubprocessError) as error:
            result["available"] = False
            result["error"] = str(error)
    return result


def create_aider_handoff(brain: ProjectBrain, task: str, limit: int = 5) -> dict:
    routing = prepare_profile_handoff(brain, task, limit)
    handoff = brain.directory / "research" / "AIDER_HANDOFF.md"
    specialist_text = Path(routing["handoff_path"]).read_text(encoding="utf-8")
    handoff.write_text(
        "# Aider Bounded Work Handoff\n\n"
        f"## Task\n\n{task.strip()}\n\n"
        "## Required behavior\n\n"
        "- Read the selected specialist handoff linked below.\n"
        "- Stay within the confirmed task and repository.\n"
        "- Do not access credentials or external services unless explicitly configured.\n"
        "- Do not use prohibited models.\n"
        "- Run focused tests and report evidence, changed files, and remaining risks.\n"
        "- The user or primary supervising model gives the final green signal.\n\n"
        f"## Specialist handoff\n\n{specialist_text}\n",
        encoding="utf-8",
    )
    append_journey(
        brain,
        "Aider Handoff Prepared",
        [f"Task: {task.strip()}", f"Handoff: {handoff.name}"],
    )
    return {
        "task": task.strip(),
        "handoff": str(handoff),
        "specialist_handoff": routing["handoff_path"],
        "selected_profiles": [profile["name"] for profile in routing["selected"]],
        "context": routing["context"],
    }


def build_aider_command(
    brain: ProjectBrain,
    task: str,
    backend: str,
    model: str,
    *,
    dry_run: bool = True,
    limit: int = 5,
) -> dict:
    if backend not in BACKENDS:
        raise GuardianError(f"Unknown Aider backend {backend!r}; use: {', '.join(BACKENDS)}")
    require_model_allowed(model)
    if not task.strip():
        raise GuardianError("Aider task must not be empty.")
    executable = _aider_path()
    if not executable:
        raise GuardianError("Aider is not installed or not available on PATH.")
    config = BACKENDS[backend]
    handoff = create_aider_handoff(brain, task, limit)
    audit_dir = brain.directory / "audit"
    audit_dir.mkdir(exist_ok=True)
    command = [
        executable,
        "--no-analytics",
        "--no-auto-commits",
        "--no-gitignore",
        "--map-tokens",
        "0",
        "--input-history-file",
        str(audit_dir / "aider-input.history"),
        "--chat-history-file",
        str(audit_dir / "aider-chat.history.md"),
        "--llm-history-file",
        str(audit_dir / "aider-llm.history.md"),
        "--openai-api-base",
        config["base_url"],
        "--model",
        f"openai/{model}",
        "--read",
        handoff["handoff"],
        "--message",
        task.strip(),
    ]
    if dry_run:
        command.append("--dry-run")
    return {
        "backend": backend,
        "model": model,
        "dry_run": dry_run,
        "command": command,
        "credential_env": config["credential_env"],
        "handoff": handoff,
    }


def launch_aider(
    brain: ProjectBrain,
    task: str,
    backend: str,
    model: str,
    *,
    dry_run: bool = True,
    limit: int = 5,
) -> int:
    launch = build_aider_command(brain, task, backend, model, dry_run=dry_run, limit=limit)
    config = BACKENDS[backend]
    if not _port_open(config["host"], config["port"]):
        raise GuardianError(f"Aider backend {backend!r} is not reachable at {config['base_url']}.")
    child_env = dict(os.environ)
    credential_env = config["credential_env"]
    if credential_env:
        credential = child_env.get(credential_env)
        if not credential and config["credential_required"]:
            raise GuardianError(
                f"Aider backend {backend!r} requires {credential_env}; configure it locally without saving it in the repository."
            )
        child_env["OPENAI_API_KEY"] = credential or f"local-{backend}"
    else:
        child_env.setdefault("OPENAI_API_KEY", "local-ollama")
    append_journey(
        brain,
        "Aider Session Launched",
        [f"Backend: {backend}", f"Model: {model}", f"Dry run: {dry_run}"],
    )
    return subprocess.run(
        launch["command"],
        cwd=str(brain.root),
        env=child_env,
        check=False,
    ).returncode
