"""Redacted local OmniRoute usage-log health audit."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc


LOG_HEALTH_FILE = "omniroute-log-health.json"
MAX_LOG_BYTES = 2_000_000


def _validate_local_base_url(base_url: str) -> str:
    parsed = urlparse(base_url.strip())
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise GuardianError("OmniRoute logs require an explicit loopback HTTP base URL.")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _parse_log_line(line: str) -> dict | None:
    parts = [part.strip() for part in line.split(" | ")]
    if len(parts) != 7:
        return None
    timestamp, model, provider, connection, input_text, output_text, status_text = parts
    try:
        input_tokens = max(0, int(input_text))
        output_tokens = max(0, int(output_text))
        status_code = int(status_text)
    except ValueError:
        return None
    return {
        "timestamp": timestamp[:40],
        "model": model[:200],
        "provider": provider[:100],
        "connection_present": connection != "-",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "status_code": status_code,
        "successful": 200 <= status_code < 300,
    }


def _member_aliases(model: str) -> set[str]:
    aliases = {model.lower()}
    remaining = model
    while "/" in remaining:
        remaining = remaining.split("/", 1)[1]
        aliases.add(remaining.lower())
    return aliases


def _configured_combos(brain: ProjectBrain) -> list[dict]:
    path = brain.directory / "model-gateway.json"
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GuardianError(f"Invalid model gateway while correlating logs: {error}") from error
    provider = next(
        (
            item for item in payload.get("providers", [])
            if item.get("id") == "local-omniroute"
        ),
        None,
    )
    if not isinstance(provider, dict):
        return []
    return [
        model for model in provider.get("models", [])
        if isinstance(model, dict)
        and model.get("route_kind") == "omniroute-combo"
        and isinstance(model.get("id"), str)
    ]


def _artifact_path(brain: ProjectBrain) -> Path:
    return brain.directory / "audit" / LOG_HEALTH_FILE


def audit_omniroute_logs(
    brain: ProjectBrain,
    *,
    base_url: str = "http://localhost:3000",
    limit: int = 100,
) -> dict:
    if limit < 1 or limit > 500:
        raise GuardianError("OmniRoute log audit limit must be between 1 and 500.")
    root = _validate_local_base_url(base_url)
    request = urllib.request.Request(
        f"{root}/api/usage/logs?limit={limit}",
        headers={"Accept": "application/json", "User-Agent": "Guardian-Agent/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read(MAX_LOG_BYTES + 1)
    except (OSError, urllib.error.URLError) as error:
        raise GuardianError(f"Local OmniRoute log audit failed: {error}") from error
    if len(raw) > MAX_LOG_BYTES:
        raise GuardianError(f"OmniRoute log response exceeds {MAX_LOG_BYTES} bytes.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise GuardianError(f"OmniRoute log response was invalid JSON: {error}") from error
    if not isinstance(payload, list):
        raise GuardianError("OmniRoute log response must be a list.")
    events = [
        parsed
        for item in payload
        if isinstance(item, str)
        for parsed in [_parse_log_line(item)]
        if parsed is not None
    ][:limit]
    route_health = []
    for combo in _configured_combos(brain):
        aliases = {combo["id"].lower()}
        for member in combo.get("member_models") or []:
            if isinstance(member, str):
                aliases.update(_member_aliases(member))
        matched = [
            event for event in events
            if event["model"].lower() in aliases
        ][:20]
        failures = sum(not event["successful"] for event in matched)
        successes = len(matched) - failures
        failure_rate = round(failures / len(matched), 3) if matched else None
        penalty = 0
        if matched and not matched[0]["successful"]:
            penalty += 15
        if failure_rate is not None and failure_rate >= 0.5:
            penalty += 15
        route_health.append({
            "model": combo["id"],
            "matched_events": len(matched),
            "successes": successes,
            "failures": failures,
            "failure_rate": failure_rate,
            "last_status_code": matched[0]["status_code"] if matched else None,
            "routing_penalty": min(30, penalty),
        })
    artifact = {
        "schema_version": "guardian-omniroute-log-health-v1",
        "audited_at": now_utc(),
        "source": f"{root}/api/usage/logs",
        "privacy": (
            "Raw log lines and connection identifiers were discarded. "
            "Only redacted model/provider/status/token summaries are retained."
        ),
        "event_count": len(events),
        "success_count": sum(event["successful"] for event in events),
        "failure_count": sum(not event["successful"] for event in events),
        "events": events,
        "routes": route_health,
    }
    path = _artifact_path(brain)
    path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    append_journey(
        brain,
        "OmniRoute Logs Audited",
        [
            f"Redacted events: {len(events)}",
            f"Failures: {artifact['failure_count']}",
            f"Combo routes correlated: {len(route_health)}",
            "Raw lines and connection identifiers were discarded.",
        ],
    )
    return {**artifact, "artifact": str(path)}


def omniroute_log_penalty(brain: ProjectBrain, model_id: str) -> int:
    path = _artifact_path(brain)
    if not path.is_file():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    record = next(
        (
            item for item in payload.get("routes", [])
            if isinstance(item, dict) and item.get("model") == model_id
        ),
        None,
    )
    if not record:
        return 0
    penalty = record.get("routing_penalty", 0)
    return min(30, max(0, int(penalty))) if isinstance(penalty, (int, float)) else 0
