"""Generate portable, non-destructive Guardian entry points for coding harnesses."""

from __future__ import annotations

from pathlib import Path

from guardian_agent.core import GuardianError, ProjectBrain, append_journey


TARGET_FILES = {
    "codex": "AGENTS.md",
    "claude": "CLAUDE.md",
    "gemini": "GEMINI.md",
    "antigravity": "GUARDIAN.md",
    "cursor": "guardian.mdc",
    "vscode": "GUARDIAN.md",
}


def _content(target: str) -> str:
    return (
        f"# Guardian bootstrap for {target}\n\n"
        "Before substantial work:\n\n"
        "1. Read `.agent/CONTEXT.md`, `.agent/REQUIREMENTS.md`, and `.agent/PLAN.md`.\n"
        "2. Follow confirmed requirements; do not implement pending assumptions.\n"
        "3. Apply relevant approved cross-project lessons with `guardian learning apply`.\n"
        "4. Ask Guardian to select the adaptive workflow and relevant built-in skills.\n"
        "5. Use a fresh bounded handoff for delegated work.\n"
        "6. Require specification review, quality review, and fresh verification before completion.\n"
        "7. Record material decisions, failures, and reusable lessons in the project brain.\n"
        "8. Never expose vault secrets or perform sensitive external actions without policy approval.\n"
    )


ROOT_TARGET_PATHS = {
    "codex": Path("AGENTS.md"),
    "claude": Path("CLAUDE.md"),
    "gemini": Path("GEMINI.md"),
    "antigravity": Path("GUARDIAN.md"),
    "cursor": Path(".cursor/rules/guardian.mdc"),
    # VS Code uses .vscode/GUARDIAN.md (not root) to avoid colliding with
    # Antigravity which owns the root GUARDIAN.md.
    "vscode": Path(".vscode/GUARDIAN.md"),
}


def generate_bootstrap(
    brain: ProjectBrain,
    target: str,
    overwrite: bool = False,
    root_harness: bool = False,
) -> dict:
    targets = list(TARGET_FILES) if target == "all" else [target]
    unknown = [item for item in targets if item not in TARGET_FILES]
    if unknown:
        raise GuardianError(f"Unknown bootstrap target: {', '.join(unknown)}")

    results = []
    for item in targets:
        if root_harness:
            rel_path = ROOT_TARGET_PATHS[item]
            path = brain.root / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            directory = brain.directory / "integrations" / item
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / TARGET_FILES[item]

        if path.exists() and not overwrite:
            results.append({"target": item, "path": str(path), "status": "preserved"})
            continue
        path.write_text(_content(item), encoding="utf-8")
        results.append({"target": item, "path": str(path), "status": "created"})

    append_journey(
        brain,
        "Cross-tool Bootstraps Generated",
        [f"Targets: {', '.join(targets)}", f"Root harness: {root_harness}", "Existing files preserved unless overwrite requested."],
    )
    return {"targets": results}

