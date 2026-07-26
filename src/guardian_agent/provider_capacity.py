"""Secret-safe provider quota, rate-limit, latency, and retry telemetry."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from guardian_agent.core import GuardianError, ProjectBrain, now_utc


CAPACITY_FILE = "provider-capacity.json"
ALLOWED_HEADERS = {
    "retry-after",
    "x-ratelimit-limit-requests",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-reset-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-tokens",
    "x-omniroute-response-cost",
    "x-omniroute-provider",
    "x-omniroute-model",
}


def _path(brain: ProjectBrain) -> Path:
    return brain.directory / "audit" / CAPACITY_FILE


def _load(brain: ProjectBrain) -> dict:
    path = _path(brain)
    if not path.exists():
        return {"version": 1, "routes": {}, "events": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GuardianError(f"Invalid provider capacity ledger: {error}") from error
    if not isinstance(payload.get("routes"), dict):
        raise GuardianError("Invalid provider capacity ledger: routes must be an object.")
    payload.setdefault("events", [])
    return payload


def _save(brain: ProjectBrain, payload: dict) -> None:
    path = _path(brain)
    path.parent.mkdir(exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _safe_headers(headers) -> dict[str, str]:
    try:
        items = headers.items()
    except (AttributeError, TypeError):
        return {}
    result = {}
    for key, value in items:
        normalized = str(key).lower()
        if normalized in ALLOWED_HEADERS:
            result[normalized] = str(value)[:200]
    return result


def _duration_seconds(value: str) -> float | None:
    text = value.strip().lower()
    try:
        numeric = float(text)
        if numeric > 1_000_000_000:
            return max(0.0, numeric - time.time())
        return max(0.0, numeric)
    except ValueError:
        pass
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(ms|s|m|h)", text)
    if match:
        amount = float(match.group(1))
        multiplier = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[match.group(2)]
        return amount * multiplier
    try:
        instant = datetime.fromisoformat(text.replace("z", "+00:00"))
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        return max(0.0, instant.timestamp() - time.time())
    except ValueError:
        return None


def record_provider_capacity(
    brain: ProjectBrain,
    provider: str,
    model: str,
    headers,
    *,
    latency_ms: int,
    status: str,
    usage: dict | None = None,
    estimated_prompt_tokens: int | None = None,
) -> dict:
    filtered = _safe_headers(headers)
    now_epoch = time.time()
    delays = [
        delay
        for name in (
            "retry-after",
            "x-ratelimit-reset-requests",
            "x-ratelimit-reset-tokens",
        )
        if name in filtered
        for delay in [_duration_seconds(filtered[name])]
        if delay is not None
    ]
    remaining_requests = filtered.get("x-ratelimit-remaining-requests")
    remaining_tokens = filtered.get("x-ratelimit-remaining-tokens")
    exhausted = (
        remaining_requests is not None
        and _as_float(remaining_requests) == 0
    ) or (
        remaining_tokens is not None
        and _as_float(remaining_tokens) == 0
    )
    if exhausted and not delays:
        delays.append(60.0)
    blocked_until = now_epoch + max(delays) if delays and (
        exhausted or status == "rate_limited" or "retry-after" in filtered
    ) else None
    key = f"{provider}:{model}"
    payload = _load(brain)
    previous = payload["routes"].get(key, {})
    effective_usage = usage if isinstance(usage, dict) else previous.get("usage")
    effective_estimate = (
        estimated_prompt_tokens
        if isinstance(estimated_prompt_tokens, int)
        else previous.get("estimated_prompt_tokens")
    )
    reported_prompt_tokens = (
        int(effective_usage["prompt_tokens"])
        if isinstance(effective_usage, dict)
        and isinstance(effective_usage.get("prompt_tokens"), (int, float))
        else None
    )
    inflation_ratio = (
        round(reported_prompt_tokens / effective_estimate, 2)
        if reported_prompt_tokens is not None
        and isinstance(effective_estimate, int)
        and effective_estimate > 0
        else None
    )
    record = {
        "provider": provider,
        "model": model,
        "observed_at": now_utc(),
        "observed_at_epoch": now_epoch,
        "status": status,
        "latency_ms": max(0, int(latency_ms)),
        "headers": filtered,
        "blocked_until_epoch": blocked_until,
        "usage": effective_usage,
        "estimated_prompt_tokens": effective_estimate,
        "prompt_inflation_ratio": inflation_ratio,
        "efficiency_warning": bool(
            inflation_ratio is not None and inflation_ratio > 3
        ),
    }
    payload["routes"][key] = record
    payload["events"] = [*payload.get("events", []), {
        "route": key,
        "observed_at_epoch": now_epoch,
        "status": status,
        "latency_ms": record["latency_ms"],
        "blocked_until_epoch": blocked_until,
    }][-100:]
    _save(brain, payload)
    return record


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def require_capacity_available(
    brain: ProjectBrain,
    provider: str,
    model: str,
) -> None:
    record = _load(brain)["routes"].get(f"{provider}:{model}")
    if not record:
        return
    blocked_until = record.get("blocked_until_epoch")
    if isinstance(blocked_until, (int, float)) and blocked_until > time.time():
        wait_seconds = max(1, int(blocked_until - time.time() + 0.999))
        raise GuardianError(
            f"Provider route {provider}:{model} is in an observed retry/quota "
            f"window for about {wait_seconds}s; no request was sent."
        )


def provider_capacity_status(
    brain: ProjectBrain,
    provider: str | None = None,
) -> dict:
    payload = _load(brain)
    routes = list(payload["routes"].values())
    if provider:
        routes = [record for record in routes if record.get("provider") == provider]
    now_epoch = time.time()
    return {
        "routes": [
            {
                **record,
                "currently_blocked": bool(
                    isinstance(record.get("blocked_until_epoch"), (int, float))
                    and record["blocked_until_epoch"] > now_epoch
                ),
            }
            for record in sorted(
                routes,
                key=lambda item: (item.get("provider", ""), item.get("model", "")),
            )
        ],
        "event_count": len(payload.get("events", [])),
        "retained_event_limit": 100,
        "header_allowlist": sorted(ALLOWED_HEADERS),
    }


def provider_efficiency_penalty(
    brain: ProjectBrain,
    provider: str,
    model: str,
) -> int:
    """Return a bounded priority penalty learned from observed prompt overhead."""
    record = _load(brain)["routes"].get(f"{provider}:{model}", {})
    ratio = record.get("prompt_inflation_ratio")
    if not isinstance(ratio, (int, float)) or ratio <= 3:
        return 0
    return min(100, max(10, int(ratio)))


def provider_prompt_reservation_multiplier(
    brain: ProjectBrain,
    provider: str,
    model: str,
) -> float:
    """Reserve against learned hidden prompt overhead; fail conservatively for OmniRoute."""
    record = _load(brain)["routes"].get(f"{provider}:{model}", {})
    ratio = record.get("prompt_inflation_ratio")
    if isinstance(ratio, (int, float)) and ratio > 1:
        return min(256.0, float(ratio))
    if provider == "local-omniroute":
        return 128.0
    if provider == "local-ollama":
        return 1.0
    return 16.0


def provider_quality_adjustment(
    brain: ProjectBrain,
    provider: str,
    model: str,
) -> int:
    """Prefer repeatedly measured high-quality routes; penalize weak ones."""
    directory = brain.directory / "audit" / "evaluations"
    scores = []
    scenario_count = 0
    if not directory.is_dir():
        return 0
    for path in directory.glob("guardian-eval-v1-*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        live = record.get("live_quality", {})
        scenarios = live.get("scenarios")
        if not live.get("executed") or not isinstance(scenarios, list) or not scenarios:
            continue
        if scenarios[0].get("provider") != provider or scenarios[0].get("model") != model:
            continue
        scenario_count += len(scenarios)
        score = live.get("quality_score_percent")
        if not isinstance(score, (int, float)):
            possible = sum(len(item.get("required_terms", [])) for item in scenarios)
            earned = sum(
                len(item.get("required_terms", [])) - len(item.get("missing_terms", []))
                for item in scenarios
            )
            score = 100 * earned / possible if possible else 0.0
        scores.append(float(score))
    if scenario_count < 3 or not scores:
        return 0
    average = sum(scores) / len(scores)
    if average >= 90:
        return -5
    if average >= 75:
        return 0
    if average >= 50:
        return 15
    return 30
