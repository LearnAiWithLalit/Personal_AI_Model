"""Versioned routing and live model-quality evaluations."""

from __future__ import annotations

import json
import hashlib
import uuid
from pathlib import Path

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc
from guardian_agent.gateway import complete_task_with_model, resolve_configured_route
from guardian_agent.model_policy import is_model_allowed
from guardian_agent.profiles import select_profiles, validate_catalog


EVALUATION_VERSION = "guardian-eval-v1"
ROUTING_SCENARIOS = (
    ("write unit tests", {"unit-test-writer"}),
    ("research competitors and verify citations", {"citation-manager", "competitive-intelligence-agent"}),
    ("design accessible user interface", {"accessibility-designer"}),
    ("deploy kubernetes with terraform", {"kubernetes-engineer", "terraform-iac-engineer"}),
    ("dependency planner for a complex implementation", {"dependency-planner"}),
)
LIVE_SCENARIOS = (
    {
        "id": "planning-risk-verification",
        "task": "planning",
        "prompt": (
            "Create a very short implementation plan for adding a health endpoint. "
            "Include the literal headings REQUIREMENTS, RISKS, and VERIFICATION."
        ),
        "required_terms": ("requirements", "risks", "verification"),
    },
    {
        "id": "review-edge-case",
        "task": "review",
        "prompt": (
            "Review `def divide(a, b): return a / b`. Briefly identify the zero-divisor "
            "edge case and mention a test."
        ),
        "required_terms": ("zero", "test"),
    },
    {
        "id": "token-budget-documentation",
        "task": "documentation",
        "prompt": (
            "In one sentence, explain why a daily token budget prevents accidental "
            "model overuse. Use both words token and budget."
        ),
        "required_terms": ("token", "budget"),
    },
)
PROHIBITED_ALIASES = (
    "claude-sonnet-4.6",
    "vendor/claude_sonnet_4.6",
    "agy/claude-sonnet-4-6-thinking",
)


def _artifact_path(brain: ProjectBrain) -> Path:
    directory = brain.directory / "audit" / "evaluations"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{EVALUATION_VERSION}-{uuid.uuid4().hex[:10]}.json"


def run_evaluation(
    brain: ProjectBrain,
    *,
    provider_id: str | None = None,
    model_id: str | None = None,
) -> dict:
    if (provider_id is None) != (model_id is None):
        raise GuardianError("Live evaluation requires both provider_id and model_id.")

    catalog_validation = validate_catalog()
    routing_results = []
    savings = []
    for task, expected in ROUTING_SCENARIOS:
        selection = select_profiles(task, limit=5)
        selected = {item["slug"] for item in selection["selected"]}
        matched = sorted(selected & expected)
        passed = bool(matched)
        routing_results.append({
            "task": task,
            "expected_any": sorted(expected),
            "selected": sorted(selected),
            "matched": matched,
            "passed": passed,
        })
        savings.append(selection["context"]["estimated_savings_percent"])

    prohibited_results = [
        {"model": alias, "blocked": not is_model_allowed(alias)}
        for alias in PROHIBITED_ALIASES
    ]
    deterministic_passed = (
        catalog_validation["valid"]
        and all(item["passed"] for item in routing_results)
        and all(item["blocked"] for item in prohibited_results)
        and min(savings) >= 90
    )

    live_results = []
    if provider_id and model_id:
        for scenario in LIVE_SCENARIOS:
            route = resolve_configured_route(
                brain,
                scenario["task"],
                provider_id,
                model_id,
            )
            completion = complete_task_with_model(
                brain,
                scenario["task"],
                scenario["prompt"],
                route=route,
            )
            response = completion["response"]
            lowered = response.lower()
            missing = [
                term for term in scenario["required_terms"]
                if term not in lowered
            ]
            live_results.append({
                "id": scenario["id"],
                "task": scenario["task"],
                "provider": completion["provider"],
                "model": completion["model"],
                "required_terms": list(scenario["required_terms"]),
                "missing_terms": missing,
                "passed": not missing,
                "usage": completion.get("usage"),
                "response": response,
            })

    live_quality_score = None
    if live_results:
        earned = sum(
            len(item["required_terms"]) - len(item["missing_terms"])
            for item in live_results
        )
        possible = sum(len(item["required_terms"]) for item in live_results)
        live_quality_score = round(100 * earned / possible, 1) if possible else 0.0
    passed = deterministic_passed and all(item["passed"] for item in live_results)
    result = {
        "schema_version": EVALUATION_VERSION,
        "created_at": now_utc(),
        "passed": passed,
        "mode": "live" if live_results else "deterministic",
        "catalog": catalog_validation,
        "routing": {
            "passed": all(item["passed"] for item in routing_results),
            "minimum_context_savings_percent": min(savings),
            "scenarios": routing_results,
        },
        "model_policy": {
            "passed": all(item["blocked"] for item in prohibited_results),
            "scenarios": prohibited_results,
        },
        "live_quality": {
            "executed": bool(live_results),
            "passed": all(item["passed"] for item in live_results) if live_results else None,
            "quality_score_percent": live_quality_score,
            "scenarios": live_results,
        },
    }
    path = _artifact_path(brain)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    result["artifact"] = str(path)
    append_journey(
        brain,
        "Guardian Evaluation Completed",
        [
            f"Version: {EVALUATION_VERSION}",
            f"Mode: {result['mode']}",
            f"Passed: {passed}",
            f"Artifact: {path.relative_to(brain.root)}",
        ],
    )
    return result


