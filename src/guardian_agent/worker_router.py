"""WorkerRouter — auto-selects Aider, JCode, or Hermes based on task size
and worker availability.

Routing flow:
1. Classify the task (small → Aider, large → JCode, research → Hermes)
2. Check which workers are available (binary detection)
3. Select the best worker with fallback logic
4. Prepare the appropriate handoff
5. Return a structured route decision ready for Guardian's diff/tests/evidence
   and final-review gate.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from guardian_agent.aider import (
    classify_task_size,
    create_aider_handoff,
    _aider_path,
    launch_aider,
)
from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc
from guardian_agent.jcode import (
    create_jcode_handoff,
    execute_jcode_in_sandbox,
    jcode_is_opted_in,
    jcode_opt_in,
)
from guardian_agent.hermes import (
    create_hermes_handoff,
    execute_hermes_task,
    hermes_is_opted_in,
    hermes_opt_in,
)


# Worker capability descriptions for the route decision.
_WORKER_CAPABILITIES: dict[str, dict[str, Any]] = {
    "aider": {
        "name": "Aider",
        "description": "Scoped coding with local or OmniRoute models",
        "scope": "small scoped coding tasks, single-file or limited multi-file edits",
        "requires_backend": True,
        "requires_opt_in": False,
        "execution_disabled": False,
        "can_handle": frozenset({"small", "large", "research"}),
    },
    "jcode": {
        "name": "JCode",
        "description": "Larger sandboxed coding with bounded parallel work",
        "scope": "multi-file coding, refactoring, full implementations",
        "requires_backend": False,
        "requires_opt_in": True,
        "execution_disabled": False,
        "can_handle": frozenset({"large", "small"}),
    },
    "hermes": {
        "name": "Hermes",
        "description": "Research, planning, skill evaluation, and summaries",
        "scope": "research, planning, skill-evaluation, summary tasks",
        "requires_backend": False,
        "requires_opt_in": True,
        "execution_disabled": True,  # Fail-closed until sandboxed execution exists
        "can_handle": frozenset({"research", "small"}),
    },
}


def _check_worker_availability() -> dict[str, dict[str, Any]]:
    """Check availability of all workers.

    Returns:
        Dict of worker_name -> availability info:
        - available: bool (binary found on PATH)
        - executable: str or None
        - execution_disabled: bool (if True, can prepare handoffs but not run)
        - requires_opt_in: bool
        - opted_in: bool or None (None = doesn't require opt-in)
        - reason: str explaining unavailability if applicable
    """
    from guardian_agent.jcode import _jcode_path
    from guardian_agent.hermes import _hermes_path

    aiders = _aider_path()
    jcodes = _jcode_path()
    hermess = _hermes_path()

    result: dict[str, dict[str, Any]] = {
        "aider": {
            "available": bool(aiders),
            "executable": aiders,
            "execution_disabled": False,
            "requires_opt_in": False,
            "opted_in": None,
            "reason": None if aiders else "Aider binary not found on PATH",
        },
        "jcode": {
            "available": bool(jcodes),
            "executable": jcodes,
            "execution_disabled": False,
            "requires_opt_in": True,
            "opted_in": None,
            "reason": None if jcodes else "JCode binary not found on PATH",
        },
        "hermes": {
            "available": bool(hermess),
            "executable": hermess,
            "execution_disabled": True,  # Fail-closed by design
            "requires_opt_in": True,
            "opted_in": None,
            "reason": (
                None
                if hermess
                else "Hermes binary not found on PATH"
            ),
        },
    }

    # Augment with opt-in status when a brain is available
    return result


def _select_worker(
    classification: dict[str, Any],
    availability: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Select the best worker based on task classification and availability.

    Selection logic:
    - Small → Aider (preferred), fallback to JCode, fallback to Hermes
    - Large → JCode (preferred), fallback to Aider
    - Research → Hermes (preferred, unless execution_disabled), fallback to Aider
    - If no worker is available, raises GuardianError

    Args:
        classification: Result from classify_task_size().
        availability: Result from _check_worker_availability().

    Returns:
        Dict with:
        - worker: str (worker name)
        - category: str (classification category)
        - reason: str (explanation of selection)
        - fallback_chain: list[str] (ordered fallback workers tried)
        - handoff_possible: bool
        - execution_possible: bool
    """
    category = classification.get("category", "small")
    fallback_chain: list[str] = []
    selected: str | None = None
    execution_possible = False

    if category == "research":
        # Prefer Hermes, fallback to Aider
        fallback_chain = ["hermes", "aider"]
    elif category == "large":
        # Prefer JCode, fallback to Aider
        fallback_chain = ["jcode", "aider"]
    else:
        # Small — prefer Aider, fallback to JCode, then Hermes
        fallback_chain = ["aider", "jcode", "hermes"]

    for worker_name in fallback_chain:
        info = availability.get(worker_name, {})
        if info.get("available") and not info.get("execution_disabled"):
            selected = worker_name
            execution_possible = True
            break
        elif info.get("available"):
            # Worker is available but execution is disabled (e.g., Hermes)
            # We can still prepare a handoff
            if selected is None:
                selected = worker_name
            # Continue looking for an execution-capable worker
        elif selected is None:
            # Not available at all — keep looking
            continue

    # If no worker is available, try any that is at least installed (for handoff)
    if selected is None:
        for worker_name in fallback_chain:
            info = availability.get(worker_name, {})
            if info.get("available"):
                selected = worker_name
                break

    # Final fallback: use Aider even if not available (for handoff preparation)
    # This allows the user to see the routing decision and install the worker
    if selected is None:
        selected = "aider"

    return {
        "worker": selected,
        "category": category,
        "reason": classification.get("reason", ""),
        "fallback_chain": fallback_chain,
        "workers_available": {
            name: info.get("available", False)
            for name, info in availability.items()
        },
        "worker_capabilities": _WORKER_CAPABILITIES.get(selected, {}),
        "handoff_possible": True,
        "execution_possible": execution_possible,
    }


def route_task(
    brain: ProjectBrain,
    task: str,
    *,
    writable_paths: list[str] | None = None,
    test_command: str | None = None,
    limit: int = 5,
    backend: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Analyze a confirmed task and produce a complete route decision.

    This is the main entry point for the WorkerRouter. It:
    1. Classifies the task by size
    2. Checks worker availability
    3. Selects the best worker with fallback chain
    4. Prepares the appropriate handoff
    5. Returns a structured route decision ready for execution

    Args:
        brain: The project brain.
        task: The confirmed task description.
        writable_paths: Optional writable file paths for coding workers.
        test_command: Optional test command for verification.
        limit: Max profiles for handoff (Aider only).
        backend: Optional backend for Aider (ollama/omniroute/colibri).
        model: Optional model for Aider.

    Returns:
        Dict with:
        - route_id: str (unique route identifier)
        - classification: dict (from classify_task_size)
        - worker_selection: dict (selected worker and fallback chain)
        - availability: dict (worker binary/opt-in status)
        - handoff: dict or None (the prepared handoff, if applicable)
        - execution_plan: dict (instructions for execution)
        - created_at: str (ISO timestamp)

    Raises:
        GuardianError: If the task is empty.
    """
    clean_task = task.strip()
    if not clean_task:
        raise GuardianError("A non-empty task is required for routing.")

    route_id = f"route-{uuid.uuid4().hex[:12]}"

    # 1. Classify the task
    classification = classify_task_size(clean_task)
    category = classification.get("category", "small")

    # 2. Check worker availability
    availability = _check_worker_availability()

    # 3. Select worker
    worker_selection = _select_worker(classification, availability)
    worker = worker_selection["worker"]

    # 4. Prepare handoff based on the selected worker
    handoff = None
    execution_plan: dict[str, Any] = {
        "worker": worker,
        "execution_possible": worker_selection.get("execution_possible", False),
        "execution_disabled_reason": None,
        "required_opt_in": None,
        "requires_backend": False,
    }

    # Check opt-in requirements and execution feasibility
    if worker == "jcode":
        _opted_in = jcode_is_opted_in(brain)
        execution_plan["required_opt_in"] = "jcode"
        execution_plan["opted_in"] = _opted_in
        if not _opted_in and worker_selection.get("execution_possible"):
            execution_plan["execution_possible"] = False
            execution_plan["execution_disabled_reason"] = (
                "JCode requires explicit opt-in. Run 'guardian jcode opt-in' first."
            )

        handoff = create_jcode_handoff(
            brain, clean_task,
            writable_paths=writable_paths,
            test_command=test_command,
        )

    elif worker == "hermes":
        _opted_in = hermes_is_opted_in(brain)
        execution_plan["required_opt_in"] = "hermes"
        execution_plan["opted_in"] = _opted_in

        # Hermes execution is fail-closed by design
        execution_plan["execution_possible"] = False
        execution_plan["execution_disabled_reason"] = (
            "Hermes execution is disabled by default until a verified "
            "sandboxed execution backend exists. Handoff can be prepared "
            "for review but execution is not available."
        )

        # Determine task type from category
        task_type_map = {
            "research": "research",
            "small": "research",
            "large": "planning",
        }
        task_type = task_type_map.get(category, "research")

        handoff = create_hermes_handoff(
            brain, clean_task,
            task_type=task_type,
            read_paths=writable_paths,
        )

    else:
        # Aider (default)
        execution_plan["requires_backend"] = True
        backend_name = backend or "ollama"
        execution_plan["suggested_backend"] = backend_name

        if not _aider_path():
            execution_plan["execution_possible"] = False
            execution_plan["execution_disabled_reason"] = (
                "Aider binary not found on PATH. "
                "Install Aider from https://aider.chat or ensure it is on PATH."
            )

        handoff = create_aider_handoff(
            brain, clean_task, limit=limit,
            writable_paths=writable_paths,
            test_command=test_command,
        )

    # 5. Build structured route decision
    route_result: dict[str, Any] = {
        "route_id": route_id,
        "task": clean_task,
        "created_at": now_utc(),
        "classification": classification,
        "worker_selection": worker_selection,
        "availability": availability,
        "handoff": handoff,
        "execution_plan": execution_plan,
    }

    append_journey(
        brain,
        "Task Routed",
        [
            f"Route ID: {route_id}",
            f"Task: {clean_task[:100]}",
            f"Category: {category}",
            f"Selected worker: {worker}",
            f"Execution possible: {execution_plan.get('execution_possible', False)}",
        ],
    )

    return route_result


def execute_route(
    brain: ProjectBrain,
    route_result: dict[str, Any],
    *,
    backend: str | None = None,
    model: str | None = None,
    timeout: int = 300,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Execute a previously routed task on its selected worker.

    Args:
        brain: The project brain.
        route_result: The dict returned by route_task().
        backend: Backend for Aider (ollama/omniroute/colibri). Required for Aider.
        model: Model for Aider. Required for Aider.
        timeout: Execution timeout in seconds.
        dry_run: If True, Aider runs in dry-run mode.

    Returns:
        Dict with execution results.

    Raises:
        GuardianError: If execution is not possible or worker is unavailable.
    """
    worker = route_result.get("worker_selection", {}).get("worker", "aider")
    task = route_result.get("task", "")
    execution_plan = route_result.get("execution_plan", {})

    if not execution_plan.get("execution_possible", False):
        reason = execution_plan.get(
            "execution_disabled_reason",
            "Execution is not possible for the selected worker.",
        )
        raise GuardianError(f"Cannot execute route: {reason}")

    writable_paths = route_result.get("handoff", {}).get("writable_paths") or \
                    route_result.get("handoff", {}).get("read_paths")
    test_command = route_result.get("handoff", {}).get("test_command")

    if worker == "jcode":
        # Ensure opt-in
        if not jcode_is_opted_in(brain):
            jcode_opt_in(brain)

        result = execute_jcode_in_sandbox(
            brain, task,
            writable_paths=writable_paths,
            test_command=test_command,
            timeout=timeout,
        )

    elif worker == "hermes":
        # Hermes execution is fail-closed — this should not be reached
        raise GuardianError(
            "Hermes execution is disabled by default. "
            "Cannot execute Hermes route at this time."
        )

    else:
        # Aider
        backend_name = backend or "ollama"
        model_name = model or "qwen3-coder:30b"

        if not _aider_path():
            raise GuardianError(
                "Aider binary not found on PATH. "
                "Install Aider from https://aider.chat or ensure it is on PATH."
            )

        exit_code = launch_aider(
            brain, task, backend_name, model_name,
            dry_run=dry_run,
            writable_paths=writable_paths,
            test_command=test_command,
        )
        result = {
            "worker": "aider",
            "exit_code": exit_code,
            "dry_run": dry_run,
            "backend": backend_name,
            "model": model_name,
        }

    append_journey(
        brain,
        "Routed Task Executed",
        [
            f"Worker: {worker}",
            f"Exit code: {result.get('exit_code') or result.get('execution', {}).get('exit_code', 'N/A')}",
        ],
    )

    return result
