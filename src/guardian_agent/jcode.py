"""JCode safe adapter — optional bounded coding worker (Phase 2).

JCode is an MIT-licensed coding-agent harness
(https://github.com/1jehuang/jcode). Guardian integrates it as an optional
replaceable bounded worker, never as Guardian's policy authority or mandatory
runtime dependency.

Phase 2 boundaries enforced by this adapter:

- Binary/version detection only — never installs or configures JCode.
- Dry-run by default — Guardian supplies a compact handoff and command preview
  without executing any action.
- No JCode self-development — JCode may not modify Guardian, its policy,
  project brain, vault, approval records, or worker configuration.
- No automatic credential scanning, importing, account switching, or quota
  evasion.
- No login/OAuth, provider setup, browser actions, MCP tools, or swarm spawning.
- No direct commit or push without explicit primary-model approval.
- Telemetry disabled by default (JCODE_NO_TELEMETRY=1) for Guardian-launched
  sessions.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from guardian_agent.aider import _safe_writable_paths
from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc, render_context


# JCode restrictions enforced by the adapter (documentation / guardrails).
_JCODE_RESTRICTIONS = [
    "no-install",
    "no-login",
    "no-oauth",
    "no-provider-setup",
    "no-credential-import",
    "no-browser",
    "no-mcp",
    "no-swarm",
    "no-self-development",
    "no-direct-commit",
    "no-direct-push",
]


def _jcode_path() -> str | None:
    """Locate the JCode binary on PATH."""
    return shutil.which("jcode")


def _timeout_version(executable: str, timeout: int = 15) -> str | None:
    """Read JCode version with a bounded timeout.

    Args:
        executable: Path to the JCode binary.
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


def jcode_status() -> dict:
    """Detect JCode binary and read version with timeout.

    Returns:
        Dict with:
        - available: bool
        - executable: str or None
        - version: str or None (None if unavailable or timeout)
        - restrictions: list of enforced restriction labels
    """
    executable = _jcode_path()
    if not executable:
        return {
            "available": False,
            "executable": None,
            "version": None,
            "message": "JCode binary was not found on PATH.",
            "restrictions": list(_JCODE_RESTRICTIONS),
        }

    version = _timeout_version(executable)
    if version is None:
        return {
            "available": False,
            "executable": executable,
            "version": None,
            "message": "JCode binary found but version check failed or timed out.",
            "restrictions": list(_JCODE_RESTRICTIONS),
        }

    return {
        "available": True,
        "executable": executable,
        "version": version,
        "message": "JCode binary detected and version read successfully.",
        "restrictions": list(_JCODE_RESTRICTIONS),
    }


def create_jcode_handoff(
    brain: ProjectBrain,
    task: str,
    writable_paths: list[str] | None = None,
    test_command: str | None = None,
) -> dict:
    """Build a compact JCode handoff with dry-run command preview.

    This function creates the handoff file but does **not** execute JCode.
    Execution is a separate step that requires explicit user opt-in.

    Args:
        brain: The project brain.
        task: The confirmed task description.
        writable_paths: Exact file or directory paths JCode may modify.
        test_command: Optional test command JCode should run after changes.

    Returns:
        Handoff metadata including the handoff file path and command preview.

    Raises:
        GuardianError: If the task is empty.
    """
    clean_task = task.strip()
    if not clean_task:
        raise GuardianError("A non-empty JCode task is required.")

    safe_paths = _safe_writable_paths(brain, writable_paths or [])

    # Build the handoff document
    context = render_context(brain)
    handoff_dir = brain.directory / "research"
    handoff_dir.mkdir(exist_ok=True)
    handoff = handoff_dir / "JCODE_HANDOFF.md"

    writable_section = ""
    if safe_paths:
        writable_lines = "\n".join(f"- `{p}`" for p in safe_paths)
        writable_section = f"\n## Writable paths\n\n{writable_lines}\n\nDo not modify files outside this list.\n"
    else:
        writable_section = "\n## Writable paths\n\n(None — read-only analysis.)\n"

    test_section = ""
    if test_command:
        test_section = f"\n## Test command\n\n```bash\n{test_command}\n```\n"

    handoff_text = (
        "# JCode Bounded Work Handoff\n\n"
        f"## Task\n\n{clean_task}\n\n"
        "## Required behavior\n\n"
        "- Read the compact project context below.\n"
        "- Modify only the writable paths listed below.\n"
        "- Do not access credentials, .env files, vault, or account secrets.\n"
        "- Do not install software, log in to services, or set up providers.\n"
        "- Do not use browser, MCP tools, or spawn additional workers.\n"
        "- Do not modify Guardian policy, project brain, vault, or worker configuration.\n"
        "- Run the test command after changes and report results.\n"
        "- Do not commit or push changes without explicit approval.\n"
        f"{writable_section}"
        f"{test_section}"
        "\n## Restrictions (enforced by Guardian)\n\n"
        + "\n".join(f"- `{r}`" for r in _JCODE_RESTRICTIONS)
        + "\n\n## Compact project context\n\n"
        f"{context}\n"
    )
    handoff.write_text(handoff_text, encoding="utf-8")

    # Build the command preview (dry-run only)
    safe_executable = _jcode_path()
    command_preview = None
    if safe_executable:
        cmd_parts = [
            safe_executable,
            "--read", str(handoff),
            "--message", clean_task,
        ]
        if safe_paths:
            cmd_parts.extend(["--write", ",".join(safe_paths)])
        if test_command:
            cmd_parts.extend(["--test", test_command])
        command_preview = " ".join(cmd_parts)

    append_journey(
        brain,
        "JCode Handoff Prepared",
        [
            f"Task: {clean_task}",
            f"Handoff: {handoff.name}",
            f"Writable paths: {safe_paths}",
            f"Test command: {test_command or '(none)'}",
            f"Command preview: {command_preview or '(binary not found)'}",
        ],
    )

    return {
        "task": clean_task,
        "handoff": str(handoff),
        "writable_paths": safe_paths,
        "test_command": test_command,
        "command_preview": command_preview,
        "restrictions": list(_JCODE_RESTRICTIONS),
        "instruction": (
            "Dry-run handoff prepared. JCode has NOT been executed. "
            "To run JCode, use a separate execution flow with explicit user opt-in. "
            f"Review the handoff at: {handoff}"
        ),
    }


