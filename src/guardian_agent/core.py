"""Durable project-brain operations.

This module intentionally uses only Python's standard library so the first
Guardian workflow can run locally before model providers are configured.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


AGENT_DIR = ".agent"
DOCUMENTS = (
    "PROJECT.md",
    "REQUIREMENTS.md",
    "PLAN.md",
    "DECISIONS.md",
    "JOURNEY.md",
    "CONTEXT.md",
    "LESSONS.md",
    "TASKS.md",
    "COSTS.md",
    "SKILLS.md",
)
SUBDIRECTORIES = ("research", "artifacts", "audit", "tasks")


class GuardianError(RuntimeError):
    """Raised when a project-brain operation cannot be completed safely."""


@dataclass(frozen=True)
class ProjectBrain:
    root: Path

    @property
    def directory(self) -> Path:
        return self.root / AGENT_DIR

    def document(self, name: str) -> Path:
        if name not in DOCUMENTS:
            raise GuardianError(f"Unknown project-brain document: {name}")
        return self.directory / name


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def markdown_escape(value: str) -> str:
    """Normalize untrusted CLI text for readable Markdown records."""
    return value.strip().replace("\x00", "")


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def initialize(root: Path, name: str, purpose: str) -> ProjectBrain:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    brain = ProjectBrain(root)
    brain.directory.mkdir(exist_ok=True)
    for subdirectory in SUBDIRECTORIES:
        (brain.directory / subdirectory).mkdir(exist_ok=True)

    clean_name = markdown_escape(name) or root.name
    clean_purpose = markdown_escape(purpose) or "Purpose not confirmed yet."
    templates = {
        "PROJECT.md": f"# Project\n\n- **Name:** {clean_name}\n- **Purpose:** {clean_purpose}\n- **Created:** {now_utc()}\n- **Status:** Discovery\n\n## Constraints\n\n- Local-first by default.\n- Never store secrets in `.agent/` files.\n",
        "REQUIREMENTS.md": "# Requirements\n\n## Confirmed\n\n_No confirmed requirements yet._\n\n## Pending confirmation\n\n_No pending requirements._\n",
        "PLAN.md": "# Plan\n\n## Current phase\n\n- [ ] Discovery and requirement confirmation\n\n## Confirmed work\n\n_No confirmed work items yet._\n",
        "DECISIONS.md": "# Decisions\n\n_Record decisions, alternatives, and rationale here._\n",
        "JOURNEY.md": "# Development Journey\n\n_Chronological project history._\n",
        "CONTEXT.md": "# Compact Handoff Context\n\n_Run `guardian context` to refresh this file._\n",
        "LESSONS.md": "# Lessons\n\n_Reusable patterns, mistakes, fixes, and prevention checks._\n",
        "TASKS.md": "# Tasks\n\n_No tasks tracked yet._\n",
        "COSTS.md": "# Costs and Capacity\n\n_No model or tool usage recorded yet._\n",
        "SKILLS.md": "# Enabled Skills\n\n_No skills enabled yet._\n",
    }
    for filename, content in templates.items():
        _write_if_missing(brain.document(filename), content)

    append_journey(
        brain,
        "Project brain initialized",
        [
            f"Project name: {clean_name}",
            f"Purpose: {clean_purpose}",
            "Created durable project-memory files and directories.",
        ],
    )
    return brain


def require_brain(root: Path) -> ProjectBrain:
    brain = ProjectBrain(root.resolve())
    if not brain.directory.is_dir():
        raise GuardianError(
            f"No {AGENT_DIR}/ directory found in {brain.root}. Run `guardian init` first."
        )
    missing = [name for name in DOCUMENTS if not brain.document(name).is_file()]
    if missing:
        raise GuardianError(f"Project brain is incomplete; missing: {', '.join(missing)}")
    return brain


def append_section(path: Path, title: str, lines: list[str]) -> None:
    safe_lines = [markdown_escape(line) for line in lines if markdown_escape(line)]
    body = "\n".join(f"- {line}" for line in safe_lines) or "- No details provided."
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n\n## {title}\n\n{body}\n")


def append_journey(brain: ProjectBrain, title: str, lines: list[str]) -> None:
    append_section(brain.document("JOURNEY.md"), f"{now_utc()} — {markdown_escape(title)}", lines)


def replace_pending_requirement(brain: ProjectBrain, request: str) -> None:
    path = brain.document("REQUIREMENTS.md")
    text = path.read_text(encoding="utf-8")
    heading = "## Pending confirmation"
    prefix, found, remainder = text.partition(heading)
    if not found:
        raise GuardianError("REQUIREMENTS.md has an invalid template.")
    pending = f"{heading}\n\n- **Recorded:** {now_utc()}\n- **Request:** {markdown_escape(request)}\n"
    later_confirmed_marker = "\n## Confirmed —"
    _, later_confirmed, later_entries = remainder.partition(later_confirmed_marker)
    preserved_entries = f"{later_confirmed_marker}{later_entries}" if later_confirmed else ""
    path.write_text(
        prefix.rstrip() + "\n\n" + pending + preserved_entries,
        encoding="utf-8",
    )


def intake(brain: ProjectBrain, request: str) -> None:
    clean_request = markdown_escape(request)
    if not clean_request:
        raise GuardianError("A non-empty requirement is required.")
    replace_pending_requirement(brain, clean_request)
    append_journey(
        brain,
        "Requirement received",
        [f"Pending user confirmation: {clean_request}", "No implementation should begin until confirmation."],
    )


def _pending_request(brain: ProjectBrain) -> str | None:
    text = brain.document("REQUIREMENTS.md").read_text(encoding="utf-8")
    marker = "- **Request:** "
    for line in reversed(text.splitlines()):
        if line.startswith(marker):
            request = line.removeprefix(marker).strip()
            return None if request == "_No pending requirements._" else request
    return None


def confirm(
    brain: ProjectBrain,
    summary: str,
    *,
    reference_id: str | None = None,
    original_request: str | None = None,
) -> None:
    clean_summary = markdown_escape(summary)
    if not clean_summary:
        raise GuardianError("A non-empty confirmed summary is required.")
    clean_reference = markdown_escape(reference_id or "")
    clean_original = markdown_escape(original_request or "")
    requirements = brain.document("REQUIREMENTS.md")
    requirements_text = requirements.read_text(encoding="utf-8")
    reference_marker = (
        f"- **Reference ID:** {clean_reference}" if clean_reference else ""
    )
    plan_marker = f"<!-- guardian-reference:{clean_reference} -->" if clean_reference else ""
    already_confirmed = bool(reference_marker and reference_marker in requirements_text)

    if not clean_original:
        clean_original = _pending_request(brain) or "Not recorded"
        replace_pending_requirement(brain, "_No pending requirements._")

    if not already_confirmed:
        reference_line = f"- **Reference ID:** {clean_reference}\n" if clean_reference else ""
        with requirements.open("a", encoding="utf-8") as handle:
            handle.write(
                f"\n\n## Confirmed — {now_utc()}\n\n"
                f"{reference_line}"
                f"- **Summary:** {clean_summary}\n"
                f"- **Original request:** {clean_original}\n"
                "- **Status:** Approved for planning and implementation.\n"
            )

    plan = brain.document("PLAN.md")
    plan_text = plan.read_text(encoding="utf-8")
    if not plan_marker or plan_marker not in plan_text:
        marker_suffix = f" {plan_marker}" if plan_marker else ""
        with plan.open("a", encoding="utf-8") as handle:
            handle.write(f"\n\n- [ ] {clean_summary}{marker_suffix}\n")

    if already_confirmed:
        return
    append_journey(
        brain,
        "Requirement confirmed",
        [f"Confirmed scope: {clean_summary}", "Added to delivery plan."],
    )


def record_decision(brain: ProjectBrain, title: str, detail: str) -> None:
    clean_title, clean_detail = markdown_escape(title), markdown_escape(detail)
    if not clean_title or not clean_detail:
        raise GuardianError("Both a decision title and detail are required.")
    append_section(brain.document("DECISIONS.md"), f"{now_utc()} — {clean_title}", [clean_detail])
    append_journey(brain, "Decision recorded", [f"{clean_title}: {clean_detail}"])


def record_lesson(brain: ProjectBrain, title: str, detail: str) -> None:
    clean_title, clean_detail = markdown_escape(title), markdown_escape(detail)
    if not clean_title or not clean_detail:
        raise GuardianError("Both a lesson title and detail are required.")
    append_section(brain.document("LESSONS.md"), f"{now_utc()} — {clean_title}", [clean_detail])
    append_journey(brain, "Lesson captured", [f"{clean_title}: {clean_detail}"])


def _tail_sections(text: str, limit: int) -> str:
    sections = text.split("\n## ")
    header = sections[0].strip()
    selected = sections[1:][-limit:]
    return "\n\n".join([header, *["## " + item.strip() for item in selected]]).strip()


def render_context(brain: ProjectBrain) -> str:
    project = brain.document("PROJECT.md").read_text(encoding="utf-8").strip()
    requirements = _tail_sections(brain.document("REQUIREMENTS.md").read_text(encoding="utf-8"), 3)
    plan = brain.document("PLAN.md").read_text(encoding="utf-8").strip()
    decisions = _tail_sections(brain.document("DECISIONS.md").read_text(encoding="utf-8"), 3)
    lessons = _tail_sections(brain.document("LESSONS.md").read_text(encoding="utf-8"), 5)
    reusable_path = brain.directory / "research" / "REUSABLE_LESSONS.md"
    reusable_lessons = (
        reusable_path.read_text(encoding="utf-8").strip()
        if reusable_path.is_file()
        else ""
    )
    context = (
        "# Guardian Handoff Context\n\n"
        "Use this document as project context. Follow confirmed requirements and do not expose secrets.\n\n"
        f"{project}\n\n"
        f"{requirements}\n\n"
        f"{plan}\n\n"
        f"{decisions}\n\n"
        f"{lessons}\n\n"
        f"{reusable_lessons}\n"
    )
    brain.document("CONTEXT.md").write_text(context, encoding="utf-8")
    return context


def status(brain: ProjectBrain) -> dict[str, str | int | None]:
    requirements_text = brain.document("REQUIREMENTS.md").read_text(encoding="utf-8")
    journey_text = brain.document("JOURNEY.md").read_text(encoding="utf-8")
    return {
        "project": str(brain.root),
        "pending_requirement": _pending_request(brain),
        "confirmed_requirements": requirements_text.count("## Confirmed —"),
        "journey_entries": journey_text.count("## "),
        "skills": brain.document("SKILLS.md").read_text(encoding="utf-8").count("## "),
    }
