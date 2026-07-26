"""Specialist Workers Protocol (Phase I).

Defines specialist worker roles (Research, Spec, Frontend, Backend, Database,
Test, Security, DevOps, Docs, Creative) and structures handoff work packages.
"""

from __future__ import annotations

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, markdown_escape
from guardian_agent.research import build_handoff_package


WORKER_ROLES = {
    "research": "Performs repository and market/tech research",
    "spec": "Refines product specifications and user stories",
    "frontend": "Builds UI layouts, components, and client logic",
    "backend": "Builds APIs, business logic, and backend services",
    "database": "Manages schema migrations and data models",
    "test": "Builds unit, integration, and e2e test suites",
    "security": "Audits code for vulnerabilities and permission boundaries",
    "devops": "Manages CI/CD pipelines, Docker, and deployment manifests",
    "docs": "Generates clear user and developer documentation",
    "creative": "Produces visual designs and brand assets",
}


def list_worker_roles() -> dict[str, str]:
    return dict(WORKER_ROLES)


def dispatch_worker(
    brain: ProjectBrain,
    role: str,
    task: str,
    target_files: list[str] | None = None,
) -> dict:
    clean_role = markdown_escape(role).lower()
    if clean_role not in WORKER_ROLES:
        raise GuardianError(f"Unknown worker role {clean_role!r}. Available: {', '.join(sorted(WORKER_ROLES))}")
        
    clean_task = markdown_escape(task)
    pkg = build_handoff_package(brain, f"Worker [{clean_role}]: {clean_task}", target_files)
    
    append_journey(
        brain,
        f"Specialist Worker Dispatched: {clean_role}",
        [f"Task: {clean_task}", f"Package: {pkg['saved_path']}"],
    )
    
    return {
        "role": clean_role,
        "task": clean_task,
        "status": "dispatched",
        "package_path": pkg["saved_path"],
    }
