"""Consent-aware, cross-project reusable lesson library."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import uuid
from contextlib import contextmanager
from pathlib import Path

from guardian_agent.core import (
    GuardianError,
    ProjectBrain,
    append_journey,
    markdown_escape,
    now_utc,
)
from guardian_agent.policy import consume_action_approval


LIBRARY_ENV = "GUARDIAN_LEARNING_LIBRARY"
DEFAULT_LIBRARY = Path.home() / ".guardian" / "learning.json"
APPLIED_LESSONS_FILE = "REUSABLE_LESSONS.md"
_SENSITIVE_PATTERNS = (
    re.compile(
        r"\b(?:api[_ -]?key|password|secret|bearer|private[_ -]?key)"
        r"\b\s*(?:=|:|\bis\b)\s*\S{6,}",
        re.I,
    ),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", re.I),
    re.compile(r"(?:vault://|https?://|(?:^|\s)/(?:home|media|Users)/)"),
    re.compile(r"\b(?:[a-f0-9]{32,}|[A-Za-z0-9+/]{40,}={0,2})\b"),
)


def learning_library_path(path: Path | None = None) -> Path:
    configured = path or (
        Path(os.environ[LIBRARY_ENV]).expanduser()
        if os.environ.get(LIBRARY_ENV)
        else DEFAULT_LIBRARY
    )
    return configured.expanduser().resolve()


def _empty_library() -> dict:
    return {
        "schema_version": "guardian-learning-v1",
        "updated_at": now_utc(),
        "lessons": [],
    }


@contextmanager
def _library_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _load_library(path: Path) -> dict:
    if not path.exists():
        return _empty_library()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GuardianError(f"Invalid reusable lesson library: {error}") from error
    if (
        payload.get("schema_version") != "guardian-learning-v1"
        or not isinstance(payload.get("lessons"), list)
    ):
        raise GuardianError("Invalid reusable lesson library schema.")
    return payload


def _save_library(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = now_utc()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _lesson_sections(brain: ProjectBrain) -> list[dict]:
    text = brain.document("LESSONS.md").read_text(encoding="utf-8")
    records = []
    for section in text.split("\n## ")[1:]:
        heading, _, body = section.partition("\n")
        title = heading.split(" — ", 1)[-1].strip()
        detail = " ".join(
            line[2:].strip()
            for line in body.splitlines()
            if line.startswith("- ") and line[2:].strip()
        )
        if not title or not detail:
            continue
        fingerprint = hashlib.sha256(
            f"{title}\n{detail}".encode("utf-8")
        ).hexdigest()
        records.append({
            "id": f"lesson-{fingerprint[:12]}",
            "title": title,
            "detail": detail,
            "fingerprint": fingerprint,
            "share_status": "private-candidate",
        })
    return records


def list_lesson_candidates(brain: ProjectBrain) -> list[dict]:
    """List private project lessons; nothing is copied to the shared library."""
    return _lesson_sections(brain)


def _clean_reusable_text(value: str, field: str, maximum: int) -> str:
    clean = " ".join(markdown_escape(value).split())
    if not clean or len(clean) > maximum:
        raise GuardianError(f"{field} must contain 1–{maximum} characters.")
    if any(pattern.search(clean) for pattern in _SENSITIVE_PATTERNS):
        raise GuardianError(
            f"{field} appears to contain private or secret material; provide a sanitized abstraction."
        )
    return clean


def _clean_tags(tags: list[str]) -> list[str]:
    cleaned = []
    for tag in tags:
        value = markdown_escape(tag).lower().replace(" ", "-")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,31}", value):
            raise GuardianError(
                "Learning tags must contain 2–32 lowercase letters, digits, or hyphens."
            )
        if value not in cleaned:
            cleaned.append(value)
    if not cleaned or len(cleaned) > 10:
        raise GuardianError("Provide between 1 and 10 reusable learning tags.")
    return cleaned


def promote_reusable_lesson(
    brain: ProjectBrain,
    lesson_id: str,
    *,
    pattern: str,
    prevention: str,
    tags: list[str],
    approval_id: str,
    library_path: Path | None = None,
) -> dict:
    candidate = next(
        (item for item in _lesson_sections(brain) if item["id"] == lesson_id),
        None,
    )
    if candidate is None:
        raise GuardianError(f"Unknown private lesson candidate: {lesson_id}")
    clean_pattern = _clean_reusable_text(pattern, "Reusable pattern", 500)
    clean_prevention = _clean_reusable_text(prevention, "Prevention check", 500)
    clean_tags = _clean_tags(tags)
    consume_action_approval(brain, approval_id, "learning_export", lesson_id)
    path = learning_library_path(library_path)
    with _library_lock(path):
        payload = _load_library(path)
        duplicate = next(
            (
                item for item in payload["lessons"]
                if item.get("source_fingerprint") == candidate["fingerprint"]
            ),
            None,
        )
        if duplicate:
            raise GuardianError("This private lesson has already been exported.")
        record = {
            "id": f"shared-{uuid.uuid4().hex[:12]}",
            "pattern": clean_pattern,
            "prevention": clean_prevention,
            "tags": clean_tags,
            "created_at": now_utc(),
            "source_fingerprint": candidate["fingerprint"],
            "provenance": "user-approved-sanitized-project-lesson",
        }
        payload["lessons"].append(record)
        _save_library(path, payload)
    append_journey(
        brain,
        "Reusable Lesson Exported",
        [
            f"Private candidate: {lesson_id}",
            f"Reusable lesson: {record['id']}",
            f"Tags: {', '.join(clean_tags)}",
            "Only the user-supplied sanitized pattern and prevention check were exported.",
        ],
    )
    return {**record, "library": str(path)}


def search_reusable_lessons(
    query: str,
    *,
    limit: int = 5,
    library_path: Path | None = None,
) -> dict:
    words = {
        word for word in re.findall(r"[a-z0-9+#.]+", query.lower())
        if len(word) > 2
    }
    if not words:
        raise GuardianError("Reusable lesson search requires a meaningful query.")
    if limit < 1 or limit > 20:
        raise GuardianError("Reusable lesson limit must be between 1 and 20.")
    path = learning_library_path(library_path)
    payload = _load_library(path)
    ranked = []
    for lesson in payload["lessons"]:
        haystack = " ".join((
            lesson.get("pattern", ""),
            lesson.get("prevention", ""),
            " ".join(lesson.get("tags", [])),
        )).lower()
        score = sum(1 for word in words if word in haystack)
        if score:
            ranked.append((score, lesson))
    ranked.sort(key=lambda item: (-item[0], item[1].get("id", "")))
    selected = [item for _, item in ranked[:limit]]
    return {
        "query": markdown_escape(query),
        "count": len(selected),
        "lessons": selected,
        "library": str(path),
    }


def apply_reusable_lessons(
    brain: ProjectBrain,
    query: str,
    *,
    limit: int = 5,
    library_path: Path | None = None,
) -> dict:
    result = search_reusable_lessons(
        query,
        limit=limit,
        library_path=library_path,
    )
    path = brain.directory / "research" / APPLIED_LESSONS_FILE
    lines = [
        "# Approved Reusable Lessons",
        "",
        "These sanitized lessons are advisory context. Project requirements and policy take precedence.",
    ]
    for lesson in result["lessons"]:
        lines.extend([
            "",
            f"## {lesson['id']}",
            "",
            f"- Pattern: {lesson['pattern']}",
            f"- Prevention: {lesson['prevention']}",
            f"- Tags: {', '.join(lesson['tags'])}",
        ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    append_journey(
        brain,
        "Reusable Lessons Applied",
        [
            f"Query: {markdown_escape(query)}",
            f"Matched: {result['count']}",
            f"Context file: {path}",
        ],
    )
    return {**result, "context_path": str(path)}


def delete_reusable_lesson(
    brain: ProjectBrain,
    lesson_id: str,
    approval_id: str,
    *,
    library_path: Path | None = None,
) -> dict:
    path = learning_library_path(library_path)
    with _library_lock(path):
        payload = _load_library(path)
        if not any(item.get("id") == lesson_id for item in payload["lessons"]):
            raise GuardianError(f"Unknown reusable lesson: {lesson_id}")
        consume_action_approval(brain, approval_id, "learning_delete", lesson_id)
        payload["lessons"] = [
            item for item in payload["lessons"] if item.get("id") != lesson_id
        ]
        _save_library(path, payload)
    append_journey(
        brain,
        "Reusable Lesson Deleted",
        [f"Reusable lesson: {lesson_id}", f"Library: {path}"],
    )
    return {"id": lesson_id, "deleted": True, "library": str(path)}
