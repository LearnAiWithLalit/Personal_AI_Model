"""Independent, secret-free model-provider registry, router, and completion engine.

The gateway stores provider metadata only. Provider API keys remain in an
environment variable, OS keychain, or encrypted vault.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from dataclasses import asdict, dataclass
from pathlib import Path

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc, markdown_escape
from guardian_agent.health import record_provider_error, record_provider_success


GATEWAY_FILE = "model-gateway.json"
TASK_CAPABILITIES = {
    "routing": {"routing", "general"},
    "research": {"research", "general"},
    "planning": {"planning", "reasoning", "general"},
    "coding": {"coding", "general"},
    "review": {"review", "coding", "reasoning", "general"},
    "documentation": {"documentation", "general"},
}
COST_RANK = {"local": 0, "free": 1, "low": 2, "paid": 3}


@dataclass(frozen=True)
class Model:
    id: str
    capabilities: list[str]
    cost_tier: str
    priority: int = 100


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
) -> Provider:
    if not provider_id or not model_id:
        raise GuardianError("Provider id and model id are required.")
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


def discover_free_providers(brain: ProjectBrain) -> list[dict]:
    """Discover and register legitimate free-tier endpoints (OpenRouter free models, OmniRoute local)."""
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
        {
            "provider_id": "local-omniroute",
            "kind": "openai-compatible",
            "model_id": "omniroute-auto",
            "capabilities": ["coding", "research", "planning", "general"],
            "cost_tier": "free",
            "priority": 5,
            "base_url": "http://localhost:8000/v1",
            "credential_env": "OMNIROUTE_API_KEY",
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
        
    append_journey(brain, "Free API Providers Discovered", [f"Added {len(added)} free-tier model routes."])
    return added


def setup_ollama_provider(brain: ProjectBrain, model_name: str = "qwen2.5-coder") -> dict:
    """Setup and register local Ollama provider endpoint."""
    prov = add_provider(
        brain,
        provider_id="local-ollama",
        kind="local",
        model_id=model_name,
        capabilities=["coding", "research", "planning", "review", "general"],
        cost_tier="local",
        priority=1,
        base_url="http://localhost:11434/v1",
        credential_env=None,
    )
    append_journey(brain, "Local Ollama Provider Configured", [f"Model: {model_name} at http://localhost:11434/v1"])
    return {"provider_id": prov.id, "model": model_name, "base_url": prov.base_url}


def choose_model(brain: ProjectBrain, task: str) -> dict:
    if task not in TASK_CAPABILITIES:
        raise GuardianError(f"Unknown task type {task!r}; use: {', '.join(sorted(TASK_CAPABILITIES))}")
    payload = load_gateway(brain)
    allowed = TASK_CAPABILITIES[task]
    candidates: list[tuple[tuple[int, int, str, str], Provider, Model]] = []
    for provider in list_providers(brain):
        if not provider.enabled:
            continue
        for model in provider.models:
            if not allowed.intersection(model.capabilities):
                continue
            if model.cost_tier == "paid" and not payload["policy"].get("allow_paid", False):
                continue
            candidates.append(
                (
                    (COST_RANK[model.cost_tier], model.priority, provider.id, model.id),
                    provider,
                    model,
                )
            )
    if not candidates:
        raise GuardianError(
            f"No enabled, policy-approved model is configured for {task}. Add a local/free provider or allow paid routing."
        )
    _, provider, model = min(candidates, key=lambda item: item[0])
    return {
        "task": task,
        "provider": provider.id,
        "provider_kind": provider.kind,
        "base_url": provider.base_url,
        "credential_env": provider.credential_env,
        "model": model.id,
        "capabilities": model.capabilities,
        "cost_tier": model.cost_tier,
    }


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


def complete_task_with_model(
    brain: ProjectBrain,
    task: str,
    prompt: str,
    system_prompt: str | None = None,
) -> dict:
    route = choose_model(brain, task)
    base_url = route.get("base_url")
    model_id = route.get("model")
    provider_id = route.get("provider", "unknown")
    
    if base_url:
        try:
            url = f"{base_url.rstrip('/')}/chat/completions"
            headers = {"Content-Type": "application/json"}
            payload_data = {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system_prompt or "You are Guardian Agent worker."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            }
            req = urllib.request.Request(url, data=json.dumps(payload_data).encode("utf-8"), headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data["choices"][0]["message"]["content"]
                record_provider_success(brain, provider_id)
                record_telemetry(brain, task, provider_id, model_id, tokens=len(prompt.split()), cost_usd=0.0)
                return {"task": task, "provider": provider_id, "model": model_id, "response": text}
        except Exception as error:
            record_provider_error(brain, provider_id, str(error))
            raise GuardianError(f"Provider {provider_id!r} completion failed: {error}") from error

    raise GuardianError(f"Provider {provider_id!r} has no valid base_url configured for completion.")


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