def evaluation_history(brain: ProjectBrain) -> dict:
    """Aggregate versioned live evaluations without loading response bodies."""
    directory = brain.directory / "audit" / "evaluations"
    groups: dict[tuple[str, str], dict] = {}
    files_checked = 0
    if directory.is_dir():
        for path in sorted(directory.glob(f"{EVALUATION_VERSION}-*.json")):
            files_checked += 1
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            live = record.get("live_quality", {})
            scenarios = live.get("scenarios")
            if not live.get("executed") or not isinstance(scenarios, list) or not scenarios:
                continue
            first = scenarios[0]
            provider, model = first.get("provider"), first.get("model")
            if not isinstance(provider, str) or not isinstance(model, str):
                continue
            group = groups.setdefault((provider, model), {
                "provider": provider,
                "model": model,
                "runs": 0,
                "scenario_count": 0,
                "passed_scenarios": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "quality_scores": [],
                "last_run_at": None,
            })
            group["runs"] += 1
            group["scenario_count"] += len(scenarios)
            group["passed_scenarios"] += sum(bool(item.get("passed")) for item in scenarios)
            group["last_run_at"] = record.get("created_at")
            for scenario in scenarios:
                usage = scenario.get("usage")
                if isinstance(usage, dict):
                    group["total_tokens"] += int(usage.get("total_tokens") or 0)
                    group["total_cost_usd"] += float(usage.get("cost_usd") or 0.0)
            score = live.get("quality_score_percent")
            if not isinstance(score, (int, float)):
                earned = sum(
                    len(item.get("required_terms", [])) - len(item.get("missing_terms", []))
                    for item in scenarios
                )
                possible = sum(len(item.get("required_terms", [])) for item in scenarios)
                score = 100 * earned / possible if possible else 0.0
            group["quality_scores"].append(float(score))
    models = []
    for group in groups.values():
        scenario_count = group.pop("scenario_count")
        passed_scenarios = group.pop("passed_scenarios")
        quality_scores = group.pop("quality_scores")
        models.append({
            **group,
            "scenario_count": scenario_count,
            "scenario_pass_rate_percent": round(
                100 * passed_scenarios / scenario_count, 1
            ) if scenario_count else 0.0,
            "average_quality_score_percent": round(
                sum(quality_scores) / len(quality_scores), 1
            ) if quality_scores else 0.0,
            "average_tokens_per_scenario": round(
                group["total_tokens"] / scenario_count, 1
            ) if scenario_count else 0.0,
            "total_cost_usd": round(group["total_cost_usd"], 8),
        })
    models.sort(
        key=lambda item: (
            -item["average_quality_score_percent"],
            item["average_tokens_per_scenario"],
            item["provider"],
            item["model"],
        )
    )
    return {
        "schema_version": "guardian-evaluation-history-v1",
        "files_checked": files_checked,
        "model_count": len(models),
        "models": models,
    }