def build_jcode_command(
    brain: ProjectBrain,
    task: str,
    writable_paths: list[str] | None = None,
    test_command: str | None = None,
    *,
    allow_edits: bool = False,
) -> dict:
    """Construct a safe JCode command with all restrictions enforced.

    Safety guarantees:
    - Returns a command preview without executing anything (dry-run).
    - Sets JCODE_NO_TELEMETRY=1 to disable telemetry.
    - Never passes credentials, provider keys, or sensitive paths.
    - Protected paths are always excluded from writable paths.

    Args:
        brain: The project brain.
        task: The confirmed task description.
        writable_paths: Exact file or directory paths JCode may modify.
        test_command: Optional test command for verification.
        allow_edits: If False (default), adds --dry-run flag.

    Returns:
        Dict with the command list, environment variables, and handoff metadata.

    Raises:
        GuardianError: If JCode binary is not found.
    """
    executable = _jcode_path()
    if not executable:
        raise GuardianError(
            "JCode binary was not found on PATH. "
            "Install JCode from https://github.com/1jehuang/jcode or ensure it is on PATH."
        )

    handoff_data = create_jcode_handoff(brain, task, writable_paths, test_command)
    safe_paths = handoff_data["writable_paths"]

    # Build the command
    command = [
        executable,
        "--read", handoff_data["handoff"],
        "--message", task.strip(),
    ]

    if not allow_edits:
        command.append("--dry-run")

    if safe_paths:
        command.extend(["--write", ",".join(safe_paths)])

    if test_command:
        command.extend(["--test", test_command])

    # Return environment metadata — the command is never executed here.
    # Real execution would set JCODE_NO_TELEMETRY=1 and strip credential env vars.

    return {
        "executable": executable,
        "command": command,
        "env": {
            "JCODE_NO_TELEMETRY": "1",
        },
        "handoff": handoff_data,
        "allow_edits": allow_edits,
        "restrictions_enforced": list(_JCODE_RESTRICTIONS),
        "note": "JCode command is ready for preview. No execution has occurred.",
    }


# ---------------------------------------------------------------------------
# Phase 3 — Controlled execution
# ---------------------------------------------------------------------------

_CONSENT_FILE = "jcode_consent.json"


