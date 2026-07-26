"""Intake, Profile Selection, and Deterministic Orchestration (Phase 2 & 4).

Generates a deterministic orchestration preview (profile selection, skill hints,
route preview, and explicit allowed paths) without calling a model, starting a container,
or running external actions.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from guardian_agent.core import (
    GuardianError,
    ProjectBrain,
    append_journey,
    confirm,
    markdown_escape,
    now_utc,
    render_context,
)

from guardian_agent.gateway import list_routes_for_task
from guardian_agent.health import check_provider_health
from guardian_agent.model_policy import PROHIBITED_MODELS, is_model_allowed

from guardian_agent.profiles import select_profiles
from guardian_agent.skills import select_builtin_skills
from guardian_agent.workflow import assess_profile as _assess_risk, start_workflow


ORCHESTRATIONS_DIR = "orchestrations"
SUPPORTED_TASK_TYPES = ("routing", "research", "planning", "coding", "review", "documentation")
MAX_PREVIEW_ROUTES = 5

_PROTECTED_PATH_PATTERNS = re.compile(
    r"^(\.env.*|\.git.*|\.venv.*|\.ssh.*|vault.*|\.agent/vault.*|credentials.*|secrets.*|.*\.pem|.*\.key|.*\.pfx|.*\.p12|.*\.sqlite|.*\.db)$",
    re.IGNORECASE,
)


def _validate_and_normalize_paths(brain: ProjectBrain, raw_paths: list[str]) -> list[str]:
    """Validate and normalize user-supplied allowed paths for an orchestration."""
    normalized = []
    root = (brain.directory.parent if brain.directory.name == ".agent" else brain.directory).resolve()

    for p in raw_paths:
        clean_p = str(p or "").strip()
        if not clean_p:
            continue
        if clean_p.startswith("/") or ".." in clean_p or "\x00" in clean_p:
            raise GuardianError(f"Security violation: path {clean_p!r} is absolute or contains path traversal.")

        for part in Path(clean_p).parts:
            part_clean = part.strip()
            if _PROTECTED_PATH_PATTERNS.match(part_clean) or part_clean in (".env", ".git", ".agent"):
                raise GuardianError(f"Security violation: protected path component {part!r} in {clean_p!r} cannot be an allowed path.")



        target = (root / clean_p).resolve()
        try:
            if not target.is_relative_to(root):
                raise GuardianError(f"Security violation: path {clean_p!r} escapes project root.")
        except AttributeError:
            if os.path.commonpath([str(target), str(root)]) != str(root):
                raise GuardianError(f"Security violation: path {clean_p!r} escapes project root.")

        try:
            rel_str = str(target.relative_to(root))
        except ValueError:
            raise GuardianError(f"Security violation: path {clean_p!r} escapes project root.")

        if clean_p.endswith("/") and not rel_str.endswith("/"):
            rel_str += "/"
        normalized.append(rel_str)

    return normalized


@dataclass
class OrchestrationPreview:
    """Preview of profile, skill, route, and path selection for an orchestration."""

    task: str
    risk_profile: str
    risk_reasons: list[str]
    selected_profiles: list[dict[str, Any]]
    selected_skills: list[dict[str, Any]]
    routes: list[dict[str, Any]]
    context_savings: dict[str, Any]
    allowed_paths: list[str] = field(default_factory=list)
    access_mode: str = "read-only"


@dataclass
class OrchestrationRecord:
    """Persistent record of one orchestration lifecycle."""

    id: str
    task: str
    status: str  # "draft" | "confirmed" | "dispatched" | "failed"
    preview: OrchestrationPreview
    task_type: str = "routing"
    workflow_id: str | None = None
    requirement_summary: str | None = None
    handoff_path: str | None = None
    created_at: str = field(default_factory=now_utc)
    updated_at: str = field(default_factory=now_utc)
    errors: list[str] = field(default_factory=list)


def _orchestrations_dir(brain: ProjectBrain) -> Path:
    path = brain.directory / "tasks" / ORCHESTRATIONS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _record_path(brain: ProjectBrain, orchestration_id: str) -> Path:
    clean = markdown_escape(orchestration_id)
    if not clean.startswith("orch-") or not all(c.isalnum() or c == "-" for c in clean):
        raise GuardianError(f"Invalid orchestration ID: {orchestration_id!r}")
    return _orchestrations_dir(brain) / f"{clean}.json"


def _save_record(brain: ProjectBrain, record: OrchestrationRecord) -> None:
    record.updated_at = now_utc()
    data = _serialize_record(record)
    _record_path(brain, record.id).write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )


def _load_record(brain: ProjectBrain, orchestration_id: str) -> OrchestrationRecord:
    path = _record_path(brain, orchestration_id)
    if not path.is_file():
        raise GuardianError(
            f"Orchestration {orchestration_id!r} was not found."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise GuardianError(
            f"Orchestration record {orchestration_id!r} is corrupted."
        ) from error
    return _deserialize_record(data)


def _serialize_record(record: OrchestrationRecord) -> dict[str, Any]:
    preview_dict = asdict(record.preview)
    preview = {
        "task": preview_dict["task"],
        "task_type": record.task_type,
        "risk_profile": preview_dict["risk_profile"],
        "risk": {"profile": preview_dict["risk_profile"], "reasons": list(preview_dict["risk_reasons"])},
        "risk_reasons": list(preview_dict["risk_reasons"]),
        "selected_profiles": list(preview_dict["selected_profiles"]),
        "selected_skills": list(preview_dict["selected_skills"]),
        "routes": list(preview_dict["routes"]),
        "context_savings": dict(preview_dict["context_savings"]),
        "allowed_paths": list(preview_dict.get("allowed_paths", [])),
        "access_mode": preview_dict.get("access_mode", "read-only"),
        "prohibited_models": list(PROHIBITED_MODELS),

    }

    return {
        "id": record.id,
        "task": record.task,
        "task_type": record.task_type,
        "status": record.status,
        "preview": preview,
        "workflow_id": record.workflow_id,
        "requirement_summary": record.requirement_summary,
        "handoff_path": record.handoff_path,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "errors": list(record.errors),
    }



def _deserialize_record(data: dict[str, Any]) -> OrchestrationRecord:
    preview_data = data.get("preview", {})
    preview = OrchestrationPreview(
        task=preview_data.get("task", ""),
        risk_profile=preview_data.get("risk_profile", "standard"),
        risk_reasons=list(preview_data.get("risk_reasons", [])),
        selected_profiles=list(preview_data.get("selected_profiles", [])),
        selected_skills=list(preview_data.get("selected_skills", [])),
        routes=list(preview_data.get("routes", [])),
        context_savings=dict(preview_data.get("context_savings", {})),
        allowed_paths=list(preview_data.get("allowed_paths", [])),
        access_mode=preview_data.get("access_mode", "read-only"),
    )


    return OrchestrationRecord(
        id=data["id"],
        task=data.get("task", preview.task),
        task_type=data.get("task_type", "routing"),
        status=data.get("status", "draft"),
        preview=preview,
        workflow_id=data.get("workflow_id"),
        requirement_summary=data.get("requirement_summary"),
        handoff_path=data.get("handoff_path"),
        created_at=data.get("created_at", now_utc()),
        updated_at=data.get("updated_at", now_utc()),
        errors=list(data.get("errors", [])),
    )


def _classify_task(task: str) -> str:
    text = task.lower()
    if any(word in text for word in ("research", "investigate", "search", "find", "learn")):
        return "research"
    if any(word in text for word in ("plan", "design", "architecture", "how to")):
        return "planning"
    if any(word in text for word in ("documentation", "document", "readme", "doc", "explain")):
        return "documentation"
    if any(word in text for word in ("review", "audit", "inspect", "check")):
        return "review"
    if any(word in text for word in ("code", "implement", "build", "write", "create", "refactor", "fix")):
        return "coding"
    return "routing"


def _is_final_review_route(route: dict[str, Any]) -> bool:
    return route.get("usage_tier") == "final-review" or route.get("usage_class") == "final-review" or route.get("provider") == "manual"



def _profile_to_risk(profile_name: str) -> str:
    p = (profile_name or "").lower().strip()
    if "high" in p or "critical" in p:
        return "high"
    if "medium" in p or "elevated" in p:
        return "medium"
    return "low"


def _format_route_summary(route: dict[str, Any]) -> str:
    return (
        f"{route.get('provider', '?')}:{route.get('model', '?')} "
        f"[{route.get('cost_tier', '?')}, {route.get('capabilities', [])[:3]}]"
    )


def orchestrate_start(
    brain: ProjectBrain,
    task: str,
    limit: int = 5,
    approved_paths: list[str] | None = None,
    access_mode: str = "read-only",
) -> dict[str, Any]:
    """Create a deterministic orchestration preview and a draft orchestration record."""
    clean_task = markdown_escape(task)
    if not clean_task:
        raise GuardianError("An orchestration task is required.")
    if len(clean_task) > 2000:
        raise GuardianError("Orchestration task exceeds the 2000-character limit.")
    if limit < 1 or limit > 5:
        raise GuardianError("Profile selection limit must be between 1 and 5.")

    task_type = _classify_task(clean_task)
    risk = _assess_risk(clean_task)

    profile_result = select_profiles(clean_task, limit)
    skills = select_builtin_skills(clean_task, risk["profile"])

    all_routes = list_routes_for_task(brain, task_type) if hasattr(brain, "directory") else []
    local_routes = [
        r for r in all_routes
        if (r.get("provider") == "local-ollama" or r.get("cost_tier") == "local")
        and is_model_allowed(r.get("model", ""))
        and check_provider_health(brain, r.get("provider", "")).get("healthy", False)
    ]

    free_limited_routes = [
        r for r in all_routes
        if r.get("cost_tier") in ("free", "free-limited")
        and is_model_allowed(r.get("model", ""))
        and check_provider_health(brain, r.get("provider", "")).get("healthy", False)
    ]
    final_review_routes = [
        r for r in all_routes
        if _is_final_review_route(r)
        and is_model_allowed(r.get("model", ""))
        and check_provider_health(brain, r.get("provider", "")).get("healthy", False)
    ]
    fallback_routes = [
        r for r in all_routes
        if r not in local_routes
        and r not in free_limited_routes
        and not _is_final_review_route(r)
        and r.get("cost_tier") not in ("paid",)
    ]

    seen: set[tuple[str, str]] = set()
    deduped_routes: list[dict[str, Any]] = []
    working_routes = local_routes + free_limited_routes + fallback_routes
    if final_review_routes:
        working_routes = working_routes[: MAX_PREVIEW_ROUTES - 1] + final_review_routes[:1]
    else:
        working_routes = working_routes[:MAX_PREVIEW_ROUTES]
    for route in working_routes:
        key = (route.get("provider", ""), route.get("model", ""))
        if key not in seen:
            seen.add(key)
            deduped_routes.append(route)

    normalized_paths = _validate_and_normalize_paths(brain, approved_paths or [])

    preview = OrchestrationPreview(
        task=clean_task,
        risk_profile=risk["profile"],
        risk_reasons=risk["reasons"],
        selected_profiles=profile_result.get("selected", []),
        selected_skills=skills,
        routes=deduped_routes,
        context_savings=profile_result.get("context", {}),
        allowed_paths=normalized_paths,
        access_mode=access_mode,
    )

    orchestration_id = f"orch-{uuid.uuid4().hex[:12]}"
    record = OrchestrationRecord(
        id=orchestration_id,
        task=clean_task,
        status="draft",
        preview=preview,
        task_type=task_type,
    )

    is_write_mode = (access_mode == "write") or (task_type in ("coding", "refactoring", "bugfix"))
    if is_write_mode and not normalized_paths:
        record.errors.append("Writable task requires explicit approved paths before confirmation.")

    _save_record(brain, record)


    preview_lines = [
        f"Orchestration: {orchestration_id}",
        f"Task: {clean_task}",
        f"Classified as: {task_type}",
        f"Risk profile: {risk['profile']} ({'; '.join(risk['reasons'])})",
        f"Proposed allowed paths: {', '.join(normalized_paths) if normalized_paths else '(None specified)'}",
        "",
        "Selected profiles:",
    ]
    for prof in preview.selected_profiles:
        preview_lines.append(
            f"  - {prof.get('name', '?')} ({prof.get('slug', '?')}) "
            f"[match: {prof.get('match_score', 0)}]"
        )
    preview_lines.extend([
        "",
        "Selected built-in skills:",
    ])
    for skill in preview.selected_skills:
        preview_lines.append(f"  - {skill.get('name', '?')}: {skill.get('description', '')}")
    preview_lines.extend([
        "",
        "Route preview:",
    ])
    if deduped_routes:
        for route in deduped_routes:
            preview_lines.append(f"  - {_format_route_summary(route)}")
    else:
        preview_lines.append("  (No configured routes available)")

    preview_text = "\n".join(preview_lines)

    append_journey(
        brain,
        f"Orchestration Draft Created: {orchestration_id}",
        [
            f"Task: {clean_task}",
            f"Risk profile: {risk['profile']}",
            f"Allowed paths: {normalized_paths}",
        ],
    )

    return {
        "orchestration_id": orchestration_id,
        "status": record.status,
        "preview_text": preview_text,
        "preview": _serialize_record(record)["preview"],
        "instruction": (
            f"Review the draft preview. To confirm, supply --allowed-path if needed and run: "
            f"guardian orchestrate confirm --id {orchestration_id}"
        ),
    }


def orchestrate_confirm(
    brain: ProjectBrain,
    orchestration_id: str,
    summary: str | None = None,
) -> dict[str, Any]:
    """Confirm a draft orchestration request."""
    record = _load_record(brain, orchestration_id)
    if record.status != "draft":
        raise GuardianError(
            f"Orchestration {orchestration_id!r} is in status {record.status!r}, "
            "not 'draft'. Only draft orchestrations can be confirmed."
        )

    allowed_paths = getattr(record.preview, "allowed_paths", []) if hasattr(record.preview, "allowed_paths") else (record.preview.get("allowed_paths", []) if isinstance(record.preview, dict) else [])
    access_mode = getattr(record.preview, "access_mode", "read-only") if hasattr(record.preview, "access_mode") else (record.preview.get("access_mode", "read-only") if isinstance(record.preview, dict) else "read-only")


    is_write_mode = (access_mode == "write") or (record.task_type in ("coding", "refactoring", "bugfix"))
    if is_write_mode and not allowed_paths:
        raise GuardianError(
            f"Orchestration {orchestration_id!r} cannot be confirmed: writable task "
            "has no explicitly approved paths. Re-run orchestrate start with --allowed-path."
        )


    clean_summary = markdown_escape(summary or record.task)
    if not clean_summary:
        raise GuardianError("A non-empty confirmation summary is required.")

    confirm(
        brain,
        clean_summary,
        reference_id=record.id,
        original_request=record.task,
    )

    workflow_risk = _profile_to_risk(record.preview.risk_profile)
    workflow = start_workflow(brain, record.task, workflow_risk)

    record.status = "confirmed"
    record.workflow_id = workflow["id"]
    record.requirement_summary = clean_summary
    _save_record(brain, record)

    append_journey(
        brain,
        f"Orchestration Confirmed: {orchestration_id}",
        [
            f"Summary: {clean_summary}",
            f"Workflow: {workflow['id']}",
            f"Allowed paths: {record.preview.allowed_paths}",
        ],
    )

    return {
        "orchestration_id": orchestration_id,
        "status": record.status,
        "workflow_id": workflow["id"],
        "requirement_summary": clean_summary,
        "instruction": (
            f"Orchestration confirmed. To dispatch the compact handoff, run: "
            f"guardian orchestrate dispatch --id {orchestration_id}"
        ),
    }


def orchestrate_dispatch(
    brain: ProjectBrain,
    orchestration_id: str,
) -> dict[str, Any]:
    """Dispatch a confirmed orchestration."""
    record = _load_record(brain, orchestration_id)

    if record.status == "dispatched" and record.handoff_path:
        path = Path(record.handoff_path)
        return {
            "orchestration_id": orchestration_id,
            "status": "dispatched",
            "handoff_path": record.handoff_path,
            "handoff_exists": path.is_file(),
            "note": "Orchestration was already dispatched. Returning existing handoff.",
        }

    if record.status != "confirmed":
        raise GuardianError(
            f"Orchestration {orchestration_id!r} is in status {record.status!r}, "
            "not 'confirmed'. Only confirmed orchestrations can be dispatched."
        )

    handoff_dir = brain.directory / "research"
    handoff_dir.mkdir(exist_ok=True)
    handoff_path = handoff_dir / f"orchestration_handoff_{record.id}.md"

    context = render_context(brain)
    preview = record.preview

    selected_profile_lines = []
    for prof in preview.selected_profiles:
        selected_profile_lines.append(
            f"### {prof.get('name', '?')} (`{prof.get('slug', '?')}`)\n\n"
            f"- Mission: {prof.get('description', '')}\n"
            f"- Capabilities: {', '.join(prof.get('capabilities', []))}\n"
            f"- Tools: {', '.join(prof.get('tools', []))}\n"
            f"- Suggested skills: {', '.join(prof.get('skill_hints', []))}\n"
            f"- Risk: {prof.get('risk', 'low')}\n"
            f"- Output: {prof.get('output_contract', '')}\n"
            f"- Verify: {'; '.join(prof.get('verification', []))}\n"
            f"- Prohibited models: {', '.join(prof.get('prohibited_models', PROHIBITED_MODELS))}"
        )

    route_lines = []
    for route in preview.routes:
        route_lines.append(f"- {_format_route_summary(route)}")

    content = f"""# Orchestration Handoff for {record.id}