def evaluation_regression_alerts(
    brain: ProjectBrain,
    *,
    quality_drop_threshold: float = 10.0,
    token_increase_threshold: float = 50.0,
) -> dict:
    """Compare the latest two live runs for each route and persist regressions."""
    if quality_drop_threshold < 0 or token_increase_threshold < 0:
        raise GuardianError("Regression thresholds cannot be negative.")
    directory = brain.directory / "audit" / "evaluations"
    runs: dict[tuple[str, str], list[dict]] = {}
    if directory.is_dir():
        paths = sorted(
            directory.glob(f"{EVALUATION_VERSION}-*.json"),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
        )
        for path in paths:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            live = record.get("live_quality", {})
            scenarios = live.get("scenarios")
            if not live.get("executed") or not isinstance(scenarios, list) or not scenarios:
                continue
            provider = scenarios[0].get("provider")
            model = scenarios[0].get("model")
            if not isinstance(provider, str) or not isinstance(model, str):
                continue
            score = live.get("quality_score_percent")
            if not isinstance(score, (int, float)):
                possible = sum(len(item.get("required_terms", [])) for item in scenarios)
                earned = sum(
                    len(item.get("required_terms", [])) - len(item.get("missing_terms", []))
                    for item in scenarios
                )
                score = 100 * earned / possible if possible else 0.0
            tokens = sum(
                int(item.get("usage", {}).get("total_tokens") or 0)
                for item in scenarios
                if isinstance(item.get("usage"), dict)
            )
            runs.setdefault((provider, model), []).append({
                "created_at": record.get("created_at"),
                "passed": bool(live.get("passed")),
                "quality_score_percent": float(score),
                "tokens_per_scenario": tokens / len(scenarios),
                "artifact": str(path),
            })
    comparisons = []
    alerts = []
    for (provider, model), model_runs in sorted(runs.items()):
        if len(model_runs) < 2:
            continue
        previous, current = model_runs[-2:]
        quality_drop = previous["quality_score_percent"] - current["quality_score_percent"]
        token_increase = (
            100 * (
                current["tokens_per_scenario"] - previous["tokens_per_scenario"]
            ) / previous["tokens_per_scenario"]
            if previous["tokens_per_scenario"] > 0 else 0.0
        )
        reasons = []
        if previous["passed"] and not current["passed"]:
            reasons.append("pass-to-fail")
        if quality_drop >= quality_drop_threshold and quality_drop > 0:
            reasons.append("quality-drop")
        if token_increase >= token_increase_threshold and token_increase > 0:
            reasons.append("token-increase")
        comparison = {
            "provider": provider,
            "model": model,
            "previous": previous,
            "current": current,
            "quality_drop_points": round(quality_drop, 1),
            "token_increase_percent": round(token_increase, 1),
            "reasons": reasons,
        }
        comparisons.append(comparison)
        if reasons:
            digest = hashlib.sha256(
                f"{provider}:{model}:{current['artifact']}:{','.join(reasons)}".encode("utf-8")
            ).hexdigest()[:12]
            alerts.append({"id": f"eval-alert-{digest}", **comparison})
    report = {
        "schema_version": "guardian-evaluation-regressions-v1",
        "created_at": now_utc(),
        "passed": not alerts,
        "quality_drop_threshold": quality_drop_threshold,
        "token_increase_threshold": token_increase_threshold,
        "comparison_count": len(comparisons),
        "alert_count": len(alerts),
        "alerts": alerts,
        "comparisons": comparisons,
    }
    path = brain.directory / "audit" / "evaluation-regressions.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if alerts:
        append_journey(
            brain,
            "Model Evaluation Regression Alert",
            [
                f"Alerts: {len(alerts)}",
                "Routes: " + ", ".join(
                    f"{item['provider']}:{item['model']}" for item in alerts
                ),
            ],
        )
    return {**report, "artifact": str(path)}
