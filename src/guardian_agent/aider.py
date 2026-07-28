"""Bounded Aider worker adapter for local Ollama or the user's OmniRoute.

Phase 1 — Aider routing improvements:
- Task-size classification: small scoped edits -> Aider, larger -> JCode, research -> Hermes
- Enhanced handoff: confirmed task, acceptance criteria, exact writable paths, test command, risks
- Execution evidence: changed files, git diff summary, test results, token/provider usage
- Safety guardrails: dry-run default, no auto-commit/push, no credentials in handoff, no browser
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, markdown_escape, now_utc
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
    "colibri": {
        "base_url": "http://localhost:8000/v1",
        "host": "127.0.0.1",
        "port": 8000,
        "credential_env": None,
        "credential_required": False,
    },
}

# Patterns that indicate a task likely requires multi-file changes (large task)
_LARGE_TASK_PATTERNS = re.compile(
    r"(refactor|redesign|rewrite|restructure|migrate|rearchitect|"
    r"rebuild|new feature|full .* implementation|multi.file|"
    r"several files|multiple modules|end.to.end|end\\-to\\-end)",
    re.IGNORECASE,
)

# Patterns that indicate a research/learning task
_RESEARCH_TASK_PATTERNS = re.compile(
    r"(research|investigate|learn|study|explore|compare|"
    r"evaluate|find out|understand|document)(ing|ation)?",
    re.IGNORECASE,
)

# Protected path patterns that must never be in handoff writable paths
_PROTECTED_PATH_PATTERNS = re.compile(
    r"^(\.env.*|\.git.*|\.venv.*|\.ssh.*|vault.*|\.agent/vault.*|credentials.*|secrets.*|.*\.pem|.*\.key|.*\.pfx|.*\.p12)$",
    re.IGNORECASE,
)

_MAX_EVIDENCE_LENGTH = 10_000


def _aider_path() -> str | None:
    search_path = os.pathsep.join([
        "/home/lalit/.local/bin",
        os.environ.get("PATH", ""),
    ])
    return shutil.which("aider", path=search_path)


def _colibri_path() -> str | None:
    """Locate the Colibrì binary (coli) on PATH.

    Colibrì provides an OpenAI-compatible HTTP API server via `coli serve`.
    Aider connects to it as a backend to run large local MoE models.
    """
    return shutil.which("coli")


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _jcode_available() -> bool:
    """Detect whether JCode binary is available (for task-size routing)."""
    return bool(shutil.which("jcode"))


def _hermes_available() -> bool:
    """Detect whether Hermes binary is available (for research routing)."""
    return bool(shutil.which("hermes"))


def _colibri_available() -> bool:
    """Detect whether Colibrì binary (coli) is available (for backend routing)."""
    return bool(shutil.which("coli"))


def _git_diff_summary(project_root: Path) -> dict:
    """Collect a concise git diff summary of uncommitted changes."""
    result: dict = {
        "files_changed": [],
        "insertions": 0,
        "deletions": 0,
        "diff_stat": "",
        "error": None,
    }
    try:
        # Check if this is a git repository
        git_check = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(project_root),
        )
        if git_check.returncode != 0:
            result["error"] = "Not a git repository."
            return result

        # Get diff stat
        stat = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(project_root),
        )
        result["diff_stat"] = stat.stdout.strip()

        # Parse changed files with insertions/deletions
        diff_numstat = subprocess.run(
            ["git", "diff", "--numstat"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(project_root),
        )
        files = []
        total_insertions = 0
        total_deletions = 0
        for line in diff_numstat.stdout.splitlines():
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                try:
                    ins = int(parts[0]) if parts[0] != "-" else 0
                    dels = int(parts[1]) if parts[1] != "-" else 0
                except ValueError:
                    ins, dels = 0, 0
                total_insertions += ins
                total_deletions += dels
                files.append({
                    "path": parts[2],
                    "insertions": ins,
                    "deletions": dels,
                })

        result["files_changed"] = files
        result["insertions"] = total_insertions
        result["deletions"] = total_deletions
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        result["error"] = str(error)

    return result


def _run_tests(test_command: str, project_root: Path) -> dict:
    """Run a test command and return structured results.

    The test command must be a bounded, safe command (no interactive prompts,
    no destructive operations). Returns stdout, stderr, return code, and
    a summary.
    """
    result: dict = {
        "command": test_command,
        "returncode": -1,
        "stdout": "",
        "stderr": "",
        "summary": "",
        "error": None,
    }
    if not test_command or not test_command.strip():
        result["error"] = "No test command provided."
        return result

    try:
        completed = subprocess.run(
            test_command,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(project_root),
            shell=True,
        )
        result["returncode"] = completed.returncode
        result["stdout"] = completed.stdout[:_MAX_EVIDENCE_LENGTH]
        result["stderr"] = completed.stderr[:_MAX_EVIDENCE_LENGTH]

        # Extract a compact summary from the last few lines of stdout
        lines = completed.stdout.strip().splitlines()
        summary_lines = [l for l in lines if any(kw in l.lower() for kw in ("ok", "passed", "failed", "error", "test"))]
        result["summary"] = "\n".join(summary_lines[-10:]) if summary_lines else completed.stdout.strip()[-500:]
    except subprocess.TimeoutExpired:
        result["error"] = "Test command timed out after 120 seconds."
    except (OSError, subprocess.SubprocessError) as error:
        result["error"] = str(error)

    return result


def _safe_writable_paths(brain: ProjectBrain, raw_paths: list[str]) -> list[str]:
    """Validate and filter writable paths, excluding protected/sensitive paths."""
    normalized = []
    root = brain.root.resolve()

    for p in raw_paths:
        clean_p = str(p or "").strip()
        if not clean_p:
            continue
        # Reject absolute paths and path traversal
        if clean_p.startswith("/") or ".." in clean_p or "\x00" in clean_p:
            continue
        # Reject protected paths
        skip = False
        for part in Path(clean_p).parts:
            part_clean = part.strip()
            if _PROTECTED_PATH_PATTERNS.match(part_clean) or part_clean in (".env", ".git", ".agent"):
                skip = True
                break
        if skip:
            continue
        target = (root / clean_p).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            continue
        normalized.append(str(target.relative_to(root)))

    return normalized


def classify_task_size(task: str) -> dict:
    """Classify a task by size for routing decisions.

    Returns:
        A dict with:
        - category: "small", "large", or "research"
        - reason: Explanation of the classification
        - recommended_worker: "aider", "jcode", or "hermes"
        - workers_available: dict of which workers are detected
    """
    clean_task = task.strip()
    if not clean_task:
        return {
            "category": "small",
            "reason": "Empty task — defaulting to small.",
            "recommended_worker": "aider",
            "workers_available": {
                "aider": bool(_aider_path()),
                "jcode": _jcode_available(),
                "hermes": _hermes_available(),
            },
        }

    # Check for research/learning patterns first
    if _RESEARCH_TASK_PATTERNS.search(clean_task):
        hermes_ok = _hermes_available()
        return {
            "category": "research",
            "reason": "Task contains research/learning keywords.",
            "recommended_worker": "hermes" if hermes_ok else "aider",
            "workers_available": {
                "aider": bool(_aider_path()),
                "jcode": _jcode_available(),
                "hermes": hermes_ok,
            },
        }

    # Check for large task patterns
    task_length = len(clean_task)
    is_multi_file = clean_task.count("\n") > 5 or task_length > 500
    has_large_keywords = bool(_LARGE_TASK_PATTERNS.search(clean_task))

    if has_large_keywords or is_multi_file:
        jcode_ok = _jcode_available()
        aider_ok = bool(_aider_path())
        return {
            "category": "large",
            "reason": (
                "Multi-file or large-scope task detected."
                if is_multi_file
                else "Task contains refactoring/redesign keywords."
            ),
            "recommended_worker": "jcode" if jcode_ok else ("aider" if aider_ok else None),
            "workers_available": {
                "aider": aider_ok,
                "jcode": jcode_ok,
                "hermes": _hermes_available(),
            },
        }

    # Default: small task
    return {
        "category": "small",
        "reason": "Task is compact and scoped — suitable for Aider.",
        "recommended_worker": "aider",
        "workers_available": {
            "aider": bool(_aider_path()),
            "jcode": _jcode_available(),
            "hermes": _hermes_available(),
        },
    }


def aider_status() -> dict:
    """Return structured Aider availability, backend health, and worker routing info."""
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
        "jcode_available": _jcode_available(),
        "hermes_available": _hermes_available(),
        "colibri_available": _colibri_available(),
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


def create_aider_handoff(
    brain: ProjectBrain,
    task: str,
    limit: int = 5,
    acceptance_criteria: list[str] | None = None,
    writable_paths: list[str] | None = None,
    test_command: str | None = None,
    risks: list[str] | None = None,
    stop_conditions: list[str] | None = None,
) -> dict:
    """Create an enhanced Aider handoff with full execution context.

    Args:
        brain: The project brain.
        task: The confirmed task description.
        limit: Maximum number of profiles to include.
        acceptance_criteria: List of acceptance criteria for the task.
        writable_paths: Exact file paths Aider may modify.
        test_command: Command to run for verification.
        risks: Known risks to communicate.
        stop_conditions: Conditions under which Aider should stop.

    Returns:
        Handoff metadata including the handoff file path.
    """
    routing = prepare_profile_handoff(brain, task, limit)
    handoff = brain.directory / "research" / "AIDER_HANDOFF.md"
    specialist_text = Path(routing["handoff_path"]).read_text(encoding="utf-8")

    # Build enhanced handoff content
    safe_writable = _safe_writable_paths(brain, writable_paths or [])

    criteria_section = ""
    if acceptance_criteria:
        criteria_lines = "\n".join(f"- [ ] {c}" for c in acceptance_criteria)
        criteria_section = f"\n## Acceptance criteria\n\n{criteria_lines}\n"

    writable_section = ""
    if safe_writable:
        writable_lines = "\n".join(f"- `{p}`" for p in safe_writable)
        writable_section = f"\n## Writable paths\n\n{writable_lines}\n\nDo not modify files outside this list.\n"
    else:
        writable_section = "\n## Writable paths\n\n(None — read-only analysis.)\n"

    test_section = ""
    if test_command:
        test_section = f"\n## Test command\n\n```bash\n{test_command}\n```\n"

    risks_section = ""
    if risks:
        risk_lines = "\n".join(f"- ⚠️ {r}" for r in risks)
        risks_section = f"\n## Known risks\n\n{risk_lines}\n"

    stop_section = ""
    if stop_conditions:
        stop_lines = "\n".join(f"- 🛑 {s}" for s in stop_conditions)
        stop_section = f"\n## Stop conditions\n\n{stop_lines}\n"

    handoff.write_text(
        "# Aider Bounded Work Handoff\n\n"
        f"## Task\n\n{task.strip()}\n\n"
        "## Required behavior\n\n"
        "- Read the selected specialist handoff linked below.\n"
        "- Stay within the confirmed task and repository.\n"
        "- Modify only the writable paths listed below.\n"
        "- Do not access credentials or external services unless explicitly configured.\n"
        "- Do not use prohibited models.\n"
        "- Run the test command after changes and report results.\n"
        "- Report evidence: changed files, git diff, test results, token usage, remaining risks.\n"
        "- The user or primary supervising model gives the final green signal.\n"
        f"{criteria_section}"
        f"{writable_section}"
        f"{test_section}"
        f"{risks_section}"
        f"{stop_section}"
        f"\n## Specialist handoff\n\n{specialist_text}\n",
        encoding="utf-8",
    )

    append_journey(
        brain,
        "Aider Handoff Prepared",
        [
            f"Task: {task.strip()}",
            f"Handoff: {handoff.name}",
            f"Writable paths: {safe_writable}",
            f"Test command: {test_command or '(none)'}",
        ],
    )

    return {
        "task": task.strip(),
        "handoff": str(handoff),
        "specialist_handoff": routing["handoff_path"],
        "selected_profiles": [profile["name"] for profile in routing["selected"]],
        "context": routing["context"],
        "acceptance_criteria": acceptance_criteria or [],
        "writable_paths": safe_writable,
        "test_command": test_command,
        "risks": risks or [],
        "stop_conditions": stop_conditions or [],
    }


def collect_aider_execution_evidence(
    brain: ProjectBrain,
    task: str,
    test_command: str | None = None,
) -> dict:
    """Collect execution evidence after an Aider session completes.

    Gathers:
    - Changed files via git diff
    - Git diff stat summary
    - Test results (if test_command provided)
    - Token/provider usage if available
    - Remaining risks

    Args:
        brain: The project brain.
        task: The original task.
        test_command: Optional test command to run for verification.

    Returns:
        Structured evidence report.
    """
    evidence: dict[str, Any] = {
        "task": task,
        "collected_at": now_utc(),
        "changed_files": [],
        "diff_stat": "",
        "insertions": 0,
        "deletions": 0,
        "test_results": None,
        "token_usage": None,
        "remaining_risks": [],
        "errors": [],
    }

    # 1. Collect git diff evidence
    diff = _git_diff_summary(brain.root)
    if diff.get("error"):
        evidence["errors"].append(f"Git diff: {diff['error']}")
    else:
        evidence["changed_files"] = diff["files_changed"]
        evidence["diff_stat"] = diff["diff_stat"]
        evidence["insertions"] = diff["insertions"]
        evidence["deletions"] = diff["deletions"]

    # 2. Run tests if a test command was provided
    if test_command:
        test_result = _run_tests(test_command, brain.root)
        evidence["test_results"] = test_result

    # 3. Check for Aider audit logs for token/provider usage
    audit_dir = brain.directory / "audit"
    aider_history = audit_dir / "aider-llm.history.md"
    if aider_history.is_file():
        try:
            history_text = aider_history.read_text(encoding="utf-8", errors="replace")
            # Attempt to extract token usage from history
            token_lines = []
            for line in history_text.splitlines():
                if any(kw in line.lower() for kw in ("token", "model", "provider", "cost")):
                    token_lines.append(line.strip())
            if token_lines:
                evidence["token_usage"] = {
                    "source": "aider-llm.history.md",
                    "extracted_lines": token_lines[-20:],
                }
        except OSError as error:
            evidence["errors"].append(f"Reading aider history: {error}")

    # 4. Collect changed file paths for easy reference
    changed_paths = [f["path"] for f in evidence["changed_files"]]

    # 5. Identify remaining risks based on evidence
    if evidence["test_results"]:
        tr = evidence["test_results"]
        if tr.get("error"):
            evidence["remaining_risks"].append(f"Test execution failed: {tr['error']}")
        elif tr.get("returncode", -1) != 0:
            evidence["remaining_risks"].append(
                f"Tests exited with code {tr['returncode']}. Changes may introduce regressions."
            )
        else:
            evidence["remaining_risks"].append("Tests passed, but focused tests may not cover all edge cases.")
    else:
        evidence["remaining_risks"].append("No test command was executed. Manual verification recommended.")

    if not changed_paths:
        evidence["remaining_risks"].append("No files were changed — task may not have produced output.")

    if not evidence["token_usage"]:
        evidence["remaining_risks"].append("Token/provider usage was not recorded.")

    # Record evidence in journey
    append_journey(
        brain,
        "Aider Execution Evidence Collected",
        [
            f"Task: {task[:100]}...",
            f"Changed files: {len(changed_paths)}",
            f"Insertions/deletions: +{evidence['insertions']}/-{evidence['deletions']}",
            f"Tests run: {bool(test_command)}",
        ],
    )

    return evidence


def build_aider_command(
    brain: ProjectBrain,
    task: str,
    backend: str,
    model: str,
    *,
    dry_run: bool = True,
    limit: int = 5,
    acceptance_criteria: list[str] | None = None,
    writable_paths: list[str] | None = None,
    test_command: str | None = None,
    risks: list[str] | None = None,
    stop_conditions: list[str] | None = None,
) -> dict:
    """Build a bounded Aider command with enhanced handoff and safety guardrails.

    Safety guardrails enforced:
    - dry-run default (must opt in with allow_edits)
    - no analytics, no auto-commits, no gitignore use
    - history files isolated under .agent/audit/
    - no credentials in the command or handoff text
    - only reachable backends accepted
    - prohibited models rejected before execution

    Args:
        brain: The project brain.
        task: The confirmed task description.
        backend: One of "ollama", "omniroute", or "colibri".
        model: The model identifier (must pass model policy).
        dry_run: If True, adds --dry-run to the Aider command.
        limit: Max profiles for the handoff.
        acceptance_criteria: Optional acceptance criteria for handoff.
        writable_paths: Exact writable file paths.
        test_command: Optional test command for verification.
        risks: Known risks for handoff.
        stop_conditions: Stop conditions for handoff.

    Returns:
        Dict with backend, model, dry_run, command list, credential_env, and handoff metadata.
    """
    if backend not in BACKENDS:
        raise GuardianError(f"Unknown Aider backend {backend!r}; use: {', '.join(BACKENDS)}")
    require_model_allowed(model)
    if not task.strip():
        raise GuardianError("Aider task must not be empty.")
    executable = _aider_path()
    if not executable:
        raise GuardianError("Aider is not installed or not available on PATH.")
    config = BACKENDS[backend]
    handoff = create_aider_handoff(
        brain, task, limit,
        acceptance_criteria=acceptance_criteria,
        writable_paths=writable_paths,
        test_command=test_command,
        risks=risks,
        stop_conditions=stop_conditions,
    )
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
    acceptance_criteria: list[str] | None = None,
    writable_paths: list[str] | None = None,
    test_command: str | None = None,
    risks: list[str] | None = None,
    stop_conditions: list[str] | None = None,
) -> int:
    """Launch Aider with enhanced handoff, safety guardrails, and backend validation.

    Safety checks:
    - Backend must be reachable before launching.
    - Credentials are read from environment only — never from handoff or project files.
    - No auto-commit, no analytics, no gitignore modifications.
    - Only allowed models are accepted (prohibited models blocked before launch).
    - Dry-run is the default; pass allow_edits externally to override.

    Args:
        brain: The project brain.
        task: The confirmed task description.
        backend: One of "ollama", "omniroute", or "colibri".
        model: The model identifier.
        dry_run: If True, runs in --dry-run mode (default safe behavior).
        limit: Max profiles for the handoff.
        acceptance_criteria: Optional acceptance criteria for handoff.
        writable_paths: Exact writable file paths.
        test_command: Optional test command for verification.
        risks: Known risks for handoff.
        stop_conditions: Stop conditions for handoff.

    Returns:
        Return code from the Aider subprocess.
    """
    launch = build_aider_command(
        brain, task, backend, model,
        dry_run=dry_run,
        limit=limit,
        acceptance_criteria=acceptance_criteria,
        writable_paths=writable_paths,
        test_command=test_command,
        risks=risks,
        stop_conditions=stop_conditions,
    )
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
