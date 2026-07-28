"""Hermes safe adapter — optional learning/research worker (Phase 5 & 6).

Hermes is an MIT-licensed autonomous AI agent framework by Nous Research
(https://github.com/NousResearch/Hermes). Guardian integrates it as an optional
replaceable bounded worker for research, planning, skill-evaluation, and summary
tasks — never as Guardian's policy authority or mandatory runtime dependency.

Phase 5 boundaries enforced by this adapter:

- Binary/version detection only — never installs or configures Hermes.
- "Tools disabled" profile — only compact research, planning, skill-evaluation,
  and summary tasks are allowed.
- Hermes memory is kept strictly separate from Guardian memory.
- Only user-approved, sanitized lessons may be imported into Guardian.
- No messaging gateway, browser, MCP, scheduling, OAuth, or credential import.
- Telemetry disabled by default for Guardian-launched sessions.

Phase 6 — Controlled background work:

- Guardian-scheduled tasks only after explicit user approval.
- Task types limited to: health-check, research-summary, skill-evaluation,
  maintenance-proposal.
- All external actions, browser use, payments, publishing, and account activity
  blocked by default.
- Human/primary-model review required for any change proposal.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc, render_context


# Hermes restrictions enforced by the adapter.
_HERMES_RESTRICTIONS = [
    "no-install",
    "no-login",
    "no-oauth",
    "no-provider-setup",
    "no-credential-import",
    "no-browser",
    "no-mcp",
    "no-swarm",
    "no-self-development",
    "no-commit-push",
    "no-messaging-gateway",
    "no-scheduling",
    "no-external-actions",
]

# Allowed task types for Hermes execution (tools-disabled profile).
_ALLOWED_TASK_TYPES = frozenset({
    "research",
    "planning",
    "skill-evaluation",
    "summary",
})

# Phase 6 — Allowed scheduled task types.
_ALLOWED_SCHEDULED_TASK_TYPES = frozenset({
    "health-check",
    "research-summary",
    "skill-evaluation",
    "maintenance-proposal",
})

_HERMES_SCHEDULE_FILE = "hermes_schedule.json"
_HERMES_CONSENT_FILE = "hermes_consent.json"
_HERMES_MEMORY_DIR = "hermes_memory"


def _hermes_path() -> str | None:
    """Locate the Hermes binary on PATH."""
    return shutil.which("hermes")


def _timeout_version(executable: str, timeout: int = 15) -> str | None:
    """Read Hermes version with a bounded timeout.

    Args:
        executable: Path to the Hermes binary.
        timeout: Maximum seconds to wait for version output.

    Returns:
        Version string, or None if the command fails or times out.
    """
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if completed.returncode == 0:
            return completed.stdout.strip()
        return None
    except (OSError, subprocess.SubprocessError):
        return None


def hermes_status() -> dict:
    """Detect Hermes binary and read version with timeout.

    Returns:
        Dict with:
        - available: bool
        - executable: str or None
        - version: str or None
        - restrictions: list of enforced restriction labels
    """
    executable = _hermes_path()
    if not executable:
        return {
            "available": False,
            "executable": None,
            "version": None,
            "message": "Hermes binary was not found on PATH.",
            "restrictions": list(_HERMES_RESTRICTIONS),
        }

    version = _timeout_version(executable)
    if version is None:
        return {
            "available": False,
            "executable": executable,
            "version": None,
            "message": "Hermes binary found but version check failed or timed out.",
            "restrictions": list(_HERMES_RESTRICTIONS),
        }

    return {
        "available": True,
        "executable": executable,
        "version": version,
        "message": "Hermes binary detected and version read successfully.",
        "restrictions": list(_HERMES_RESTRICTIONS),
    }


# ---------------------------------------------------------------------------
# Phase 5 — Memory isolation
# ---------------------------------------------------------------------------

def _hermes_memory_path(brain: ProjectBrain) -> Path:
    """Get the isolated Hermes memory directory (separate from Guardian memory)."""
    mem_path = brain.directory / _HERMES_MEMORY_DIR
    mem_path.mkdir(parents=True, exist_ok=True)
    return mem_path


def list_hermes_memory(brain: ProjectBrain) -> dict:
    """List files in the isolated Hermes memory directory.

    Hermes memory is kept strictly separate from Guardian memory. Nothing
    is automatically imported into Guardian's learning library.

    Returns:
        Dict with memory file count and file names.
    """
    mem_path = _hermes_memory_path(brain)
    files = []
    for item in sorted(mem_path.iterdir()):
        if item.is_file():
            mtime = item.stat().st_mtime
            files.append({
                "name": item.name,
                "size": item.stat().st_size,
                "modified": time.ctime(mtime),
            })
    return {
        "memory_path": str(mem_path),
        "file_count": len(files),
        "files": files,
        "note": (
            "Hermes memory is isolated from Guardian memory. "
            "Use 'hermes import-lesson' to import a sanitized, user-approved lesson."
        ),
    }


def import_hermes_lesson(
    brain: ProjectBrain,
    source_file: str,
    *,
    sanitized_pattern: str,
    sanitized_prevention: str,
    tags: list[str],
    library_path: Path | None = None,
) -> dict:
    """Import a user-approved, sanitized lesson from Hermes memory into Guardian's learning library.

    This is the ONLY way Hermes learning enters Guardian memory. The lesson
    must be sanitized (reviewed by the user) before import. Raw Hermes memory
    is never automatically imported.

    Args:
        brain: The project brain.
        source_file: Name of the file in Hermes memory to import from.
        sanitized_pattern: User-approved sanitized pattern string.
        sanitized_prevention: User-approved sanitized prevention check.
        tags: List of tags for categorization.
        library_path: Optional custom learning library path.

    Returns:
        Dict with import result including the reusable lesson ID.

    Raises:
        GuardianError: If source file not found, or content is invalid.
    """
    from guardian_agent.learning import (
        _clean_reusable_text,
        _clean_tags,
        learning_library_path,
        _load_library,
        _save_library,
        _library_lock,
    )

    mem_path = _hermes_memory_path(brain)
    source = mem_path / source_file

    if not source.is_file():
        raise GuardianError(
            f"Hermes memory file {source_file!r} not found in {mem_path}."
        )

    # Validate sanitized content (not raw Hermes output)
    clean_pattern = _clean_reusable_text(sanitized_pattern, "Sanitized pattern", 500)
    clean_prevention = _clean_reusable_text(sanitized_prevention, "Sanitized prevention", 500)
    clean_tags = _clean_tags(tags)

    path = learning_library_path(library_path)
    with _library_lock(path):
        payload = _load_library(path)
        record = {
            "id": f"hermes-import-{uuid.uuid4().hex[:12]}",
            "pattern": clean_pattern,
            "prevention": clean_prevention,
            "tags": clean_tags,
            "created_at": now_utc(),
            "source": source_file,
            "provenance": "hermes-sanitized-user-approved",
        }
        payload["lessons"].append(record)
        _save_library(path, payload)

    append_journey(
        brain,
        "Hermes Lesson Imported",
        [
            f"Source: {source_file}",
            f"Reusable lesson: {record['id']}",
            f"Tags: {', '.join(clean_tags)}",
            "Only the user-supplied sanitized pattern and prevention were imported.",
        ],
    )

    return {
        "status": "imported",
        "lesson_id": record["id"],
        "library": str(path),
        "source": source_file,
    }


# ---------------------------------------------------------------------------
# Phase 5 — Consent and execution
# ---------------------------------------------------------------------------

def hermes_opt_in(brain: ProjectBrain) -> dict:
    """Record explicit user opt-in to Hermes execution for this project.

    Hermes execution is blocked until the user explicitly runs this function.
    The consent is stored in the project's .agent/ directory and can be
    revoked by deleting the consent file.

    Args:
        brain: The project brain.

    Returns:
        Dict with the consent status.
    """
    consent_path = brain.directory / _HERMES_CONSENT_FILE
    if consent_path.is_file():
        return {
            "status": "already_opted_in",
            "message": "Hermes execution is already opted in for this project.",
            "consent_path": str(consent_path),
        }

    consent = {
        "opted_in": True,
        "opted_in_at": now_utc(),
        "project": str(brain.root),
        "tools_disabled": True,
        "phase5_only": True,
    }
    consent_path.write_text(json.dumps(consent, indent=2) + "\n", encoding="utf-8")

    append_journey(
        brain,
        "Hermes Execution Opted In",
        [
            "Explicit user opt-in recorded for Hermes controlled execution.",
            "Tools-disabled profile active.",
        ],
    )

    return {
        "status": "opted_in",
        "message": (
            "Hermes execution is now enabled for this project with a tools-disabled profile. "
            "Use 'guardian hermes run' to execute bounded research/learning tasks."
        ),
        "consent_path": str(consent_path),
    }


def hermes_is_opted_in(brain: ProjectBrain) -> bool:
    """Check whether Hermes execution has been explicitly opted in."""
    consent_path = brain.directory / _HERMES_CONSENT_FILE
    if not consent_path.is_file():
        return False
    try:
        consent = json.loads(consent_path.read_text(encoding="utf-8"))
        return bool(consent.get("opted_in", False))
    except (OSError, json.JSONDecodeError, ValueError):
        return False


def create_hermes_handoff(
    brain: ProjectBrain,
    task: str,
    task_type: str = "research",
    *,
    read_paths: list[str] | None = None,
) -> dict:
    """Build a compact tools-disabled Hermes handoff for research/learning tasks.

    This function creates the handoff file but does **not** execute Hermes.
    The handoff enforces a tools-disabled profile — only observation, analysis,
    and summarization are allowed. No browser, file writes, or external actions.

    Args:
        brain: The project brain.
        task: The confirmed task description.
        task_type: Type of task (research, planning, skill-evaluation, summary).
        read_paths: Optional paths Hermes may read (never write).

    Returns:
        Handoff metadata including the handoff file path.

    Raises:
        GuardianError: If the task is empty or task_type is not allowed.
    """
    clean_task = task.strip()
    if not clean_task:
        raise GuardianError("A non-empty task is required for Hermes handoff.")

    clean_type = task_type.lower().strip()
    if clean_type not in _ALLOWED_TASK_TYPES:
        raise GuardianError(
            f"Unsupported Hermes task type {task_type!r}. "
            f"Allowed: {', '.join(sorted(_ALLOWED_TASK_TYPES))}."
        )

    # Build the handoff document with tools-disabled profile
    context = render_context(brain)
    handoff_dir = brain.directory / "research"
    handoff_dir.mkdir(exist_ok=True)
    handoff_path = handoff_dir / "HERMES_HANDOFF.md"

    safe_paths = []
    path_found = read_paths or []
    # Filter to only existing valid paths
    for p in path_found:
        full = brain.root / p
        if full.exists():
            safe_paths.append(p)

    read_section = ""
    if safe_paths:
        read_lines = "\n".join(f"- `{p}`" for p in safe_paths)
        read_section = f"\n## Read paths (read-only)\n\n{read_lines}\n\nThese paths are available for reading only. No modifications allowed.\n"
    else:
        read_section = "\n## Read paths\n\n(None — use general project context.)\n"

    handoff_text = (
        "# Hermes Bounded Work Handoff\n\n"
        f"## Task: {clean_type}\n\n"
        f"## Instructions\n\n"
        f"{clean_task}\n\n"
        "## Tools-disabled profile\n\n"
        "This Hermes session runs with tools DISABLED. The following are strictly prohibited:\n\n"
        + "\n".join(f"- `{r}`" for r in _HERMES_RESTRICTIONS)
        + "\n\n"
        "## Permitted actions\n\n"
        "- Read compact project context and listed files.\n"
        "- Analyze, research, plan, evaluate skills, or summarize.\n"
        "- Store output in Hermes isolated memory (no automatic import to Guardian).\n"
        "- May produce a structured markdown report in the project artifacts.\n"
        f"{read_section}"
        "## Not permitted\n\n"
        "- Write to any project file outside Hermes memory.\n"
        "- Access credentials, vault, .env files, or account secrets.\n"
        "- Use browser, messaging, scheduling, MCP tools, or swarm spawning.\n"
        "- Install software, configure providers, or log in to services.\n"
        "- Modify Guardian policy, project brain, or worker configuration.\n"
        "- Commit or push changes.\n\n"
        "## Restrictions (enforced by Guardian)\n\n"
        + "\n".join(f"- `{r}`" for r in _HERMES_RESTRICTIONS)
        + "\n\n## Compact project context\n\n"
        f"{context}\n"
    )
    handoff_path.write_text(handoff_text, encoding="utf-8")

    append_journey(
        brain,
        "Hermes Handoff Prepared",
        [
            f"Task: {clean_task[:100]}",
            f"Type: {clean_type}",
            f"Handoff: {handoff_path.name}",
            "Tools-disabled profile enforced.",
        ],
    )

    return {
        "task": clean_task,
        "task_type": clean_type,
        "handoff": str(handoff_path),
        "read_paths": safe_paths,
        "restrictions": list(_HERMES_RESTRICTIONS),
        "instruction": (
            "Dry-run handoff prepared. Hermes has NOT been executed. "
            "The handoff enforces a tools-disabled profile — no browser, "
            "no external actions, no file writes outside Hermes memory. "
            f"Review the handoff at: {handoff_path}"
        ),
    }


def execute_hermes_task(
    brain: ProjectBrain,
    task: str,
    task_type: str = "research",
    read_paths: list[str] | None = None,
    *,
    timeout: int = 300,
) -> dict:
    """Execute a bounded Hermes task with tools-disabled profile.

    Phase 5 controlled execution:
    1. Requires explicit user opt-in per project (hermes_opt_in).
    2. Task type must be one of the allowed types.
    3. Generates a tools-disabled handoff — no browser, MCP, or external actions.
    4. Captures stdout, stderr, exit code, and timing.
    5. Stores output in isolated Hermes memory (separate from Guardian).
    6. Returns a structured result for user review.

    Args:
        brain: The project brain.
        task: The confirmed task description.
        task_type: Type of task (research, planning, skill-evaluation, summary).
        read_paths: Optional read-only paths Hermes may refer to.
        timeout: Maximum seconds for Hermes execution (default 300s=5min).

    Returns:
        Dict with execution results including stdout, stderr, Hermes memory files.

    Raises:
        GuardianError: If opt-in not granted, binary not found, or execution fails.
    """
    # 1. Fail-closed: execution is disabled until a verified sandboxed
    #    execution backend exists. Environment variables alone cannot
    #    guarantee Hermes cannot use tools, configure gateways, access
    #    credentials, or write files. See:
    #    https://github.com/NousResearch/Hermes
    raise GuardianError(
        "Hermes execution is disabled by default. The current adapter sets "
        "environment variables (HERMES_TOOLS_DISABLED) but does not have "
        "a verified sandboxed execution backend. Environment variables "
        "alone cannot guarantee Hermes cannot use tools, configure "
        "gateways, MCP, messaging, OAuth, or write files. A sandboxed "
        "execution backend (worktree, restricted environment, no vault/"
        ".env/credentials/browser/MCP/messaging configuration, post-run "
        "diff validation, fail-closed capability verification) must be "
        "implemented before enabling guardian hermes run."
    )

    # 2. Verify explicit user opt-in (kept for when execution is re-enabled)
    if not hermes_is_opted_in(brain):
        raise GuardianError(
            "Hermes execution requires explicit user opt-in. "
            "Run 'guardian hermes opt-in' first."
        )

    # 3. Find Hermes binary
    executable = _hermes_path()
    if not executable:
        raise GuardianError(
            "Hermes binary was not found on PATH. "
            "Install Hermes from https://github.com/NousResearch/Hermes "
            "or ensure it is on PATH."
        )

    clean_task = task.strip()
    if not clean_task:
        raise GuardianError("A non-empty task is required.")

    clean_type = task_type.lower().strip()
    if clean_type not in _ALLOWED_TASK_TYPES:
        raise GuardianError(
            f"Unsupported Hermes task type {task_type!r}. "
            f"Allowed: {', '.join(sorted(_ALLOWED_TASK_TYPES))}."
        )

    # 3. Validate timeout
    if timeout < 10 or timeout > 3600:
        raise GuardianError("timeout must be between 10 and 3600 seconds.")

    # 4. Prepare handoff
    handoff_data = create_hermes_handoff(brain, clean_task, clean_type, read_paths=read_paths)
    handoff_path = handoff_data["handoff"]

    start_time = time.time()
    mem_path = _hermes_memory_path(brain)
    output_file = mem_path / f"{clean_type}_{uuid.uuid4().hex[:8]}.md"

    try:
        # 5. Build and execute Hermes command
        hermes_command = [
            executable,
            "--read", handoff_path,
            "--message", f"[{clean_type}] {clean_task}",
        ]

        child_env = dict(os.environ)
        child_env["HERMES_TOOLS_DISABLED"] = "1"
        child_env["HERMES_NO_TELEMETRY"] = "1"
        child_env.pop("HERMES_API_KEY", None)
        child_env.pop("HERMES_AUTH_TOKEN", None)
        child_env.pop("HERMES_MESSAGING_TOKEN", None)

        result = subprocess.run(
            hermes_command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(brain.root),
            env=child_env,
        )
        elapsed = time.time() - start_time

        execution = {
            "exit_code": result.returncode,
            "stdout": result.stdout[:10000],
            "stderr": result.stderr[:5000],
            "timed_out": False,
            "elapsed_seconds": round(elapsed, 2),
        }

        # Save Hermes output to isolated memory
        output_content = (
            f"# Hermes Output: {clean_type}\n\n"
            f"## Task\n{clean_task}\n\n"
            f"## Standard output\n```\n{result.stdout[:5000]}\n```\n\n"
            f"## Standard error\n```\n{result.stderr[:2000]}\n```\n\n"
            f"## Exit code\n{result.returncode}\n\n"
            f"_Generated at {now_utc()}_\n"
        )
        output_file.write_text(output_content, encoding="utf-8")

    except subprocess.TimeoutExpired:
        elapsed = timeout
        execution = {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Hermes execution timed out after {timeout} seconds.",
            "timed_out": True,
            "elapsed_seconds": timeout,
        }
        output_file.write_text(
            f"# Hermes Output: {clean_type}\n\n"
            f"## Task\n{clean_task}\n\n"
            f"_Execution timed out after {timeout} seconds._\n",
            encoding="utf-8",
        )

        append_journey(
            brain,
            "Hermes Execution Timed Out",
            [f"Task: {clean_task[:100]}...", f"Timeout: {timeout}s"],
        )

    except (OSError, subprocess.SubprocessError) as error:
        execution = {
            "exit_code": -1,
            "stdout": "",
            "stderr": str(error),
            "timed_out": False,
            "elapsed_seconds": round(time.time() - start_time, 2),
        }
        output_file.write_text(
            f"# Hermes Output: {clean_type}\n\n"
            f"## Task\n{clean_task}\n\n"
            f"_Execution failed: {error}_\n",
            encoding="utf-8",
        )

    append_journey(
        brain,
        "Hermes Execution Completed",
        [
            f"Task: {clean_task[:100]}...",
            f"Type: {clean_type}",
            f"Exit code: {execution['exit_code']}",
            f"Output saved to Hermes memory: {output_file.name}",
            f"Elapsed: {execution['elapsed_seconds']}s",
        ],
    )

    return {
        "task": clean_task,
        "task_type": clean_type,
        "execution": execution,
        "memory_output": str(output_file),
        "memory_path": str(mem_path),
        "restrictions": list(_HERMES_RESTRICTIONS),
        "note": (
            "Hermes output stored in isolated memory. "
            "It is NOT automatically imported into Guardian's learning library. "
            "Use 'guardian hermes import-lesson' after user review to import "
            "a sanitized lesson."
        ),
    }


# ---------------------------------------------------------------------------
# Phase 6 — Controlled background work
# ---------------------------------------------------------------------------

_SCHEDULE_FILE_VERSION = 1


def _schedule_path(brain: ProjectBrain) -> Path:
    return brain.directory / _HERMES_SCHEDULE_FILE


def _load_schedule(brain: ProjectBrain) -> dict:
    path = _schedule_path(brain)
    if not path.is_file():
        return {
            "version": _SCHEDULE_FILE_VERSION,
            "created_at": now_utc(),
            "tasks": [],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload.get("tasks"), list):
            raise GuardianError("Invalid Hermes schedule: tasks must be a list.")
        return payload
    except (OSError, json.JSONDecodeError) as error:
        raise GuardianError(f"Invalid Hermes schedule: {error}") from error


def _save_schedule(brain: ProjectBrain, payload: dict) -> None:
    path = _schedule_path(brain)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def hermes_schedule_task(
    brain: ProjectBrain,
    task_type: str,
    task_description: str,
    interval_seconds: int,
    *,
    approval_id: str,
) -> dict:
    """Add a Guardian-scheduled Hermes task (Phase 6).

    Only allowed task types: health-check, research-summary, skill-evaluation,
    maintenance-proposal.

    Requires explicit user approval via an approval_id.

    Args:
        brain: The project brain.
        task_type: Type of scheduled task.
        task_description: Description of the task.
        interval_seconds: Interval between executions (minimum 300s/5min).
        approval_id: User-approved approval ID.

    Returns:
        Dict with the scheduled task details.

    Raises:
        GuardianError: If task type is not allowed, interval too short,
                       or approval not granted.
    """
    clean_type = task_type.lower().strip()
    if clean_type not in _ALLOWED_SCHEDULED_TASK_TYPES:
        raise GuardianError(
            f"Unsupported scheduled task type {task_type!r}. "
            f"Allowed: {', '.join(sorted(_ALLOWED_SCHEDULED_TASK_TYPES))}."
        )

    if interval_seconds < 300:
        raise GuardianError("Scheduled Hermes tasks must have an interval of at least 300 seconds (5 minutes).")

    if interval_seconds > 86400 * 7:
        raise GuardianError("Scheduled Hermes tasks must have an interval of at most 7 days.")

    # Verify approval was consumed
    from guardian_agent.policy import consume_action_approval
    consume_action_approval(
        brain,
        approval_id,
        "hermes_schedule",
        f"hermes:{clean_type}",
    )

    payload = _load_schedule(brain)
    now_epoch = time.time()

    task_record = {
        "id": f"hermes-sched-{uuid.uuid4().hex[:10]}",
        "type": clean_type,
        "description": task_description,
        "interval_seconds": interval_seconds,
        "enabled": True,
        "created_at": now_utc(),
        "approval_id": approval_id,
        "last_run_epoch": None,
        "next_run_epoch": now_epoch + interval_seconds,
        "failure_count": 0,
        "last_status": "never",
        "last_error": None,
    }
    payload["tasks"].append(task_record)
    _save_schedule(brain, payload)

    append_journey(
        brain,
        "Hermes Scheduled Task Added",
        [
            f"Type: {clean_type}",
            f"Interval: {interval_seconds}s",
            f"Approval: {approval_id}",
        ],
    )

    return task_record


def hermes_list_scheduled(brain: ProjectBrain) -> dict:
    """List all scheduled Hermes tasks with their status.

    Returns:
        Dict with task count and task details.
    """
    payload = _load_schedule(brain)
    now_epoch = time.time()
    tasks = [
        {
            **task,
            "due": bool(
                task.get("enabled", True)
                and task.get("next_run_epoch") is not None
                and float(task["next_run_epoch"]) <= now_epoch
            ),
        }
        for task in payload["tasks"]
    ]
    return {
        "created_at": payload.get("created_at"),
        "task_count": len(tasks),
        "due_count": sum(1 for t in tasks if t["due"]),
        "tasks": tasks,
    }


def hermes_unschedule_task(brain: ProjectBrain, task_id: str) -> dict:
    """Disable a scheduled Hermes task.

    Args:
        brain: The project brain.
        task_id: The ID of the scheduled task to disable.

    Returns:
        Dict with the task ID and new status.

    Raises:
        GuardianError: If task ID is not found.
    """
    payload = _load_schedule(brain)
    task = next(
        (t for t in payload["tasks"] if t.get("id") == task_id),
        None,
    )
    if task is None:
        raise GuardianError(f"Scheduled task {task_id!r} not found.")

    task["enabled"] = False
    task["last_status"] = "disabled"
    _save_schedule(brain, payload)

    return {
        "task_id": task_id,
        "status": "disabled",
        "message": f"Scheduled task {task_id!r} has been disabled.",
    }


def hermes_run_due_tasks(
    brain: ProjectBrain,
    *,
    max_tasks: int = 5,
    force: bool = False,
    task_type_filter: str | None = None,
) -> dict:
    """Run due scheduled Hermes tasks (Phase 6).

    Only executes tasks that are:
    - Enabled
    - Past their next_run_epoch (or force=True)
    - Of an allowed type (health-check, research-summary, skill-evaluation, maintenance-proposal)
    - Filtered by optional task_type_filter

    All external actions, browser use, payments, publishing, and account
    activity are blocked by default. Results are stored in Hermes memory
    for later review by a human or primary model.

    Args:
        brain: The project brain.
        max_tasks: Maximum tasks to execute in this run (default 5, max 10).
        force: If True, run all enabled tasks regardless of schedule.
        task_type_filter: Optional filter to run only a specific task type.

    Returns:
        Dict with execution results and summary.
    """
    if max_tasks < 1 or max_tasks > 10:
        raise GuardianError("max_tasks must be between 1 and 10.")

    payload = _load_schedule(brain)
    now_epoch = time.time()

    # Find due tasks
    due = []
    for task in payload["tasks"]:
        if not task.get("enabled", True):
            continue
        if task_type_filter and task.get("type") != task_type_filter:
            continue
        if force or (
            task.get("next_run_epoch") is not None
            and float(task["next_run_epoch"]) <= now_epoch
        ):
            due.append(task)

    due = due[:max_tasks]

    if not due:
        return {
            "executed": 0,
            "message": "No due Hermes tasks to run.",
            "records": [],
        }

    records = []
    for task in due:
        started = time.monotonic()
        task_id = task.get("id", "unknown")
        task_type = task.get("type", "unknown")
        description = task.get("description", "")

        try:
            # Execute the scheduled task via the Hermes adapter
            result = execute_hermes_task(
                brain,
                task=description or f"Scheduled {task_type} check",
                task_type=_map_scheduled_to_allowed(task_type),
                timeout=120,  # Shorter timeout for scheduled tasks
            )

            task["failure_count"] = 0
            task["last_status"] = "passed"
            task["last_error"] = None
            delay = int(task["interval_seconds"])
            status = "passed"

            # Scheduled tasks NEVER result in automatic changes.
            # Results are stored in Hermes memory for review.
            records.append({
                "task_id": task_id,
                "type": task_type,
                "status": status,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "memory_output": result.get("memory_output"),
                "next_run_epoch": now_epoch + delay,
                "change_proposed": False,
                "note": "Result stored in Hermes memory. Human/primary-model review required for any change proposal.",
            })

        except Exception as error:
            task["failure_count"] = int(task.get("failure_count", 0)) + 1
            task["last_status"] = "failed"
            task["last_error"] = str(error)[:500]
            delay = min(86400, 60 * (2 ** min(task["failure_count"] - 1, 10)))
            status = "failed"

            records.append({
                "task_id": task_id,
                "type": task_type,
                "status": status,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "next_run_epoch": now_epoch + delay,
                "change_proposed": False,
                "error": str(error)[:200],
            })

        task["last_run_epoch"] = now_epoch
        task["next_run_epoch"] = now_epoch + delay

    _save_schedule(brain, payload)

    return {
        "executed": len(records),
        "records": records,
        "note": (
            "No external actions, browser use, payments, publishing, or account "
            "activity were performed. Results are stored in Hermes memory for "
            "human/primary-model review."
        ),
    }


def _map_scheduled_to_allowed(scheduled_type: str) -> str:
    """Map a scheduled task type to an allowed Phase 5 task type."""
    mapping = {
        "health-check": "summary",
        "research-summary": "summary",
        "skill-evaluation": "skill-evaluation",
        "maintenance-proposal": "planning",
    }
    return mapping.get(scheduled_type, "research")