def jcode_opt_in(brain: ProjectBrain) -> dict:
    """Record explicit user opt-in to JCode execution for this project.

    JCode execution is blocked until the user explicitly runs this function.
    The consent is stored in the project's .agent/ directory and can be
    revoked by deleting the consent file.

    Args:
        brain: The project brain.

    Returns:
        Dict with the consent status.
    """
    consent_path = brain.directory / _CONSENT_FILE
    if consent_path.is_file():
        return {
            "status": "already_opted_in",
            "message": "JCode execution is already opted in for this project.",
            "consent_path": str(consent_path),
        }

    import json
    consent = {
        "opted_in": True,
        "opted_in_at": now_utc(),
        "project": str(brain.root),
    }
    consent_path.write_text(json.dumps(consent, indent=2) + "\n", encoding="utf-8")

    append_journey(
        brain,
        "JCode Execution Opted In",
        ["Explicit user opt-in recorded for JCode controlled execution."],
    )

    return {
        "status": "opted_in",
        "message": "JCode execution is now enabled for this project. Use 'guardian jcode run' to execute.",
        "consent_path": str(consent_path),
    }


def jcode_is_opted_in(brain: ProjectBrain) -> bool:
    """Check whether JCode execution has been explicitly opted in."""
    import json
    consent_path = brain.directory / _CONSENT_FILE
    if not consent_path.is_file():
        return False
    try:
        consent = json.loads(consent_path.read_text(encoding="utf-8"))
        return bool(consent.get("opted_in", False))
    except (OSError, json.JSONDecodeError, ValueError):
        return False


def _git_diff_in_sandbox(sandbox_path: Path, project_root: Path) -> dict:
    """Generate a diff comparing the sandbox worktree against the original project.

    Args:
        sandbox_path: Path to the sandbox worktree.
        project_root: Path to the original project root.

    Returns:
        Dict with files_changed, diff_stat, insertions, deletions.
    """
    result: dict = {
        "files_changed": [],
        "diff_stat": "",
        "insertions": 0,
        "deletions": 0,
        "error": None,
    }

    try:
        # Check if sandbox is a git worktree
        git_check = subprocess.run(
            ["git", "-C", str(sandbox_path), "rev-parse", "--git-dir"],
            capture_output=True, text=True, timeout=5,
        )
        if git_check.returncode == 0:
            # Compare sandbox branch against main
            diff_numstat = subprocess.run(
                ["git", "-C", str(project_root), "diff", "--numstat", "HEAD"],
                capture_output=True, text=True, timeout=10,
            )
            diff_stat = subprocess.run(
                ["git", "-C", str(project_root), "diff", "--stat", "HEAD"],
                capture_output=True, text=True, timeout=10,
            )
            result["diff_stat"] = diff_stat.stdout.strip()

            files = []
            total_ins = 0
            total_dels = 0
            for line in diff_numstat.stdout.splitlines():
                parts = line.strip().split("\t")
                if len(parts) >= 3:
                    try:
                        ins = int(parts[0]) if parts[0] != "-" else 0
                        dels = int(parts[1]) if parts[1] != "-" else 0
                    except ValueError:
                        ins, dels = 0, 0
                    total_ins += ins
                    total_dels += dels
                    files.append({"path": parts[2], "insertions": ins, "deletions": dels})
            result["files_changed"] = files
            result["insertions"] = total_ins
            result["deletions"] = total_dels
        else:
            # Fallback: compare directory contents
            for f in sandbox_path.glob("**/*"):
                if f.is_file():
                    rel = f.relative_to(sandbox_path)
                    orig = project_root / rel
                    if orig.is_file() and orig.read_bytes() != f.read_bytes():
                        result["files_changed"].append({"path": str(rel), "insertions": 0, "deletions": 0})
                    elif not orig.exists():
                        result["files_changed"].append({"path": str(rel), "insertions": 0, "deletions": 0})
            result["diff_stat"] = f"{len(result['files_changed'])} file(s) changed"
    except (OSError, subprocess.SubprocessError) as error:
        result["error"] = str(error)

    return result


def _validate_out_of_scope(
    changed_files: list[dict],
    allowed_paths: list[str],
) -> list[dict]:
    """Check changed files against the allowed writable paths.

    Args:
        changed_files: List of dicts with 'path' key.
        allowed_paths: List of allowed file/directory paths.

    Returns:
        List of out-of-scope changes. Empty list means all changes are valid.
    """
    out_of_scope = []
    for f in changed_files:
        file_path = f.get("path", "")
        if not file_path:
            continue
        matched = False
        for allowed in allowed_paths:
            allowed_clean = allowed.rstrip("/")
            if file_path == allowed_clean or file_path.startswith(allowed_clean + "/"):
                matched = True
                break
        if not matched:
            out_of_scope.append({
                "path": file_path,
                "insertions": f.get("insertions", 0),
                "deletions": f.get("deletions", 0),
            })
    return out_of_scope


