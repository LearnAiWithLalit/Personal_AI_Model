"""Token-efficient specialist profile catalog and deterministic task routing.

Profiles are role metadata, not continuously running agents.  Guardian searches
the compact index first and expands only the selected profiles into a handoff.
"""

from __future__ import annotations

import json
import re
from hashlib import sha256
from dataclasses import asdict, dataclass
from typing import Iterable

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, render_context
from guardian_agent.model_policy import PROHIBITED_MODELS


@dataclass(frozen=True)
class AgentProfile:
    id: int
    slug: str
    name: str
    domain: str
    description: str
    triggers: tuple[str, ...]
    capabilities: tuple[str, ...]
    tools: tuple[str, ...]
    skill_hints: tuple[str, ...]
    risk: str
    approval_actions: tuple[str, ...]
    input_contract: str
    output_contract: str
    verification: tuple[str, ...]
    provenance: tuple[str, ...]
    preferred_model_tier: str
    prohibited_models: tuple[str, ...] = PROHIBITED_MODELS


_DOMAINS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("intake-orchestration", (
        "Intent classifier", "Task decomposer", "Requirements interviewer", "Planner",
        "Dependency planner", "Model router", "Tool router", "Budget manager",
        "Context selector", "Memory retriever", "Delegation manager",
        "Parallel-work coordinator", "Conflict resolver", "Progress reporter",
        "Human-approval gate", "Skill and token optimization advisor",
    )),

    ("product-ux", (
        "Product manager", "User-story writer", "Acceptance-criteria writer",
        "Feature prioritizer", "Roadmap agent", "User researcher", "Persona builder",
        "UX researcher", "Information architect", "UX writer", "UI designer",
        "Design-system agent", "Accessibility designer", "Wireframe agent",
        "Usability-test analyst",
    )),
    ("software-architecture", (
        "Solution architect", "Repository mapper", "Codebase archaeologist",
        "API architect", "Database architect", "Event-driven architect",
        "Microservice architect", "Monolith-modularization agent", "Cloud architect",
        "Integration architect", "Performance architect", "Security architect",
        "Data architect", "Migration architect", "Technical decision-record writer",
    )),
    ("coding", (
        "Frontend developer", "Backend developer", "Full-stack developer",
        "Mobile developer", "Desktop-app developer", "CLI developer",
        "Browser-extension developer", "API developer", "Database developer",
        "Python developer", "JavaScript/TypeScript developer", "Java/Kotlin developer",
        "C#/.NET developer", "Go developer", "Rust/C/C++ developer",
    )),
    ("specialized-engineering", (
        "Game developer", "Embedded/IoT developer", "Robotics developer",
        "Blockchain developer", "Data-engineering developer", "ML engineer",
        "LLM/RAG engineer", "Computer-vision engineer", "Speech/audio engineer",
        "GIS developer", "ERP/CRM developer", "Shopify/e-commerce developer",
        "WordPress/CMS developer", "Low-code automation developer",
        "Legacy-code modernization agent",
    )),
    ("quality-debugging", (
        "Bug triager", "Root-cause investigator", "Unit-test writer",
        "Integration-test writer", "End-to-end test agent", "Regression-test agent",
        "Test-data generator", "QA explorer", "Visual-regression tester",
        "Load-test engineer", "Reliability-test engineer", "Fuzzer",
        "Static-analysis agent", "Code-review agent", "PR-review response agent",
    )),
    ("devops-operations", (
        "CI/CD engineer", "Docker/container engineer", "Kubernetes engineer",
        "Terraform/IaC engineer", "Cloud deployment agent", "Release manager",
        "Dependency-upgrade agent", "Package/security-update agent",
        "Observability engineer", "Log analyst", "Incident commander", "SRE agent",
        "Cost-optimization agent", "Backup/recovery agent",
        "Environment/configuration agent",
    )),
    ("security-governance", (
        "Threat-model agent", "Secure-code reviewer", "Vulnerability scanner",
        "Pen-test assistant", "Secrets detector", "IAM/permissions reviewer",
        "Privacy reviewer", "Compliance mapper", "License-compliance agent",
        "Data-classification agent", "Prompt-injection defender",
        "MCP/tool-permission reviewer", "Supply-chain security agent",
        "Audit-evidence collector", "Policy-enforcement agent",
    )),
    ("data-research-knowledge", (
        "Web researcher", "Source verifier", "Citation manager",
        "Competitive-intelligence agent", "Market researcher", "Data analyst",
        "SQL analyst", "Spreadsheet analyst", "Dashboard builder",
        "Data-cleaning agent", "Data-labeling agent", "Document/PDF extractor",
        "Knowledge-base curator", "RAG index manager", "Report writer",
    )),
    ("business-communication", (
        "Technical writer", "API-doc writer", "README agent", "Proposal writer",
        "Sales-research agent", "Lead-qualification agent", "Customer-support agent",
        "Email-drafting agent", "Meeting-notes agent", "Project-manager agent",
        "Hiring/recruiting agent", "Finance-analysis agent",
        "Legal-contract reviewer", "Marketing-content agent",
        "Translation/localization agent",
    )),
)


