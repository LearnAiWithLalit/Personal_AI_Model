"""External skill discovery, quarantine, provenance, and static inspection.

Remote content is data, never instructions to Guardian. Imports are restricted
to registered HTTPS raw-content prefixes and remain quarantined until a human
approval is consumed.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc
from guardian_agent.policy import consume_action_approval
from guardian_agent.skills import skills_dir


MAX_SKILL_BYTES = 512_000
SOURCE_REGISTRY: dict[str, dict] = {
    "orchestra-ai-research": {
        "name": "Orchestra Research AI Research Skills",
        "url": "https://github.com/Orchestra-Research/AI-research-SKILLs",
        "kind": "repository",
        "raw_prefix": "https://raw.githubusercontent.com/Orchestra-Research/AI-research-SKILLs/",
        "license": "MIT",
        "focus": (
            "ai research", "model architecture", "fine tuning", "evaluation",
            "rag", "agents", "mlops", "multimodal", "inference",
        ),
        "importable": True,
    },
    "addy-web-quality": {
        "name": "Addy Osmani Web Quality Skills",
        "url": "https://github.com/addyosmani/web-quality-skills",
        "kind": "repository",
        "raw_prefix": "https://raw.githubusercontent.com/addyosmani/web-quality-skills/",
        "license": "MIT",
        "focus": (
            "web quality", "performance", "core web vitals", "accessibility",
            "seo", "best practices", "lighthouse",
        ),
        "importable": True,
    },
    "voltagent-awesome": {
        "name": "VoltAgent Awesome Agent Skills",
        "url": "https://github.com/VoltAgent/awesome-agent-skills",
        "kind": "curated-index",
        "license": "varies by linked project",
        "focus": (
            "agent skills", "coding", "product", "security", "documents",
            "databases", "deployment", "design",
        ),
        "importable": False,
    },
    "thinking-partner": {
        "name": "Thinking Partner",
        "url": "https://skillsllm.com/skill/thinking-partner",
        "kind": "skill-directory",
        "license": "verify upstream before import",
        "focus": (
            "critical thinking", "decision making", "mental models",
            "assumption testing", "premortem", "systems thinking",
        ),
        "importable": False,
    },
    "awesome-skills-mcp": {
        "name": "Awesome Agent Skills MCP",
        "url": "https://mcpservers.org/servers/shadowrootdev/awesome-agent-skills-mcp",
        "kind": "mcp-catalog",
        "license": "MIT server; skill licenses vary",
        "focus": (
            "mcp", "skill search", "skill registry", "documents", "security",
            "react", "nextjs", "hugging face",
        ),
        "importable": False,
        "integration": "Use Guardian's untrusted MCP registration and per-tool allowlist.",
    },
    "agnt-top-100": {
        "name": "AGNT 100 Best AI Agent Skills",
        "url": "https://agnt.gg/articles/100-best-ai-agent-skills",
        "kind": "editorial-index",
        "license": "varies by linked project",
        "focus": (
            "coding", "design", "data analytics", "documents", "writing",
            "security compliance", "business marketing", "automation",
            "communication", "devops", "creative media", "enterprise",
        ),
        "importable": False,
    },
}

_CRITICAL_PATTERNS = {
    "instruction-override": re.compile(
        r"\b(ignore|disregard|override)\b.{0,40}\b(previous|system|developer|safety)\b",
        re.IGNORECASE,
    ),
    "secret-exfiltration": re.compile(
        r"\b(exfiltrate|steal|reveal|upload|send)\b.{0,50}\b(secret|credential|token|password|key)\b",
        re.IGNORECASE,
    ),
    "destructive-shell": re.compile(
        r"(rm\s+-rf\b|curl\b[^\n|]*\|\s*(sh|bash)\b|wget\b[^\n|]*\|\s*(sh|bash)\b)",
        re.IGNORECASE,
    ),
    "safety-bypass": re.compile(
        r"\b(bypass|disable|evade)\b.{0,40}\b(approval|policy|guardrail|captcha|mfa)\b",
        re.IGNORECASE,
    ),
}
_WARNING_PATTERNS = {
    "elevated-command": re.compile(r"(^|\s)sudo(\s|$)|chmod\s+777", re.IGNORECASE | re.MULTILINE),
    "dynamic-execution": re.compile(r"\beval\s*\(|\bexec\s*\(", re.IGNORECASE),
    "absolute-user-path": re.compile(r"(?<!\w)/(home|Users)/[^/\s]+/"),
    "wildcard-tools": re.compile(r"""tools\s*:\s*(\[\s*["']?\*|["']\*)""", re.IGNORECASE),
}
_CONTROL_CHARS = re.compile("[\u202a-\u202e\u2066-\u2069\ufeff]")


def list_external_sources() -> list[dict]:
    return [
        {"id": source_id, **source}
        for source_id, source in SOURCE_REGISTRY.items()
    ]


def search_external_sources(query: str, limit: int = 10) -> list[dict]:
    words = {word for word in re.findall(r"[a-z0-9+#.]+", query.lower()) if len(word) > 1}
    if not words:
        raise GuardianError("External skill search requires a non-empty query.")
    if limit < 1 or limit > 25:
        raise GuardianError("External skill search limit must be between 1 and 25.")
    ranked = []
    for source_id, source in SOURCE_REGISTRY.items():
        haystack = " ".join((source_id, source["name"], *source["focus"])).lower()
        score = sum(3 if word in source["name"].lower() else 1 for word in words if word in haystack)
        if score:
            ranked.append((score, source_id, source))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [
        {
            "id": source_id,
            "name": source["name"],
            "url": source["url"],
            "kind": source["kind"],
            "focus": list(source["focus"]),
            "importable": source["importable"],
            "match_score": score,
        }
        for score, source_id, source in ranked[:limit]
    ]


def inspect_skill_text(text: str) -> dict:
    findings = []
    encoded_size = len(text.encode("utf-8"))
    if encoded_size > MAX_SKILL_BYTES:
        findings.append({
            "severity": "critical", "code": "oversized",
            "detail": f"Skill exceeds {MAX_SKILL_BYTES} bytes.",
        })
    if _CONTROL_CHARS.search(text):
        findings.append({
            "severity": "critical", "code": "hidden-unicode-control",
            "detail": "Skill contains bidirectional or hidden Unicode control characters.",
        })
    for code, pattern in _CRITICAL_PATTERNS.items():
        if pattern.search(text):
            findings.append({"severity": "critical", "code": code, "detail": "Matched unsafe instruction pattern."})
    for code, pattern in _WARNING_PATTERNS.items():
        if pattern.search(text):
            findings.append({"severity": "warning", "code": code, "detail": "Requires manual review."})
    if len(text.splitlines()) > 500:
        findings.append({
            "severity": "warning", "code": "long-skill-body",
            "detail": "Skill exceeds 500 lines; split details into on-demand references.",
        })
    frontmatter = _parse_frontmatter(text)
    if not frontmatter.get("name") or not frontmatter.get("description"):
        findings.append({
            "severity": "critical", "code": "invalid-frontmatter",
            "detail": "SKILL.md requires name and description frontmatter.",
        })
    critical = sum(item["severity"] == "critical" for item in findings)
    warnings = sum(item["severity"] == "warning" for item in findings)
    return {
        "valid_structure": bool(frontmatter.get("name") and frontmatter.get("description")),
        "name": frontmatter.get("name", ""),
        "description": frontmatter.get("description", ""),
        "line_count": len(text.splitlines()),
        "byte_count": encoded_size,
        "critical_count": critical,
        "warning_count": warnings,
        "risk": "critical" if critical else "review" if warnings else "low",
        "findings": findings,
    }


def _parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    result: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, separator, value = line.partition(":")
        if separator and key.strip() in {"name", "description"}:
            result[key.strip()] = value.strip().strip("\"'")
    return result


def _validate_import_url(source: dict, url: str) -> None:
    if not source.get("importable") or not source.get("raw_prefix"):
        raise GuardianError("This source is discovery-only; follow its upstream license and import a reviewed raw skill explicitly.")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise GuardianError("External skills require an HTTPS URL without embedded credentials.")
    expected = urlparse(source["raw_prefix"])
    if (
        parsed.hostname != expected.hostname
        or not parsed.path.startswith(expected.path)
        or any(segment == ".." for segment in parsed.path.split("/"))
    ):
        raise GuardianError("Skill URL is outside the registered source's raw-content prefix.")
    if not parsed.path.endswith("/SKILL.md"):
        raise GuardianError("External skill URL must point to a SKILL.md file.")


def quarantine_external_skill(
    brain: ProjectBrain,
    source_id: str,
    url: str,
    *,
    timeout: int = 15,
) -> dict:
    source = SOURCE_REGISTRY.get(source_id)
    if not source:
        raise GuardianError(f"Unknown external skill source: {source_id}")
    _validate_import_url(source, url)
    request = urllib.request.Request(url, headers={"User-Agent": "Guardian-Agent/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            _validate_import_url(source, final_url)
            raw = response.read(MAX_SKILL_BYTES + 1)
    except (urllib.error.URLError, OSError) as error:
        raise GuardianError(f"External skill fetch failed: {error}") from error
    if len(raw) > MAX_SKILL_BYTES:
        raise GuardianError(f"External skill exceeds {MAX_SKILL_BYTES} bytes.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GuardianError("External skill must be UTF-8 text.") from error
    inspection = inspect_skill_text(text)
    name = inspection["name"].lower()
    if not name or len(name) > 64 or not re.fullmatch(r"[a-z0-9-]+", name):
        raise GuardianError("Imported skill name must use lowercase letters, digits, and hyphens.")
    destination = skills_dir(brain) / "quarantine" / name
    if destination.exists():
        raise GuardianError(f"Quarantined skill {name!r} already exists.")
    destination.mkdir(parents=True)
    digest = hashlib.sha256(raw).hexdigest()
    (destination / "SKILL.md").write_text(text, encoding="utf-8")
    metadata = {
        "name": name,
        "description": inspection["description"],
        "status": "quarantined",
        "source_id": source_id,
        "source_url": final_url,
        "source_repository": source["url"],
        "source_license": source["license"],
        "sha256": digest,
        "fetched_at": now_utc(),
        "inspection": inspection,
    }
    (destination / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    append_journey(
        brain,
        f"External Skill Quarantined: {name}",
        [f"Source: {source_id}", f"SHA-256: {digest}", f"Risk: {inspection['risk']}"],
    )
    return {
        "name": name,
        "status": "quarantined",
        "path": str(destination),
        "sha256": digest,
        "inspection": inspection,
    }


def inspect_quarantined_skill(brain: ProjectBrain, name: str) -> dict:
    clean_name = name.strip().lower()
    path = skills_dir(brain) / "quarantine" / clean_name
    metadata_path = path / "metadata.json"
    skill_path = path / "SKILL.md"
    if not metadata_path.is_file() or not skill_path.is_file():
        raise GuardianError(f"Quarantined skill {clean_name!r} does not exist.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    current_hash = hashlib.sha256(skill_path.read_bytes()).hexdigest()
    metadata["integrity_valid"] = current_hash == metadata.get("sha256")
    metadata["current_inspection"] = inspect_skill_text(skill_path.read_text(encoding="utf-8"))
    return metadata


def accept_quarantined_skill(brain: ProjectBrain, name: str, approval_id: str) -> dict:
    clean_name = name.strip().lower()
    source = skills_dir(brain) / "quarantine" / clean_name
    if not source.is_dir():
        raise GuardianError(f"Quarantined skill {clean_name!r} does not exist.")
    inspection = inspect_quarantined_skill(brain, clean_name)
    if not inspection["integrity_valid"]:
        raise GuardianError("Quarantined skill changed after import; import it again before review.")
    if inspection["current_inspection"]["critical_count"]:
        raise GuardianError("Critical inspection findings must be resolved before accepting this skill.")
    consume_action_approval(brain, approval_id, "skill_import_accept", clean_name)
    destination = skills_dir(brain) / "drafts" / clean_name
    if destination.exists():
        raise GuardianError(f"Draft skill {clean_name!r} already exists.")
    source.rename(destination)
    metadata_path = destination / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["status"] = "draft"
    metadata["reviewed_at"] = now_utc()
    metadata["review_approval_id"] = approval_id
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    append_journey(
        brain,
        f"External Skill Accepted as Draft: {clean_name}",
        ["It remains untrusted until validation and explicit promotion."],
    )
    return {"name": clean_name, "status": "draft", "path": str(destination / "SKILL.md")}


def audit_external_skills(brain: ProjectBrain) -> dict:
    """Re-scan every external skill and verify reviewed content integrity."""
    base = skills_dir(brain)
    records = []
    for state in ("quarantine", "drafts", "trusted"):
        state_dir = base / state
        for skill_dir in sorted(path for path in state_dir.iterdir() if path.is_dir()):
            metadata_path = skill_dir / "metadata.json"
            skill_path = skill_dir / "SKILL.md"
            if not metadata_path.is_file() or not skill_path.is_file():
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                records.append({
                    "name": skill_dir.name,
                    "state": state,
                    "status": "invalid-metadata",
                })
                continue
            if not metadata.get("source_id"):
                continue
            current_hash = hashlib.sha256(skill_path.read_bytes()).hexdigest()
            inspection = inspect_skill_text(skill_path.read_text(encoding="utf-8"))
            integrity_valid = current_hash == metadata.get("sha256")
            status = (
                "critical-findings" if inspection["critical_count"]
                else "integrity-failed" if not integrity_valid
                else "pass"
            )
            records.append({
                "name": skill_dir.name,
                "state": state,
                "source_id": metadata["source_id"],
                "status": status,
                "integrity_valid": integrity_valid,
                "recorded_sha256": metadata.get("sha256"),
                "current_sha256": current_hash,
                "risk": inspection["risk"],
                "findings": inspection["findings"],
            })
    passed = all(record["status"] == "pass" for record in records)
    append_journey(
        brain,
        "External Skill Audit Completed",
        [
            f"External skills checked: {len(records)}",
            f"Passed: {sum(record['status'] == 'pass' for record in records)}",
            f"Failed: {sum(record['status'] != 'pass' for record in records)}",
        ],
    )
    return {"passed": passed, "count": len(records), "records": records}
