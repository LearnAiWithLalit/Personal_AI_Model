"""Independent, secret-free model-provider registry, router, and completion engine.

The gateway stores provider metadata only. Provider API keys remain in an
environment variable, OS keychain, or encrypted vault.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc, markdown_escape
from guardian_agent.budget import (
    budget_status,
    estimate_route_cost,
    estimate_tokens,
    reserve_budget,
    settle_budget,
)
from guardian_agent.health import check_provider_health, record_provider_error, record_provider_success
from guardian_agent.model_policy import is_model_allowed, require_model_allowed
from guardian_agent.vault import get_secret, redact_secrets
from guardian_agent.provider_capacity import (
    provider_efficiency_penalty,
    provider_prompt_reservation_multiplier,
    provider_quality_adjustment,
    record_provider_capacity,
    require_capacity_available,
)
from guardian_agent.omniroute_logs import omniroute_log_penalty


GATEWAY_FILE = "model-gateway.json"
TASK_CAPABILITIES = {
    "routing": {"routing", "general"},
    "research": {"research", "general"},
    "planning": {"planning", "reasoning", "general"},
    "coding": {"coding", "general"},
    "review": {"review", "coding", "reasoning", "general"},
    "documentation": {"documentation", "general"},
}
COST_RANK = {
    "local": 0,
    "free": 1,
    "free-limited": 2,
    "subscription": 3,
    "low": 4,
    "paid": 5,
}


@dataclass(frozen=True)
class Model:
    id: str
    capabilities: list[str]
    cost_tier: str
    priority: int = 100
    route_kind: str = "direct"
    member_models: list[str] | None = None
    usage_class: str = "standard"
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None


@dataclass(frozen=True)
class Provider:
    id: str
    kind: str
    base_url: str | None
    credential_env: str | None
    enabled: bool
    models: list[Model]


def gateway_path(brain: ProjectBrain) -> Path:
    return brain.directory / GATEWAY_FILE


def default_gateway() -> dict:
    return {
        "version": 1,
        "policy": {
            "prefer_low_cost": True,
            "allow_paid": False,
            "allow_subscription": False,
            "free_limited_routes": [],
            "max_failover_attempts": 3,
            "max_prompt_estimated_tokens": 12000,
            "max_completion_tokens": 2048,
            "daily_token_budget": 250000,
            "daily_cost_budget_usd": 0.0,
            "note": "Credentials are referenced by environment variable or vault; never save secret values here.",
        },
        "providers": [],
    }


def load_gateway(brain: ProjectBrain) -> dict:
    path = gateway_path(brain)
    if not path.exists():
        save_gateway(brain, default_gateway())
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise GuardianError(f"Invalid model gateway configuration: {error}") from error
    if not isinstance(payload.get("providers"), list):
        raise GuardianError("Invalid model gateway configuration: providers must be a list.")
    return payload


def save_gateway(brain: ProjectBrain, payload: dict) -> None:
    gateway_path(brain).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _provider_from_dict(payload: dict) -> Provider:
    models = [
        Model(
            id=model["id"],
            capabilities=list(model.get("capabilities", ["general"])),
            cost_tier=model.get("cost_tier", "paid"),
            priority=int(model.get("priority", 100)),
            route_kind=model.get("route_kind", "direct"),
            member_models=(
                list(model["member_models"])
                if isinstance(model.get("member_models"), list)
                else None
            ),
            usage_class=model.get("usage_class", "standard"),
            input_cost_per_million=(
                float(model["input_cost_per_million"])
                if isinstance(model.get("input_cost_per_million"), (int, float))
                else None
            ),
            output_cost_per_million=(
                float(model["output_cost_per_million"])
                if isinstance(model.get("output_cost_per_million"), (int, float))
                else None
            ),
        )
        for model in payload.get("models", [])
    ]
    return Provider(
        id=payload["id"],
        kind=payload.get("kind", "openai-compatible"),
        base_url=payload.get("base_url"),
        credential_env=payload.get("credential_env"),
        enabled=bool(payload.get("enabled", True)),
        models=models,
    )


def list_providers(brain: ProjectBrain) -> list[Provider]:
    return [_provider_from_dict(item) for item in load_gateway(brain)["providers"]]


def add_provider(
    brain: ProjectBrain,
    *,
    provider_id: str,
    kind: str,
    model_id: str,
    capabilities: list[str],
    cost_tier: str,
    priority: int,
    base_url: str | None,
    credential_env: str | None,
    route_kind: str = "direct",
    member_models: list[str] | None = None,
    usage_class: str = "standard",
    input_cost_per_million: float | None = None,
    output_cost_per_million: float | None = None,
) -> Provider:
    if not provider_id or not model_id:
        raise GuardianError("Provider id and model id are required.")
    require_model_allowed(model_id)
    if cost_tier not in COST_RANK:
        raise GuardianError(f"Unknown cost tier {cost_tier!r}; use: {', '.join(COST_RANK)}")
    payload = load_gateway(brain)
    providers = payload["providers"]
    existing = next((item for item in providers if item["id"] == provider_id), None)
    model = {
        "id": model_id,
        "capabilities": capabilities or ["general"],
        "cost_tier": cost_tier,
        "priority": priority,
        "route_kind": route_kind,
        "member_models": member_models,
        "usage_class": usage_class,
        "input_cost_per_million": input_cost_per_million,
        "output_cost_per_million": output_cost_per_million,
    }
    if existing:
        existing["kind"] = kind
        existing["base_url"] = base_url
        existing["credential_env"] = credential_env
        existing["enabled"] = True
        existing_models = [item for item in existing.get("models", []) if item.get("id") != model_id]
        existing["models"] = [*existing_models, model]
    else:
        providers.append(
            {
                "id": provider_id,
                "kind": kind,
                "base_url": base_url,
                "credential_env": credential_env,
                "enabled": True,
                "models": [model],
            }
        )
    save_gateway(brain, payload)
    return next(provider for provider in list_providers(brain) if provider.id == provider_id)


def install_development_provider_seeds(brain: ProjectBrain) -> list[dict]:
    """Install clearly-labelled development seeds; this does not verify live availability."""
    free_models = [
        {
            "provider_id": "openrouter-free-llama",
            "kind": "openai-compatible",
            "model_id": "meta-llama/llama-3.3-70b-instruct:free",
            "capabilities": ["coding", "research", "general"],
            "cost_tier": "free",
            "priority": 10,
            "base_url": "https://openrouter.ai/api/v1",
            "credential_env": "OPENROUTER_API_KEY",
        },
        {
            "provider_id": "openrouter-free-gemini",
            "kind": "openai-compatible",
            "model_id": "google/gemini-2.0-flash-exp:free",
            "capabilities": ["coding", "planning", "reasoning", "general"],
            "cost_tier": "free",
            "priority": 10,
            "base_url": "https://openrouter.ai/api/v1",
            "credential_env": "OPENROUTER_API_KEY",
        },
    ]
    
    added = []
    for item in free_models:
        prov = add_provider(
            brain,
            provider_id=item["provider_id"],
            kind=item["kind"],
            model_id=item["model_id"],
            capabilities=item["capabilities"],
            cost_tier=item["cost_tier"],
            priority=item["priority"],
            base_url=item["base_url"],
            credential_env=item["credential_env"],
        )
        added.append({"id": prov.id, "model": item["model_id"]})
        
    append_journey(brain, "Development Provider Seeds Installed", [f"Added {len(added)} unverified development routes."])
    return added


# Compatibility alias for the initial CLI.  It deliberately no longer claims
# that hard-coded model names are live provider discovery.
discover_free_providers = install_development_provider_seeds


def setup_ollama_provider(brain: ProjectBrain, model_name: str = "qwen3-coder:30b") -> dict:
    """Setup and register local Ollama provider endpoint."""
    prov = add_provider(
        brain,
        provider_id="local-ollama",
        kind="local",
        model_id=model_name,
        capabilities=["coding", "review", "research", "planning", "general"],
        cost_tier="local",
        priority=0,
        base_url="http://localhost:11434/v1",
        credential_env=None,
    )
    append_journey(brain, "Local Ollama Provider Configured", [f"Model: {model_name} at http://localhost:11434/v1"])
    return {"provider_id": prov.id, "model": model_name, "base_url": prov.base_url}



def discover_ollama_models(
    brain: ProjectBrain,
    base_url: str = "http://localhost:11434",
) -> list[dict]:
    """Discover installed Ollama models locally and register capability hints."""
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/tags",
        headers={"User-Agent": "Guardian-Agent/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise GuardianError(f"Local Ollama discovery failed: {error}") from error
    models = payload.get("models")
    if not isinstance(models, list):
        raise GuardianError("Local Ollama discovery returned an invalid model list.")
    discovered = []
    for index, item in enumerate(models):
        model_name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(model_name, str) or not model_name.strip():
            continue
        if not is_model_allowed(model_name):
            continue
        lowered = model_name.lower()
        capabilities = ["general", "research", "planning", "reasoning"]
        priority = 30 + index
        if "qwen3" in lowered:
            capabilities.extend(["coding", "review", "documentation"])
            priority = 0
        elif "coder" in lowered or "code" in lowered:
            capabilities.extend(["coding", "review", "documentation"])
            priority = 5 + index

        elif "qwen" in lowered:
            capabilities.extend(["review", "documentation"])
            priority = 10 + index
        elif any(marker in lowered for marker in ("gemma", "llama", "mistral")):
            capabilities.extend(["review", "documentation"])
            priority = 15 + index
        provider = add_provider(
            brain,
            provider_id="local-ollama",
            kind="local",
            model_id=model_name,
            capabilities=list(dict.fromkeys(capabilities)),
            cost_tier="local",
            priority=priority,
            base_url=f"{base_url.rstrip('/')}/v1",
            credential_env=None,
        )
        discovered.append({
            "provider_id": provider.id,
            "model": model_name,
            "capabilities": list(dict.fromkeys(capabilities)),
            "priority": priority,
            "size": item.get("size"),
            "modified_at": item.get("modified_at"),
        })
    if not discovered:
        raise GuardianError("No allowed local Ollama models were discovered.")
    append_journey(
        brain,
        "Local Ollama Models Discovered",
        [f"Registered: {len(discovered)}", "Models: " + ", ".join(item["model"] for item in discovered)],
    )
    return discovered


def setup_omniroute_provider(brain: ProjectBrain, model_name: str) -> dict:
    """Register the user's local OmniRoute OpenAI-compatible endpoint."""
    if not model_name.strip():
        raise GuardianError("An explicit OmniRoute combo or model ID is required.")
    if model_name.strip().lower().startswith("auto/"):
        raise GuardianError(
            "Opaque auto/* routes cannot prove prohibited-model exclusion; use provider discover-omniroute or an audited explicit model."
        )
    prov = add_provider(
        brain,
        provider_id="local-omniroute",
        kind="openai-compatible",
        model_id=model_name,
        capabilities=["coding", "research", "planning", "review", "documentation", "general"],
        cost_tier="free",
        priority=2,
        base_url="http://localhost:3000/v1",
        credential_env="OMNIROUTE_API_KEY",
    )
    append_journey(
        brain,
        "Local OmniRoute Provider Configured",
        [f"Model/combo: {model_name}", "Endpoint: http://localhost:3000/v1"],
    )
    return {"provider_id": prov.id, "model": model_name, "base_url": prov.base_url}