_DOMAIN_RULES = {
    "intake-orchestration": {
        "description": "Clarify, route, budget, coordinate, and report work",
        "capabilities": ("reasoning", "planning", "routing", "context-management"),
        "tools": ("project-brain", "provider-gateway"),
        "skills": ("guardian-brainstorm", "guardian-plan"),
        "verification": ("requirements are explicit", "route is justified"),
        "tier": "small",
    },
    "product-ux": {
        "description": "Shape useful, usable, accessible product experiences",
        "capabilities": ("product", "ux", "design"),
        "tools": ("project-brain", "browser", "creative-suite"),
        "skills": ("guardian-brainstorm", "guardian-review"),
        "verification": ("acceptance criteria covered", "accessibility considered"),
        "tier": "balanced",
    },
    "software-architecture": {
        "description": "Design maintainable technical systems and boundaries",
        "capabilities": ("architecture", "repository-analysis", "tradeoff-analysis"),
        "tools": ("repository", "project-brain", "web-research"),
        "skills": ("guardian-plan", "guardian-review"),
        "verification": ("constraints traced", "tradeoffs recorded"),
        "tier": "strong",
    },
    "coding": {
        "description": "Implement production-quality software changes",
        "capabilities": ("coding", "testing", "repository-editing"),
        "tools": ("repository", "terminal", "sandbox"),
        "skills": ("guardian-tdd", "guardian-verify"),
        "verification": ("focused tests pass", "diff reviewed"),
        "tier": "strong",
    },
    "specialized-engineering": {
        "description": "Implement domain-specific engineering systems",
        "capabilities": ("specialized-coding", "domain-research", "testing"),
        "tools": ("repository", "terminal", "web-research"),
        "skills": ("guardian-plan", "guardian-tdd", "guardian-verify"),
        "verification": ("domain invariants checked", "tests pass"),
        "tier": "strong",
    },
    "quality-debugging": {
        "description": "Find defects and prove software quality",
        "capabilities": ("debugging", "testing", "review"),
        "tools": ("repository", "terminal", "browser"),
        "skills": ("guardian-debug", "guardian-review", "guardian-verify"),
        "verification": ("failure reproduced", "fresh regression test passes"),
        "tier": "balanced",
    },
    "devops-operations": {
        "description": "Build, deploy, observe, and recover reliable systems",
        "capabilities": ("devops", "operations", "reliability"),
        "tools": ("terminal", "provider-health", "audit-log"),
        "skills": ("guardian-plan", "guardian-verify", "guardian-worktree"),
        "verification": ("rollback exists", "health checks pass"),
        "tier": "strong",
    },
    "security-governance": {
        "description": "Reduce security, privacy, compliance, and tool risks",
        "capabilities": ("security", "governance", "audit"),
        "tools": ("repository", "policy-engine", "audit-log"),
        "skills": ("guardian-review", "guardian-verify"),
        "verification": ("evidence recorded", "high-risk actions gated"),
        "tier": "strong",
    },
    "data-research-knowledge": {
        "description": "Find, verify, transform, and communicate knowledge",
        "capabilities": ("research", "data-analysis", "knowledge-management"),
        "tools": ("web-research", "documents", "project-brain"),
        "skills": ("guardian-plan", "guardian-review"),
        "verification": ("sources verified", "claims trace to evidence"),
        "tier": "balanced",
    },
    "business-communication": {
        "description": "Produce clear business analysis and communication",
        "capabilities": ("writing", "business-analysis", "communication"),
        "tools": ("documents", "project-brain", "web-research"),
        "skills": ("guardian-brainstorm", "guardian-review"),
        "verification": ("audience and purpose matched", "facts reviewed"),
        "tier": "balanced",
    },
}