**Original Request**: {record.task}
**Confirmed Requirement**: {record.requirement_summary or record.task}
**Task Type**: {record.task_type}
**Risk Profile**: {preview.risk_profile}
**Approved Paths**: {', '.join(preview.allowed_paths) if preview.allowed_paths else '(None)'}

---

## Selected Specialist Profiles ({len(preview.selected_profiles)})

{'\n\n'.join(selected_profile_lines) if selected_profile_lines else '(None)'}

---

## Selected Skill Hints ({len(preview.selected_skills)})

{'\n'.join('- ' + s.get('name', '?') + ': ' + s.get('description', '') for s in preview.selected_skills) if preview.selected_skills else '(None)'}

---

## Context Savings

- Estimated savings: {preview.context_savings.get('estimated_savings_percent', 0)}%
- Full catalog: ~{preview.context_savings.get('full_catalog_estimated_tokens', 0)} tokens
- Selected context: ~{preview.context_savings.get('selected_estimated_tokens', 0)} tokens

---

## Route Preview ({len(preview.routes)})

{'\n'.join(route_lines) if route_lines else '(None)'}

---

## Provenance and Policy Constraints

- All routes enforce transitive prohibited models: {', '.join(PROHIBITED_MODELS)}.
- Execution stage must operate strictly inside approved paths: {', '.join(preview.allowed_paths)}.
"""

    handoff_path.write_text(content, encoding="utf-8")

    record.status = "dispatched"
    record.handoff_path = str(handoff_path)
    _save_record(brain, record)

    append_journey(
        brain,
        f"Orchestration Dispatched: {orchestration_id}",
        [f"Handoff: {handoff_path}"],
    )

    return {
        "orchestration_id": orchestration_id,
        "status": "dispatched",
        "handoff_path": str(handoff_path),
        "handoff_exists": True,
        "instruction": (
            "Orchestration dispatched. Run guardian orchestrate show "
            f"--id {orchestration_id} for details."
        ),
    }


def orchestrate_show(brain: ProjectBrain, orchestration_id: str) -> dict[str, Any]:
    record = _load_record(brain, orchestration_id)
    return _serialize_record(record)


def orchestrate_list(brain: ProjectBrain) -> list[dict[str, Any]]:
    directory = _orchestrations_dir(brain)
    if not directory.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("orch-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            records.append({
                "id": data.get("id", path.stem),
                "task": data.get("task", "?"),
                "status": data.get("status", "?"),
                "risk_profile": data.get("preview", {}).get("risk_profile", "?"),
                "allowed_paths": data.get("preview", {}).get("allowed_paths", []),
                "workflow_id": data.get("workflow_id"),
                "handoff_path": data.get("handoff_path"),
                "created_at": data.get("created_at", "?"),
                "updated_at": data.get("updated_at", "?"),
            })
        except Exception:
            continue
    return records


def orchestrate_recover(brain: ProjectBrain, orchestration_id: str) -> dict[str, Any]:
    """Idempotent recovery: return current orchestration state without side effects."""
    record = _load_record(brain, orchestration_id)
    return {
        "orchestration_id": record.id,
        "status": record.status,
        "workflow_id": record.workflow_id,
        "handoff_path": record.handoff_path,
        "recovery_action": f"Returned current state ({record.status}) for orchestration {record.id}",
        "note": "Idempotent recovery completed; returned current orchestration state.",
    }