def discover_omniroute_combos(
    brain: ProjectBrain,
    base_url: str = "http://localhost:3000",
    credential_env: str | None = None,
) -> dict:
    """Inspect live combo membership and register only policy-safe combos."""
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/combos",
        headers={"User-Agent": "Guardian-Agent/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise GuardianError(f"Local OmniRoute combo discovery failed: {error}") from error
    combos = payload.get("combos")
    if not isinstance(combos, list):
        raise GuardianError("Local OmniRoute returned an invalid combo list.")
    gateway = load_gateway(brain)
    free_limited_routes = set(
        gateway.get("policy", {}).get("free_limited_routes", [])
    )
    records = []
    for index, combo in enumerate(combos):
        if not isinstance(combo, dict) or not isinstance(combo.get("name"), str):
            continue
        name = combo["name"].strip()
        members = [
            item.get("model")
            for item in combo.get("models", [])
            if isinstance(item, dict) and isinstance(item.get("model"), str)
        ]
        blocked_members = [model for model in members if not is_model_allowed(model)]
        allowed = is_model_allowed(name) and not blocked_members
        lowered = name.lower()
        capabilities = ["general", "research", "planning", "reasoning", "review", "documentation"]
        subscription_route = bool(members) and all(
            model.lower().startswith((
                "qwen-web/",
                "cgpt-web/",
                "ds-web/",
                "agy/",
                "antigravity/",
                "kr/",
            ))
            for model in members
        )
        nvidia_free_route = bool(members) and all(
            model.lower().startswith("nvidia/") for model in members
        )
        gpt_final_review = subscription_route and all(
            model.lower().startswith("cgpt-web/gpt-5.5") for model in members
        )
        strong_specialist = (
            subscription_route or nvidia_free_route
        ) and not gpt_final_review
        if (
            "code" in lowered
            or "coding" in lowered
            or any("coder" in model.lower() for model in members)
            or strong_specialist
            or gpt_final_review
        ):
            capabilities.append("coding")
        explicitly_free = bool(members) and all(
            ":free" in model.lower()
            or model.lower().endswith("/free")
            or model.lower().startswith(("pol/", "pollinations/", "ddgw/", "duckduckgo-web/"))
            for model in members
        )
        user_confirmed_free_limited = (
            f"local-omniroute:{name}" in free_limited_routes
        )
        cost_tier = (
            "free-limited"
            if user_confirmed_free_limited
            else
            "free"
            if explicitly_free or nvidia_free_route
            else "subscription"
            if subscription_route
            else "paid"
        )
        usage_class = (
            "final-review"
            if gpt_final_review
            else "specialist"
            if strong_specialist
            else "standard"
        )
        priority = (
            40
            if gpt_final_review
            else 20
            if strong_specialist
            else 20 + index
        )
        registered = False
        if allowed:
            add_provider(
                brain,
                provider_id="local-omniroute",
                kind="openai-compatible",
                model_id=name,
                capabilities=list(dict.fromkeys(capabilities)),
                cost_tier=cost_tier,
                priority=priority,
                base_url=f"{base_url.rstrip('/')}/v1",
                credential_env=credential_env,
                route_kind="omniroute-combo",
                member_models=members,
                usage_class=usage_class,
            )
            registered = True
        records.append({
            "name": name,
            "members": members,
            "strategy": combo.get("strategy"),
            "allowed": allowed,
            "blocked_members": blocked_members,
            "cost_tier": cost_tier,
            "user_confirmed_free_limited": user_confirmed_free_limited,
            "usage_class": usage_class,
            "priority": priority,
            "registered": registered,
        })
    append_journey(
        brain,
        "Local OmniRoute Combos Audited",
        [
            f"Inspected: {len(records)}",
            f"Registered policy-safe: {sum(record['registered'] for record in records)}",
            f"Blocked by model policy: {sum(not record['allowed'] for record in records)}",
        ],
    )
    return {
        "endpoint": f"{base_url.rstrip('/')}/v1",
        "count": len(records),
        "registered_count": sum(record["registered"] for record in records),
        "blocked_count": sum(not record["allowed"] for record in records),
        "combos": records,
    }


def probe_provider_capacity(
    brain: ProjectBrain,
    provider_id: str,
    model_id: str,
) -> dict:
    """Probe an OpenAI-compatible model catalog without spending completion tokens."""
    require_model_allowed(model_id)
    provider = next(
        (item for item in list_providers(brain) if item.id == provider_id),
        None,
    )
    if provider is None or not provider.enabled:
        raise GuardianError(f"Unknown or disabled provider: {provider_id}")
    if not any(model.id == model_id for model in provider.models):
        raise GuardianError(f"Provider {provider_id!r} has no configured model {model_id!r}.")
    if not provider.base_url:
        raise GuardianError(f"Provider {provider_id!r} has no base URL to probe.")
    require_capacity_available(brain, provider_id, model_id)
    headers = {"Accept": "application/json", "User-Agent": "Guardian-Agent/0.1"}
    if provider.credential_env:
        secret = get_secret(brain, provider.credential_env)
        if not secret:
            raise GuardianError(
                f"Provider {provider_id!r} requires credential "
                f"{provider.credential_env!r}, but it is not available."
            )
        headers["Authorization"] = f"Bearer {secret}"
    request = urllib.request.Request(
        f"{provider.base_url.rstrip('/')}/models",
        headers=headers,
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise GuardianError("Provider model catalog exceeds 2 MB.")
            payload = json.loads(raw.decode("utf-8"))
            advertised = [
                item.get("id")
                for item in payload.get("data", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            ]
            capacity = record_provider_capacity(
                brain,
                provider_id,
                model_id,
                getattr(response, "headers", {}),
                latency_ms=int((time.monotonic() - started) * 1000),
                status="probe_success",
            )
    except Exception as error:
        try:
            record_provider_capacity(
                brain,
                provider_id,
                model_id,
                getattr(error, "headers", {}),
                latency_ms=int((time.monotonic() - started) * 1000),
                status=(
                    "rate_limited"
                    if isinstance(error, urllib.error.HTTPError) and error.code == 429
                    else "probe_error"
                ),
            )
        except GuardianError:
            pass
        safe_error = redact_secrets(brain, str(error))
        raise GuardianError(f"Provider {provider_id!r} capacity probe failed: {safe_error}") from error
    return {
        "provider": provider_id,
        "model": model_id,
        "endpoint": f"{provider.base_url.rstrip('/')}/models",
        "model_advertised": model_id in advertised,
        "advertised_model_count": len(advertised),
        "completion_tokens_spent": 0,
        "capacity": capacity,
    }


def choose_model(brain: ProjectBrain, task: str) -> dict:
    routes = list_routes_for_task(brain, task)
    if not routes:
        raise GuardianError(
            f"No enabled, policy-approved model is configured for {task}. Add a local/free provider or allow paid routing."
        )
    return routes[0]


def configure_provider_access(
    brain: ProjectBrain,
    *,
    allow_subscription: bool | None = None,
    allow_paid: bool | None = None,
) -> dict:
    """Explicitly allow or deny prepaid-subscription and metered paid routes."""
    if allow_subscription is None and allow_paid is None:
        raise GuardianError("Provider access configuration requires at least one change.")
    payload = load_gateway(brain)
    policy = payload.setdefault("policy", {})
    if allow_subscription is not None:
        policy["allow_subscription"] = bool(allow_subscription)
    if allow_paid is not None:
        policy["allow_paid"] = bool(allow_paid)
    save_gateway(brain, payload)
    append_journey(
        brain,
        "Provider Access Policy Configured",
        [
            f"Prepaid subscription routes: {bool(policy.get('allow_subscription', False))}",
            f"Metered paid routes: {bool(policy.get('allow_paid', False))}",
        ],
    )
    return {
        "allow_subscription": bool(policy.get("allow_subscription", False)),
        "allow_paid": bool(policy.get("allow_paid", False)),
    }


def mark_omniroute_combo_free_limited(
    brain: ProjectBrain,
    model_id: str,
) -> dict:
    """Persist the user's assertion that one audited combo uses free limited quota."""
    require_model_allowed(model_id)
    payload = load_gateway(brain)
    provider = next(
        (item for item in payload["providers"] if item.get("id") == "local-omniroute"),
        None,
    )
    if provider is None:
        raise GuardianError("Run provider discover-omniroute before marking combo funding.")
    model = next(
        (item for item in provider.get("models", []) if item.get("id") == model_id),
        None,
    )
    if model is None or model.get("route_kind") != "omniroute-combo":
        raise GuardianError(f"Unknown audited OmniRoute combo: {model_id}")
    members = model.get("member_models")
    if not isinstance(members, list) or not members:
        raise GuardianError("Cannot mark an OmniRoute combo without audited members.")
    blocked = [member for member in members if not is_model_allowed(member)]
    if blocked:
        raise GuardianError(
            "Cannot mark combo because it contains prohibited model(s): "
            + ", ".join(blocked)
        )
    key = f"local-omniroute:{model_id}"
    policy = payload.setdefault("policy", {})
    routes = policy.setdefault("free_limited_routes", [])
    if key not in routes:
        routes.append(key)
    model["cost_tier"] = "free-limited"
    save_gateway(brain, payload)
    append_journey(
        brain,
        "OmniRoute Combo Marked Free-Limited",
        [
            f"Combo: {model_id}",
            f"Audited members: {len(members)}",
            "Funding assertion: user-confirmed free quota with finite limits.",
            "Membership will still be re-audited immediately before every completion.",
        ],
    )
    return {
        "provider": "local-omniroute",
        "model": model_id,
        "cost_tier": "free-limited",
        "member_count": len(members),
    }


def resolve_configured_route(
    brain: ProjectBrain,
    task: str,
    provider_id: str,
    model_id: str,
) -> dict:
    """Resolve an exact route only if current capability and cost policy allow it."""
    require_model_allowed(model_id)
    route = next(
        (
            candidate
            for candidate in list_routes_for_task(brain, task)
            if candidate["provider"] == provider_id and candidate["model"] == model_id
        ),
        None,
    )
    if not route:
        raise GuardianError(
            f"Configured route {provider_id}:{model_id} is unavailable, incapable, unhealthy by configuration, or disallowed by cost policy."
        )
    return route


def list_routes_for_task(brain: ProjectBrain, task: str) -> list[dict]:
    """Return all policy-approved routes, ordered by cost and configured priority."""
    if task not in TASK_CAPABILITIES:
        raise GuardianError(f"Unknown task type {task!r}; use: {', '.join(sorted(TASK_CAPABILITIES))}")
    payload = load_gateway(brain)
    allowed = TASK_CAPABILITIES[task]
    candidates: list[tuple[tuple[int, int, str, str], Provider, Model]] = []
    for provider in list_providers(brain):
        if not provider.enabled:
            continue
        for model in provider.models:
            if not is_model_allowed(model.id):
                continue
            if not allowed.intersection(model.capabilities):
                continue
            if model.cost_tier == "paid" and not payload["policy"].get("allow_paid", False):
                continue
            if (
                model.cost_tier == "subscription"
                and not payload["policy"].get("allow_subscription", False)
            ):
                continue
            affinity = 0
            lowered_model = model.id.lower()
            if "coder" in lowered_model or "code" in lowered_model:
                if task in {"coding", "review"}:
                    affinity = -10
                elif task in {"research", "planning", "documentation", "routing"}:
                    affinity = 10
            elif task in {"research", "planning", "documentation", "routing"} and any(
                marker in lowered_model for marker in ("qwen", "gemma", "llama", "mistral")
            ):
                affinity = -3
            effective_priority = model.priority + affinity
            efficiency_penalty = provider_efficiency_penalty(
                brain,
                provider.id,
                model.id,
            )
            quality_adjustment = provider_quality_adjustment(
                brain,
                provider.id,
                model.id,
            )
            log_health_penalty = (
                omniroute_log_penalty(brain, model.id)
                if provider.id == "local-omniroute"
                else 0
            )
            effective_priority += (
                efficiency_penalty + quality_adjustment + log_health_penalty
            )
            candidates.append(
                (
                    (COST_RANK[model.cost_tier], effective_priority, provider.id, model.id),
                    provider,
                    model,
                    effective_priority,
                )
            )
    return [
        {
            "task": task,
            "provider": provider.id,
            "provider_kind": provider.kind,
            "base_url": provider.base_url,
            "credential_env": provider.credential_env,
            "model": model.id,
            "capabilities": model.capabilities,
            "cost_tier": model.cost_tier,
            "route_priority": effective_priority,
            "efficiency_penalty": provider_efficiency_penalty(
                brain,
                provider.id,
                model.id,
            ),
            "quality_adjustment": provider_quality_adjustment(
                brain,
                provider.id,
                model.id,
            ),
            "log_health_penalty": (
                omniroute_log_penalty(brain, model.id)
                if provider.id == "local-omniroute"
                else 0
            ),
            "prompt_reservation_multiplier": provider_prompt_reservation_multiplier(
                brain,
                provider.id,
                model.id,
            ),
            "route_kind": model.route_kind,
            "member_models": model.member_models,
            "usage_class": model.usage_class,
            "input_cost_per_million": model.input_cost_per_million,
            "output_cost_per_million": model.output_cost_per_million,
        }
        for _, provider, model, effective_priority in sorted(candidates, key=lambda item: item[0])
    ]


def record_telemetry(
    brain: ProjectBrain,
    task: str,
    provider: str,
    model: str,
    tokens: int,
    cost_usd: float = 0.0,
) -> None:
    costs_doc = brain.document("COSTS.md")
    content = costs_doc.read_text(encoding="utf-8")
    entry = f"\n- **{now_utc()}** | Task: `{task}` | Provider: `{provider}` | Model: `{model}` | Tokens: {tokens} | Cost: ${cost_usd:.4f}"
    costs_doc.write_text(content.strip() + entry + "\n", encoding="utf-8")


def configure_budget(
    brain: ProjectBrain,
    *,
    daily_tokens: int | None = None,
    daily_cost_usd: float | None = None,
    max_completion_tokens: int | None = None,
) -> dict:
    payload = load_gateway(brain)
    policy = payload.setdefault("policy", {})
    if daily_tokens is not None:
        if daily_tokens < 1:
            raise GuardianError("Daily token budget must be positive.")
        policy["daily_token_budget"] = daily_tokens
    if daily_cost_usd is not None:
        if daily_cost_usd < 0:
            raise GuardianError("Daily cost budget cannot be negative.")
        policy["daily_cost_budget_usd"] = daily_cost_usd
    if max_completion_tokens is not None:
        if max_completion_tokens < 1:
            raise GuardianError("Maximum completion tokens must be positive.")
        policy["max_completion_tokens"] = max_completion_tokens
    save_gateway(brain, payload)
    append_journey(
        brain,
        "Model Budget Configured",
        [
            f"Daily tokens: {policy.get('daily_token_budget', 250000)}",
            f"Daily cost: ${float(policy.get('daily_cost_budget_usd', 0.0)):.4f}",
            f"Maximum completion tokens: {policy.get('max_completion_tokens', 2048)}",
        ],
    )
    return budget_status(brain, policy)


def get_budget_status(brain: ProjectBrain) -> dict:
    return budget_status(brain, load_gateway(brain).get("policy", {}))


def _verify_live_omniroute_combo(route: dict) -> None:
    """Fail closed if an audited OmniRoute combo's current members become unsafe."""
    if route.get("route_kind") != "omniroute-combo":
        return
    base_url = route.get("base_url")
    model_id = route.get("model")
    if not isinstance(base_url, str) or not isinstance(model_id, str):
        raise GuardianError("Audited OmniRoute combo route is missing endpoint metadata.")
    api_root = base_url.rstrip("/")
    if api_root.endswith("/v1"):
        api_root = api_root[:-3]
    request = urllib.request.Request(
        f"{api_root}/api/combos",
        headers={"User-Agent": "Guardian-Agent/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise GuardianError(
            f"Cannot re-audit OmniRoute combo {model_id!r}; execution stopped: {error}"
        ) from error
    combos = payload.get("combos")
    if not isinstance(combos, list):
        raise GuardianError("OmniRoute combo re-audit returned an invalid combo list.")
    combo = next(
        (
            item for item in combos
            if isinstance(item, dict) and item.get("name") == model_id
        ),
        None,
    )
    if combo is None:
        raise GuardianError(
            f"OmniRoute combo {model_id!r} no longer exists; execution stopped."
        )
    members = [
        item.get("model")
        for item in combo.get("models", [])
        if isinstance(item, dict) and isinstance(item.get("model"), str)
    ]
    blocked = [member for member in members if not is_model_allowed(member)]
    if not is_model_allowed(model_id) or blocked:
        raise GuardianError(
            f"OmniRoute combo {model_id!r} now contains prohibited model(s): "
            + ", ".join(blocked or [model_id])
        )
    if not members:
        raise GuardianError(
            f"OmniRoute combo {model_id!r} has no auditable model members; execution stopped."
        )


def complete_task_with_model(
    brain: ProjectBrain,
    task: str,
    prompt: str,
    system_prompt: str | None = None,
    route: dict | None = None,
    *,
    stream: bool = False,
    on_chunk: Callable[[str], None] | None = None,
) -> dict:
    route = route or choose_model(brain, task)
    base_url = route.get("base_url")
    model_id = route.get("model")
    provider_id = route.get("provider", "unknown")
    
    if not isinstance(model_id, str):
        raise GuardianError(f"Provider {provider_id!r} route has no valid model ID.")
    require_model_allowed(model_id)

    if not base_url:
        raise GuardianError(f"Provider {provider_id!r} has no valid base_url configured for completion.")

    worker_system_prompt = system_prompt or "You are Guardian Agent worker."
    _verify_live_omniroute_combo(route)
    headers = {"Content-Type": "application/json", "User-Agent": "Guardian-Agent/0.1"}
    credential_ref = route.get("credential_env")
    if credential_ref:
        secret = get_secret(brain, credential_ref)
        if not secret:
            raise GuardianError(
                f"Provider {provider_id!r} requires credential {credential_ref!r}, but it is not available."
            )
        headers["Authorization"] = f"Bearer {secret}"

    require_capacity_available(brain, provider_id, model_id)
    gateway_policy = load_gateway(brain).get("policy", {})
    reservation = reserve_budget(
        brain,
        gateway_policy,
        route,
        prompt,
        worker_system_prompt,
    )
    started = time.monotonic()
    try:
        url = f"{base_url.rstrip('/')}/chat/completions"
        payload_data = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": worker_system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": int(gateway_policy.get("max_completion_tokens", 2048)),
            "stream": stream,
        }
        if stream:
            payload_data["stream_options"] = {"include_usage": True}
        req = urllib.request.Request(
            url,
            data=json.dumps(payload_data).encode("utf-8"),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            if stream:
                text, usage = _read_sse_completion(resp, on_chunk)
            else:
                data = json.loads(resp.read().decode("utf-8"))
                text = data["choices"][0]["message"]["content"]
                usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            prompt_tokens = int(
                usage.get("prompt_tokens")
                or estimate_tokens(prompt) + estimate_tokens(worker_system_prompt)
            )
            completion_tokens = int(
                usage.get("completion_tokens") or estimate_tokens(text)
            )
            total_tokens = int(
                usage.get("total_tokens") or prompt_tokens + completion_tokens
            )
            response_cost = None
            header_cost = getattr(resp, "headers", {}).get("x-omniroute-response-cost")
            if isinstance(header_cost, str):
                try:
                    response_cost = float(header_cost)
                except ValueError:
                    response_cost = None
            if response_cost is None:
                response_cost = estimate_route_cost(route, prompt_tokens, completion_tokens)
            billed_cost = (
                0.0
                if route.get("cost_tier") in {
                    "local", "free", "free-limited", "subscription"
                }
                else response_cost
            )
            charged = settle_budget(
                brain,
                reservation,
                actual_tokens=total_tokens,
                actual_cost_usd=billed_cost,
                charge_reservation=False,
            )
            latency_ms = int((time.monotonic() - started) * 1000)
            record_provider_capacity(
                brain,
                provider_id,
                model_id,
                getattr(resp, "headers", {}),
                latency_ms=latency_ms,
                status="success",
                usage={
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": charged["tokens"],
                    "cost_usd": charged["cost_usd"],
                    "reported_equivalent_cost_usd": response_cost,
                },
                estimated_prompt_tokens=max(
                    1,
                    (len(prompt) + len(worker_system_prompt) + 7) // 4,
                ),
            )
            record_provider_success(brain, provider_id)
            record_telemetry(
                brain,
                task,
                provider_id,
                model_id,
                tokens=charged["tokens"],
                cost_usd=charged["cost_usd"],
            )
            return {
                "task": task,
                "provider": provider_id,
                "model": model_id,
                "response": text,
                "streamed": stream,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": charged["tokens"],
                    "cost_usd": charged["cost_usd"],
                    "reported_equivalent_cost_usd": response_cost,
                    "source": "provider" if usage else "conservative-estimate",
                },
            }
    except Exception as error:
        try:
            settle_budget(
                brain,
                reservation,
                actual_tokens=None,
                actual_cost_usd=None,
                charge_reservation=True,
            )
        except GuardianError:
            pass
        error_headers = getattr(error, "headers", {})
        error_status = (
            "rate_limited"
            if isinstance(error, urllib.error.HTTPError) and error.code == 429
            else "error"
        )
        try:
            record_provider_capacity(
                brain,
                provider_id,
                model_id,
                error_headers,
                latency_ms=int((time.monotonic() - started) * 1000),
                status=error_status,
            )
        except GuardianError:
            pass
        safe_error = redact_secrets(brain, str(error))
        record_provider_error(brain, provider_id, safe_error)
        raise GuardianError(f"Provider {provider_id!r} completion failed: {safe_error}") from error


def _read_sse_completion(
    response,
    on_chunk: Callable[[str], None] | None,
) -> tuple[str, dict]:
    parts: list[str] = []
    usage: dict = {}
    for raw_line in response:
        if not isinstance(raw_line, (bytes, bytearray)):
            continue
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line or line.startswith(":") or not line.startswith("data:"):
            continue
        data_text = line[5:].strip()
        if data_text == "[DONE]":
            break
        try:
            event = json.loads(data_text)
        except json.JSONDecodeError as error:
            raise GuardianError("Provider returned malformed SSE JSON.") from error
        if isinstance(event.get("usage"), dict):
            usage = event["usage"]
        choices = event.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        choice = choices[0] if isinstance(choices[0], dict) else {}
        delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
        content = delta.get("content")
        if content is None and isinstance(choice.get("message"), dict):
            content = choice["message"].get("content")
        if isinstance(content, str) and content:
            parts.append(content)
            if on_chunk:
                on_chunk(content)
    if not parts:
        raise GuardianError("Provider stream completed without text content.")
    return "".join(parts), usage


def _diversified_failover_routes(routes: list[dict]) -> list[dict]:
    """Prefer backend diversity, then several independently quota-limited combos."""
    if not routes:
        return []
    ordered = [routes[0]]
    used = {(routes[0]["provider"], routes[0]["model"])}
    first_provider = routes[0]["provider"]
    for route in routes[1:]:
        key = (route["provider"], route["model"])
        if route["provider"] != first_provider and key not in used:
            ordered.append(route)
            used.add(key)
    for route in routes[1:]:
        key = (route["provider"], route["model"])
        if key not in used:
            ordered.append(route)
            used.add(key)
    return ordered


def complete_task_with_failover(
    brain: ProjectBrain,
    task: str,
    prompt: str,
    system_prompt: str | None = None,
    max_attempts: int | None = None,
) -> dict:
    """Try ordered low-cost healthy routes within explicit call/context limits."""
    gateway = load_gateway(brain)
    policy = gateway.get("policy", {})
    configured_attempts = int(policy.get("max_failover_attempts", 3))
    attempts_limit = configured_attempts if max_attempts is None else max_attempts
    if attempts_limit < 1 or attempts_limit > 5:
        raise GuardianError("Failover attempts must be between 1 and 5.")
    estimated_prompt_tokens = (len(prompt) + 3) // 4
    max_prompt_tokens = int(policy.get("max_prompt_estimated_tokens", 12000))
    if estimated_prompt_tokens > max_prompt_tokens:
        raise GuardianError(
            f"Prompt estimate {estimated_prompt_tokens} exceeds configured limit {max_prompt_tokens} tokens."
        )
    routes = list_routes_for_task(brain, task)
    healthy_routes = [
        route
        for route in routes
        if check_provider_health(brain, route["provider"])["healthy"]
    ]
    healthy_routes = _diversified_failover_routes(healthy_routes)
    if not healthy_routes:
        raise GuardianError(f"No healthy policy-approved routes are available for {task}.")
    failures = []
    for route in healthy_routes[:attempts_limit]:
        try:
            result = complete_task_with_model(
                brain,
                task,
                prompt,
                system_prompt=system_prompt,
                route=route,
            )
            result["routing"] = {
                "mode": "bounded-failover",
                "attempts": len(failures) + 1,
                "failed_routes": failures,
                "estimated_prompt_tokens": estimated_prompt_tokens,
                "max_attempts": attempts_limit,
            }
            return result
        except GuardianError as error:
            failures.append({
                "provider": route["provider"],
                "model": route["model"],
                "error": str(error),
            })
    raise GuardianError(
        f"All {len(failures)} attempted routes failed for {task}: "
        + "; ".join(f"{item['provider']}:{item['model']}" for item in failures)
    )


def provider_summary(brain: ProjectBrain) -> list[dict]:
    result = []
    for provider in list_providers(brain):
        result.append(
            {
                "id": provider.id,
                "kind": provider.kind,
                "enabled": provider.enabled,
                "base_url": provider.base_url,
                "credential_env": provider.credential_env,
                "models": [asdict(model) for model in provider.models],
            }
        )
    return result