_HIGH_RISK_WORDS = {
    "security", "vulnerability", "pen-test", "secrets", "iam", "privacy",
    "compliance", "legal", "finance", "payment", "deployment", "migration",
    "backup", "incident", "policy", "blockchain",
}
_STOP_WORDS = {
    "a", "an", "and", "agent", "for", "in", "of", "or", "the", "to", "with",
    "developer", "engineer", "writer", "manager", "analyst",
}
_TOKEN_NORMALIZATION = {
    "coding": "code",
    "debugging": "debug",
    "planning": "plan",
    "reasoning": "reason",
    "routing": "route",
    "testing": "test",
}
_ALIASES = {
    "frontend": ("react", "vue", "css", "browser", "ui"),
    "backend": ("server", "service", "endpoint", "business logic"),
    "api": ("rest", "graphql", "endpoint", "openapi"),
    "database": ("schema", "query", "sql", "migration"),
    "accessibility": ("accessible", "a11y", "wcag", "screen reader", "keyboard"),
    "ci": ("pipeline", "github actions", "continuous integration"),
    "cd": ("release", "continuous deployment"),
    "llm": ("language model", "prompt", "rag", "inference"),
    "rag": ("retrieval", "embedding", "vector database"),
    "seo": ("search engine", "structured data", "crawlability"),
    "mcp": ("model context protocol", "tool permission"),
    "root": ("cause", "debug", "failure"),
    "readme": ("documentation", "repository overview"),
}
_PROFILE_HINTS = {
    "a11y": ("accessibility-designer",),
    "accessible": ("accessibility-designer",),
    "android": ("mobile-developer",),
    "api": ("api-architect", "api-developer"),
    "aws": ("cloud-architect", "cloud-deployment-agent"),
    "captcha": ("human-approval-gate", "browser-extension-developer"),
    "citation": ("citation-manager", "source-verifier"),
    "contract": ("legal-contract-reviewer",),
    "docker": ("docker-container-engineer",),
    "email": ("email-drafting-agent",),
    "figma": ("ui-designer", "design-system-agent"),
    "flutter": ("mobile-developer",),
    "incident": ("incident-commander", "sre-agent"),
    "ios": ("mobile-developer",),
    "kubernetes": ("kubernetes-engineer",),
    "migration": ("migration-architect", "database-developer"),
    "payment": ("finance-analysis-agent", "security-architect"),
    "pdf": ("document-pdf-extractor",),
    "react": ("frontend-developer",),
    "rest": ("api-architect", "api-developer"),
    "seo": ("marketing-content-agent", "web-researcher"),
    "sql": ("sql-analyst", "database-developer"),
    "terraform": ("terraform-iac-engineer",),
    "test": ("unit-test-writer",),
    "translate": ("translation-localization-agent",),
    "typescript": ("javascript-typescript-developer",),
    "vue": ("frontend-developer",),
    "wcag": ("accessibility-designer",),
}