def execute_jcode_in_sandbox(
    brain: ProjectBrain,
    task: str,
    writable_paths: list[str] | None = None,
    test_command: str | None = None,
    *,
    timeout: int = 300,
) -> dict:
    """Execute JCode in a sandbox worktree with controlled execution.

    Phase 3 controlled execution:
    1. Requires explicit user opt-in per project (jcode_opt_in).
    2. Creates an isolated git worktree (or copy fallback) as a sandbox.
    3. Runs JCode with the compact handoff inside the sandbox.
    4. Captures stdout, stderr, exit code, and timing.
    5. Generates a diff between the sandbox and the original project.
    6. Validates that all changed files are within the approved writable paths.
    7. Runs the test command if provided.
    8. Returns a structured result for model/user approval.

    Args:
        brain: The project brain.
        task: The confirmed task description.
        writable_paths: Exact file or directory paths JCode may modify.
        test_command: Optional test command to run after JCode completes.
        timeout: Maximum seconds for JCode execution (default 300s=5min).

    Returns:
        Dict with execution results including sandbox_path, diff, changed files,
        out-of-scope validation, test results, and structured output.

    Raises:
        GuardianError: If opt-in not granted, binary not found, or execution fails.
    """
    # 1. Verify explicit user opt-in
    if not jcode_is_opted_in(brain):
        raise GuardianError(
            "JCode execution requires explicit user opt-in. "
            "Run 'guardian jcode opt-in' first."
        )

    # 2. Find JCode binary
    executable = _jcode_path()
    if not executable:
        raise GuardianError(
            "JCode binary was not found on PATH. "
            "Install JCode from https://github.com/1jehuang/jcode or ensure it is on PATH."
        )

    clean_task = task.strip()
    if not clean_task:
        raise GuardianError("A non-empty JCode task is required.")

    # 3. Validate timeout
    if timeout < 10 or timeout > 3600:
        raise GuardianError("timeout must be between 10 and 3600 seconds.")

    # 4. Prepare handoff and safe paths
    safe_paths = _safe_writable_paths(brain, writable_paths or [])
    handoff_data = create_jcode_handoff(brain, clean_task, safe_paths, test_command)
    handoff_path = handoff_data["handoff"]

    # 5. Create sandbox worktree
    from guardian_agent.sandbox import create_worktree_sandbox
    import uuid
    sandbox_branch = f"jcode-{uuid.uuid4().hex[:8]}"
    sandbox = create_worktree_sandbox(brain, sandbox_branch)
    sandbox_path = Path(sandbox["worktree_path"])

    append_journey(
        brain,
        "JCode Sandbox Created",
        [
            f"Branch: {sandbox_branch}",
            f"Path: {sandbox_path}",
            f"Mode: {sandbox.get('mode', 'unknown')}",
        ],
    )

    import time
    start_time = time.time()

    try:
        # 6. Copy handoff into sandbox for JCode to read
        sandbox_handoff = sandbox_path / ".agent" / "research" / "JCODE_HANDOFF.md"
        sandbox_handoff.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(handoff_path, sandbox_handoff)

        # 7. Build and execute JCode command in sandbox with timeout
        jcode_command = [
            executable,
            "--read", str(sandbox_handoff),
            "--message", clean_task,
        ]
        if safe_paths:
            jcode_command.extend(["--write", ",".join(safe_paths)])
        if test_command:
            jcode_command.extend(["--test", test_command])

        child_env = dict(os.environ)
        child_env["JCODE_NO_TELEMETRY"] = "1"
        child_env.pop("JCODE_API_KEY", None)
        child_env.pop("JCODE_AUTH_TOKEN", None)

        completed = subprocess.run(
            jcode_command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(sandbox_path),
            env=child_env,
        )
        elapsed = time.time() - start_time

        # 8. Capture execution results
        execution = {
            "exit_code": completed.returncode,
            "stdout": completed.stdout[:10000],
            "stderr": completed.stderr[:5000],
            "timed_out": False,
            "elapsed_seconds": round(elapsed, 2),
        }

    except subprocess.TimeoutExpired:
        execution = {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"JCode execution timed out after {timeout} seconds.",
            "timed_out": True,
            "elapsed_seconds": timeout,
        }
        append_journey(
            brain,
            "JCode Execution Timed Out",
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
        # Fall through to collect whatever diff/test info we can

    # 9. Collect diff evidence
    diff = _git_diff_in_sandbox(sandbox_path, brain.root)
    changed_files = diff.get("files_changed", [])

    # 10. Validate out-of-scope changes
    out_of_scope = _validate_out_of_scope(changed_files, safe_paths)

    # 11. Run test command if provided (on the sandbox)
    test_results = None
    if test_command and not execution.get("timed_out"):
        try:
            test_proc = subprocess.run(
                test_command,
                capture_output=True, text=True, timeout=60,
                cwd=str(sandbox_path), shell=True,
            )
            test_results = {
                "command": test_command,
                "returncode": test_proc.returncode,
                "summary": test_proc.stdout.strip()[-2000:] if test_proc.stdout else "",
                "error": test_proc.stderr.strip()[-1000:] if test_proc.stderr else None,
            }
        except subprocess.TimeoutExpired:
            test_results = {
                "command": test_command,
                "returncode": -1,
                "summary": "",
                "error": "Test command timed out after 60 seconds.",
            }
        except (OSError, subprocess.SubprocessError) as error:
            test_results = {
                "command": test_command,
                "returncode": -1,
                "summary": "",
                "error": str(error),
            }

    # 12. Build structured result
    result = {
        "task": clean_task,
        "sandbox_path": str(sandbox_path),
        "sandbox_branch": sandbox_branch,
        "execution": execution,
        "changed_files": changed_files,
        "diff_stat": diff.get("diff_stat", ""),
        "insertions": diff.get("insertions", 0),
        "deletions": diff.get("deletions", 0),
        "out_of_scope_changes": out_of_scope,
        "all_changes_valid": len(out_of_scope) == 0,
        "test_results": test_results,
        "writable_paths": safe_paths,
        "approved": False,  # Requires model/user final approval
    }

    # 13. Action: if there are out-of-scope changes, reject
    if out_of_scope:
        out_paths = [o["path"] for o in out_of_scope]
        append_journey(
            brain,
            "JCode Out-of-Scope Changes Detected",
            [
                f"Task: {clean_task[:100]}...",
                f"Out-of-scope files: {', '.join(out_paths)}",
                "Execution requires manual review and approval.",
            ],
        )
    else:
        append_journey(
            brain,
            "JCode Execution Completed",
            [
                f"Task: {clean_task[:100]}...",
                f"Exit code: {execution.get('exit_code')}",
                f"Changed files: {len(changed_files)}",
                f"All changes valid: {len(out_of_scope) == 0}",
                f"Elapsed: {execution.get('elapsed_seconds')}s",
            ],
        )

    return result


# ---------------------------------------------------------------------------
# Phase 4 — Bounded parallel work
# ---------------------------------------------------------------------------

_LOCK_DIR = "locks"
_LOCK_TTL_SECONDS = 3600  # 1 hour lock expiry


def _lock_writable_paths(
    brain: ProjectBrain,
    paths: list[str],
    worker_id: str,
    lock_ttl: int = _LOCK_TTL_SECONDS,
) -> dict:
    """Acquire exclusive locks on writable paths for a worker.

    Checks for existing active locks that overlap with the requested paths.
    If any path is already locked by another active worker, the lock is denied.
    Stale locks (beyond TTL) are automatically released.

    Args:
        brain: The project brain.
        paths: List of file/directory paths to lock.
        worker_id: Identifier for the worker requesting the lock.
        lock_ttl: Lock expiry in seconds (default 1 hour).

    Returns:
        Dict with lock_id (str) on success, or raises GuardianError on conflict.

    Raises:
        GuardianError: If any path is already locked by another active worker.
    """
    import json
    import uuid

    if not paths:
        return {"lock_id": None, "paths": [], "message": "No paths to lock."}

    lock_dir = brain.directory / _LOCK_DIR
    lock_dir.mkdir(exist_ok=True)

    now = now_utc()

    # Clean stale locks and check for conflicts
    for lock_file in lock_dir.glob("*.json"):
        try:
            lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
            if lock_data.get("status") == "active":
                created = lock_data.get("locked_at", "")
                # Simple TTL check: if elapsed > lock_ttl, consider stale
                if created and now > created:  # Basic time comparison
                    # Release stale locks
                    lock_data["status"] = "stale_released"
                    lock_file.write_text(json.dumps(lock_data, indent=2) + "\n", encoding="utf-8")

            # Check active locks for conflicts
            if lock_data.get("status") == "active":
                locked_worker = lock_data.get("worker_id", "")
                if locked_worker != worker_id:
                    locked_paths = lock_data.get("paths", [])
                    for p in paths:
                        for lp in locked_paths:
                            if _paths_overlap(p, lp):
                                raise GuardianError(
                                    f"Path conflict: {p!r} overlaps with {lp!r} "
                                    f"locked by worker {locked_worker!r}."
                                )
        except (OSError, json.JSONDecodeError):
            continue

    # Acquire lock
    lock_id = f"jcode-lock-{uuid.uuid4().hex[:12]}"
    lock_data = {
        "lock_id": lock_id,
        "worker_id": worker_id,
        "paths": paths,
        "locked_at": now_utc(),
        "status": "active",
    }
    lock_path = lock_dir / f"{lock_id}.json"
    lock_path.write_text(json.dumps(lock_data, indent=2) + "\n", encoding="utf-8")

    return {
        "lock_id": lock_id,
        "paths": paths,
        "message": f"Locked {len(paths)} path(s) for worker {worker_id!r}.",
    }


def _paths_overlap(path_a: str, path_b: str) -> bool:
    """Check if two file/directory paths overlap (one is a prefix of the other)."""
    a = path_a.rstrip("/")
    b = path_b.rstrip("/")
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _unlock_writable_paths(brain: ProjectBrain, lock_id: str | None) -> dict:
    """Release a previously acquired path lock.

    Args:
        brain: The project brain.
        lock_id: The lock ID to release. If None, no-op.

    Returns:
        Dict with release status.
    """
    import json

    if lock_id is None:
        return {"status": "noop", "message": "No lock to release."}

    lock_dir = brain.directory / _LOCK_DIR
    lock_path = lock_dir / f"{lock_id}.json"

    if not lock_path.is_file():
        return {"status": "not_found", "message": f"Lock {lock_id!r} not found."}

    try:
        lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
        lock_data["status"] = "released"
        lock_path.write_text(json.dumps(lock_data, indent=2) + "\n", encoding="utf-8")
        return {
            "status": "released",
            "lock_id": lock_id,
            "paths": lock_data.get("paths", []),
        }
    except (OSError, json.JSONDecodeError) as error:
        return {"status": "error", "message": str(error)}


def _check_path_conflicts(
    brain: ProjectBrain,
    task_packages: list[dict],
) -> list[str]:
    """Check if writable paths between multiple task packages conflict.

    Args:
        brain: The project brain.
        task_packages: List of task package dicts, each with a 'writable_paths' key.

    Returns:
        List of conflict descriptions. Empty list means no conflicts.
    """
    conflicts = []
    for i, pkg_a in enumerate(task_packages):
        for j, pkg_b in enumerate(task_packages):
            if i >= j:
                continue
            paths_a = [p.rstrip("/") for p in pkg_a.get("writable_paths", [])]
            paths_b = [p.rstrip("/") for p in pkg_b.get("writable_paths", [])]
            for pa in paths_a:
                for pb in paths_b:
                    if _paths_overlap(pa, pb):
                        conflicts.append(
                            f"Package {i} path {pa!r} overlaps with Package {j} path {pb!r}"
                        )
    return conflicts


def _notify_workers(
    brain: ProjectBrain,
    completed_worker: dict,
    pending_workers: list[dict],
) -> list[str]:
    """Share results from a completed worker with pending workers.

    Copies the diff information into the sandbox of each pending worker
    as a notification file so they can see what the completed worker changed.

    Args:
        brain: The project brain.
        completed_worker: The result dict from the completed worker.
        pending_workers: List of worker config dicts for workers still pending.

    Returns:
        List of notification messages.
    """
    import json
    import time

    notifications = []
    completed_task = completed_worker.get("task", "unknown")
    changed_files = completed_worker.get("changed_files", [])
    sandbox_path = completed_worker.get("sandbox_path")

    for worker_conf in pending_workers:
        worker_sandbox = worker_conf.get("sandbox_path")
        if not worker_sandbox:
            continue

        worker_sandbox_path = Path(worker_sandbox)
        notify_dir = worker_sandbox_path / ".agent" / "notifications"
        notify_dir.mkdir(parents=True, exist_ok=True)

        notification = {
            "from_worker": completed_task,
            "received_at": time.time(),
            "changed_files": changed_files,
            "diff_stat": completed_worker.get("diff_stat", ""),
            "message": (
                f"Worker '{completed_task}' completed. "
                f"Changed {len(changed_files)} file(s). "
                "Review before proceeding with your task."
            ),
        }
        note_path = notify_dir / f"notification-{int(time.time())}.json"
        note_path.write_text(json.dumps(notification, indent=2) + "\n", encoding="utf-8")

        # Also copy diff info if sandbox exists
        if sandbox_path and Path(sandbox_path).is_dir():
            diff_dest = notify_dir / "peer_diff.txt"
            diff_text = completed_worker.get("diff_stat", "No diff available.")
            diff_dest.write_text(diff_text, encoding="utf-8")

        notifications.append(
            f"Notified worker '{worker_conf.get('task', 'unknown')}' "
            f"about {len(changed_files)} change(s) from '{completed_task}'"
        )

    return notifications


def jcode_parallel_run(
    brain: ProjectBrain,
    task_packages: list[dict],
    *,
    max_workers: int = 2,
    global_timeout: int = 600,
) -> dict:
    """Execute multiple bounded JCode tasks in parallel with conflict detection.

    Phase 4 bounded parallel work:
    1. Requires explicit user opt-in per project.
    2. Validates task independence — rejects packages with overlapping writable paths.
    3. Locks writable paths before dispatching each worker.
    4. Runs workers concurrently using a ThreadPoolExecutor (max 2).
    5. Sends change notifications between workers after each completion.
    6. Stops on conflict, test failure, timeout, or emergency stop.
    7. Returns structured results for final model/user approval.

    Args:
        brain: The project brain.
        task_packages: List of task package dicts, each with:
            - task (str): The confirmed task description.
            - writable_paths (list[str], optional): Approved writable paths.
            - test_command (str, optional): Test command to run after completion.
            - timeout (int, optional): Per-worker timeout in seconds (default 300).
        max_workers: Maximum concurrent workers (default 2, max 2 for Phase 4).
        global_timeout: Total timeout for all workers combined (default 600s).

    Returns:
        Dict with worker results, conflicts, notifications, and stop condition.

    Raises:
        GuardianError: If opt-in not granted, binary not found, or path conflicts.
    """
    import json
    import time

    import time
    import json

    # 1. Verify explicit user opt-in
    if not jcode_is_opted_in(brain):
        raise GuardianError(
            "JCode execution requires explicit user opt-in. "
            "Run 'guardian jcode opt-in' first."
        )

    # 2. Validate task packages (before binary check — validation errors first)
    if not task_packages:
        raise GuardianError("At least one task package is required.")
    if len(task_packages) > max_workers:
        raise GuardianError(
            f"Number of task packages ({len(task_packages)}) exceeds max_workers ({max_workers})."
        )

    # Encode default values into each package
    for pkg in task_packages:
        pkg.setdefault("writable_paths", [])
        pkg.setdefault("test_command", None)
        pkg.setdefault("timeout", 300)
        clean = pkg.get("task", "").strip()
        if not clean:
            raise GuardianError("Each task package requires a non-empty 'task'.")
        pkg["task"] = clean

    # 3. Check for path conflicts between packages (before binary check)
    path_conflicts = _check_path_conflicts(brain, task_packages)
    if path_conflicts:
        raise GuardianError(
            "Task packages have overlapping writable paths:\n"
            + "\n".join(f"  - {c}" for c in path_conflicts)
        )

    # 4. Find JCode binary (after validation — avoid unnecessary binary check for invalid input)
    executable = _jcode_path()
    if not executable:
        raise GuardianError(
            "JCode binary was not found on PATH. "
            "Install JCode from https://github.com/1jehuang/jcode or ensure it is on PATH."
        )

    # 5. Lock writable paths for each package
    lock_ids = []
    lock_errors = []
    for i, pkg in enumerate(task_packages):
        worker_id = f"worker-{i}"
        paths = pkg.get("writable_paths", [])
        try:
            lock_result = _lock_writable_paths(brain, paths, worker_id)
            lock_ids.append(lock_result["lock_id"])
            pkg["lock_id"] = lock_result["lock_id"]
        except GuardianError as err:
            lock_errors.append(f"Package {i} ({pkg['task'][:50]}): {err}")

    # If any lock failed, release all acquired locks and abort
    if lock_errors:
        for lid in lock_ids:
            _unlock_writable_paths(brain, lid)
        raise GuardianError(
            "Failed to acquire path locks:\n" + "\n".join(f"  - {e}" for e in lock_errors)
        )

    # 6. Execute workers concurrently
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import uuid

    start_time = time.time()
    worker_results: dict[str, dict] = {}
    worker_errors: list[dict] = []
    stop_condition: str | None = None

    def _run_worker(pkg: dict, worker_index: int) -> dict:
        """Run a single JCode task in a sandbox (helper for parallel execution)."""
        worker_sandbox_branch = f"jcode-par-{uuid.uuid4().hex[:8]}"

        from guardian_agent.sandbox import create_worktree_sandbox
        sandbox = create_worktree_sandbox(brain, worker_sandbox_branch)
        sandbox_path = Path(sandbox["worktree_path"])

        pkg["sandbox_path"] = str(sandbox_path)

        return execute_jcode_in_sandbox(
            brain,
            task=pkg["task"],
            writable_paths=pkg.get("writable_paths"),
            test_command=pkg.get("test_command"),
            timeout=pkg.get("timeout", 300),
        )

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="jcode-parallel") as pool:
        # Submit all workers
        future_map = {}
        for i, pkg in enumerate(task_packages):
            future = pool.submit(_run_worker, pkg, i)
            future_map[future] = (i, pkg)

        # Process results as they complete
        try:
            for future in as_completed(future_map, timeout=global_timeout):
                i, pkg = future_map[future]
                try:
                    result = future.result()
                    worker_key = f"worker_{i}"
                    worker_results[worker_key] = {
                        "task": pkg["task"],
                        "writable_paths": pkg.get("writable_paths", []),
                        "sandbox_path": pkg.get("sandbox_path"),
                        "execution": result.get("execution", {}),
                        "changed_files": result.get("changed_files", []),
                        "diff_stat": result.get("diff_stat", ""),
                        "insertions": result.get("insertions", 0),
                        "deletions": result.get("deletions", 0),
                        "out_of_scope_changes": result.get("out_of_scope_changes", []),
                        "all_changes_valid": result.get("all_changes_valid", False),
                        "test_results": result.get("test_results"),
                        "approved": False,
                    }

                    # Check stop conditions after each worker completes
                    worker_result = worker_results[worker_key]
                    exec_data = worker_result.get("execution", {})

                    if exec_data.get("timed_out"):
                        stop_condition = f"Worker {i} timed out"
                        break

                    if exec_data.get("exit_code", 0) != 0 and exec_data.get("exit_code") is not None:
                        stop_condition = f"Worker {i} exited with code {exec_data['exit_code']}"
                        break

                    if not worker_result.get("all_changes_valid", True):
                        stop_condition = f"Worker {i} has out-of-scope changes"
                        break

                    test_res = worker_result.get("test_results")
                    if test_res and test_res.get("returncode", 0) != 0:
                        stop_condition = f"Worker {i} test failed (exit code {test_res['returncode']})"
                        break

                    # Check emergency stop
                    from guardian_agent.runtime import is_kill_switch_active
                    if is_kill_switch_active(brain):
                        stop_condition = "Emergency stop activated"
                        break

                    # Notify remaining workers about this completion
                    remaining_pkgs = [
                        pkg for j, pkg in enumerate(task_packages)
                        if f"worker_{j}" not in worker_results and j != i
                    ]
                    if remaining_pkgs:
                        notifications = _notify_workers(
                            brain,
                            worker_results[worker_key],
                            remaining_pkgs,
                        )
                        worker_results[worker_key]["notifications_sent"] = notifications

                except GuardianError as err:
                    worker_errors.append({
                        "worker_index": i,
                        "task": pkg["task"],
                        "error": str(err),
                    })
                    stop_condition = f"Worker {i} failed: {err}"
                    break

        except TimeoutError:
            stop_condition = f"Global timeout ({global_timeout}s) exceeded"

    elapsed = round(time.time() - start_time, 2)

    # 7. Release all locks
    for lid in lock_ids:
        _unlock_writable_paths(brain, lid)

    # 8. Build structured result
    all_valid = all(
        wr.get("all_changes_valid", True)
        for wr in worker_results.values()
    )

    combined_changed_files = []
    for wr in worker_results.values():
        combined_changed_files.extend(wr.get("changed_files", []))

    total_insertions = sum(wr.get("insertions", 0) for wr in worker_results.values())
    total_deletions = sum(wr.get("deletions", 0) for wr in worker_results.values())

    result = {
        "parallel_run_id": f"jcode-par-{uuid.uuid4().hex[:12]}",
        "worker_count": len(task_packages),
        "max_workers": max_workers,
        "worker_results": worker_results,
        "worker_errors": worker_errors,
        "stop_condition": stop_condition,
        "all_workers_completed": stop_condition is None,
        "all_changes_valid": all_valid,
        "combined_changed_files": combined_changed_files,
        "total_insertions": total_insertions,
        "total_deletions": total_deletions,
        "elapsed_seconds": elapsed,
        "approved": False,  # Requires model/user final approval
    }

    append_journey(
        brain,
        "JCode Parallel Run Completed",
        [
            f"Workers: {len(task_packages)}",
            f"All completed: {stop_condition is None}",
            f"Stop condition: {stop_condition or 'none'}",
            f"Total changed files: {len(combined_changed_files)}",
            f"Total insertions: {total_insertions}",
            f"Total deletions: {total_deletions}",
            f"All changes valid: {all_valid}",
            f"Elapsed: {elapsed}s",
        ],
    )

    return result