def _slug(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")


def _tokens(value: str) -> set[str]:
    normalized = set()
    for token in re.findall(r"[a-z0-9+#.]+", value.lower()):
        if len(token) > 3 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif (
            len(token) > 3
            and token.endswith("s")
            and not token.endswith(("ss", "is", "us"))
        ):
            token = token[:-1]
        token = _TOKEN_NORMALIZATION.get(token, token)
        if len(token) > 1 and token not in _STOP_WORDS:
            normalized.add(token)
    return normalized


def _build_catalog() -> tuple[AgentProfile, ...]:
    profiles: list[AgentProfile] = []
    profile_id = 1
    for domain, names in _DOMAINS:
        rule = _DOMAIN_RULES[domain]
        for name in names:
            name_tokens = sorted(_tokens(name))
            aliases = tuple(
                alias
                for token in name_tokens
                for alias in _ALIASES.get(token, ())
            )
            triggers = tuple(dict.fromkeys((*name_tokens, *aliases, domain.replace("-", " "))))
            risk = "high" if _tokens(name) & _HIGH_RISK_WORDS else (
                "medium" if domain in {"devops-operations", "software-architecture"} else "low"
            )
            approvals = (
                ("external-write", "credential-use", "production-change")
                if risk == "high"
                else ("external-write",) if risk == "medium" else ()
            )
            profiles.append(AgentProfile(
                id=profile_id,
                slug=_slug(name),
                name=name,
                domain=domain,
                description=f"{name} — {rule['description'].lower()}.",
                triggers=triggers,
                capabilities=rule["capabilities"],
                tools=rule["tools"],
                skill_hints=rule["skills"],
                risk=risk,
                approval_actions=approvals,
                input_contract="Confirmed task, constraints, relevant project context, and allowed tools.",
                output_contract="Evidence-backed specialist result, assumptions, risks, and verification status.",
                verification=rule["verification"],
                provenance=("guardian-original-150",),
                preferred_model_tier=rule["tier"],
            ))
            profile_id += 1
    return tuple(profiles)


CATALOG = _build_catalog()


def list_profiles(domain: str | None = None) -> list[dict]:
    """List compact profile metadata without expanding full handoff contracts."""
    profiles = CATALOG
    if domain:
        profiles = tuple(profile for profile in profiles if profile.domain == domain)
        if not profiles:
            raise GuardianError(f"Unknown or empty profile domain: {domain}")
    return [
        {
            "id": profile.id,
            "slug": profile.slug,
            "name": profile.name,
            "domain": profile.domain,
            "description": profile.description,
            "risk": profile.risk,
        }
        for profile in profiles
    ]


def get_profile(identifier: str | int) -> dict:
    """Expand one profile by numeric ID or slug."""
    wanted = str(identifier).strip().lower()
    for profile in CATALOG:
        if str(profile.id) == wanted or profile.slug == wanted:
            return _serialize(profile)
    raise GuardianError(f"Unknown agent profile: {identifier}")


def _serialize(profile: AgentProfile) -> dict:
    result = asdict(profile)
    return {key: list(value) if isinstance(value, tuple) else value for key, value in result.items()}


def select_profiles(task: str, limit: int = 5, domain: str | None = None) -> dict:
    """Return only the highest-scoring profiles and context-savings telemetry."""
    if not task.strip():
        raise GuardianError("Profile selection requires a non-empty task.")
    if limit < 1 or limit > 20:
        raise GuardianError("Profile selection limit must be between 1 and 20.")
    task_tokens = _tokens(task)
    candidates = [profile for profile in CATALOG if domain is None or profile.domain == domain]
    if not candidates:
        raise GuardianError(f"Unknown or empty profile domain: {domain}")

    ranked: list[tuple[int, int, AgentProfile, list[str]]] = []
    for profile in candidates:
        name_tokens = _tokens(profile.name)
        trigger_tokens = _tokens(" ".join(profile.triggers))
        capability_tokens = _tokens(" ".join(profile.capabilities))
        domain_tokens = _tokens(profile.domain.replace("-", " "))
        matched = sorted(task_tokens & (name_tokens | trigger_tokens | capability_tokens | domain_tokens))
        phrase_bonus = 12 if profile.name.lower() in task.lower() else 0
        hint_matches = sorted(
            token for token in task_tokens
            if profile.slug in _PROFILE_HINTS.get(token, ())
        )
        matched = sorted(set(matched) | set(hint_matches))
        hint_bonus = 10 * len(hint_matches)
        score = (
            phrase_bonus
            + hint_bonus
            + 8 * len(task_tokens & name_tokens)
            + 4 * len(task_tokens & trigger_tokens)
            + 2 * len(task_tokens & capability_tokens)
            + len(task_tokens & domain_tokens)
        )
        ranked.append((score, -profile.id, profile, matched))
    ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))

    relevant = [item for item in ranked if item[0] > 0]
    if not relevant:
        relevant = [next(item for item in ranked if item[2].slug == "intent-classifier")]

    # Greedy diversity prevents one repeated word such as "API" from filling
    # every slot with near-duplicate roles. It still preserves the raw score.
    chosen: list[tuple[int, int, AgentProfile, list[str], int]] = []
    covered_terms: set[str] = set()
    domain_counts: dict[str, int] = {}
    remaining = list(relevant)
    while remaining and len(chosen) < limit:
        def adjusted(item: tuple[int, int, AgentProfile, list[str]]) -> tuple[int, int, int]:
            score, negative_id, profile, matched = item
            matched_set = set(matched)
            duplicate_penalty = 10 * len(matched_set & covered_terms)
            novelty_bonus = 14 * len(matched_set - covered_terms)
            domain_penalty = 2 * domain_counts.get(profile.domain, 0)
            return score + novelty_bonus - duplicate_penalty - domain_penalty, score, negative_id

        best = max(remaining, key=adjusted)
        if chosen and adjusted(best)[0] <= 0:
            break
        remaining.remove(best)
        score, negative_id, profile, matched = best
        routing_score = adjusted(best)[0]
        chosen.append((score, negative_id, profile, matched, routing_score))
        covered_terms.update(matched)
        domain_counts[profile.domain] = domain_counts.get(profile.domain, 0) + 1

    selected = []
    for score, _, profile, matched, routing_score in chosen:
        expanded = _serialize(profile)
        expanded["match_score"] = score
        expanded["routing_score"] = routing_score
        expanded["matched_terms"] = matched
        selected.append(expanded)

    full_chars = len(json.dumps([_serialize(profile) for profile in CATALOG], separators=(",", ":")))
    selected_chars = len(json.dumps(selected, separators=(",", ":")))
    return {
        "task": task,
        "selected": selected,
        "catalog_count": len(CATALOG),
        "context": {
            "full_catalog_estimated_tokens": (full_chars + 3) // 4,
            "selected_estimated_tokens": (selected_chars + 3) // 4,
            "estimated_tokens_saved": max(0, (full_chars - selected_chars) // 4),
            "estimated_savings_percent": round((1 - selected_chars / full_chars) * 100, 1),
            "method": "deterministic metadata search; approximately four characters per token",
        },
    }


def validate_catalog(profiles: Iterable[AgentProfile] = CATALOG) -> dict:
    """Validate identity, coverage, contracts, and model safety invariants."""
    items = tuple(profiles)
    errors: list[str] = []
    ids = [profile.id for profile in items]
    slugs = [profile.slug for profile in items]
    expected_domains = {domain for domain, _ in _DOMAINS}
    actual_domains = {profile.domain for profile in items}
    if len(items) < 150:
        errors.append("catalog must contain at least 150 profiles")
    if len(ids) != len(set(ids)):
        errors.append("profile IDs must be unique")
    if len(slugs) != len(set(slugs)):
        errors.append("profile slugs must be unique")
    if ids != list(range(1, len(items) + 1)):
        errors.append("profile IDs must be contiguous starting at 1")
    if actual_domains != expected_domains:
        errors.append("catalog must cover all configured domains")
    for profile in items:
        if not all((profile.description, profile.triggers, profile.capabilities, profile.verification)):
            errors.append(f"profile {profile.id} has an incomplete contract")
        if not set(PROHIBITED_MODELS).issubset(profile.prohibited_models):
            errors.append(f"profile {profile.id} does not enforce prohibited models")
    return {
        "valid": not errors,
        "count": len(items),
        "domain_count": len(actual_domains),
        "domains": sorted(actual_domains),
        "errors": errors,
    }


def prepare_profile_handoff(brain: ProjectBrain, task: str, limit: int = 5) -> dict:
    """Save a bounded model handoff containing only selected role contracts."""
    routing = select_profiles(task, limit)
    digest = sha256(task.encode("utf-8")).hexdigest()[:10]
    path = brain.directory / "research" / f"profile_handoff_{digest}.md"
    selected = routing["selected"]
    role_sections = []
    for profile in selected:
        role_sections.append(
            f"### {profile['name']} (`{profile['slug']}`)\n\n"
            f"- Mission: {profile['description']}\n"
            f"- Capabilities: {', '.join(profile['capabilities'])}\n"
            f"- Allowed tool classes: {', '.join(profile['tools'])}\n"
            f"- Suggested skills: {', '.join(profile['skill_hints'])}\n"
            f"- Risk: {profile['risk']}\n"
            f"- Output: {profile['output_contract']}\n"
            f"- Verify: {'; '.join(profile['verification'])}\n"
            f"- Prohibited models: {', '.join(profile['prohibited_models'])}"
        )
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        "# Guardian Specialist Handoff\n\n"
        f"## Task\n\n{task.strip()}\n\n"
        "## Selected roles\n\n"
        + "\n\n".join(role_sections)
        + "\n\n## Compact project context\n\n"
        + render_context(brain)
        + "\n",
        encoding="utf-8",
    )
    append_journey(
        brain,
        "Specialist Profiles Routed",
        [
            f"Task: {task.strip()}",
            "Roles: " + ", ".join(profile["name"] for profile in selected),
            f"Estimated catalog context saved: {routing['context']['estimated_savings_percent']}%",
            f"Handoff: {path.name}",
        ],
    )
    return {
        **routing,
        "handoff_path": str(path),
        "status": "prepared_for_supervising_model",
        "final_authority": "user or configured primary model",
    }
