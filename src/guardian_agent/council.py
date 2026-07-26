"""Opt-in multi-model council for difficult, non-side-effect decisions.

The protocol is inspired by the public LLM Council pattern: independent first
opinions, anonymous peer review, then a chairman synthesis. It is deliberately
an explicit command because it multiplies provider calls and should never be
used to authorize browser, account, payment, or destructive actions.
"""

from __future__ import annotations

import json
from pathlib import Path

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc
from guardian_agent.gateway import complete_task_with_model, list_routes_for_task


COUNCIL_FILE = "council.json"
SAFE_COUNCIL_TASKS = {"research", "planning", "review", "documentation", "routing"}


def council_path(brain: ProjectBrain) -> Path:
    return brain.directory / COUNCIL_FILE


def default_council() -> dict:
    return {
        "version": 1,
        "enabled": True,
        "max_members": 3,
        "chairman": None,
        "note": "Council is opt-in. It is for analysis and recommendations, never autonomous external actions.",
    }


def load_council(brain: ProjectBrain) -> dict:
    path = council_path(brain)
    if not path.exists():
        payload = default_council()
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return payload
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise GuardianError("Council configuration is invalid JSON.") from error


def configure_council(brain: ProjectBrain, max_members: int, chairman: str | None = None) -> dict:
    if not 1 <= max_members <= 8:
        raise GuardianError("Council member limit must be between 1 and 8.")
    payload = load_council(brain)
    payload["max_members"] = max_members
    payload["chairman"] = chairman or None
    council_path(brain).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _chair_route(brain: ProjectBrain, task: str, chairman: str | None) -> dict:
    routes = list_routes_for_task(brain, task)
    if chairman:
        for route in routes:
            if route["provider"] == chairman or f"{route['provider']}:{route['model']}" == chairman:
                return route
        raise GuardianError(f"Configured chairman {chairman!r} is not an eligible route for {task}.")
    return routes[0]


def run_council(brain: ProjectBrain, *, task: str, prompt: str, max_members: int | None = None) -> dict:
    if task not in SAFE_COUNCIL_TASKS:
        raise GuardianError("Council supports research, planning, review, documentation, and routing only.")
    config = load_council(brain)
    if not config.get("enabled", True):
        raise GuardianError("Council mode is disabled in council.json.")
    limit = max_members or int(config.get("max_members", 3))
    if not 1 <= limit <= 8:
        raise GuardianError("Council member limit must be between 1 and 8.")
    routes = list_routes_for_task(brain, task)[:limit]
    if not routes:
        raise GuardianError("No policy-approved model route is configured for this council task.")

    opinions: list[dict] = []
    for index, route in enumerate(routes, start=1):
        try:
            result = complete_task_with_model(
                brain, task, prompt,
                system_prompt="Give an independent, evidence-aware answer. State uncertainties and do not perform external actions.",
                route=route,
            )
            opinions.append({"id": f"Opinion {index}", "provider": route["provider"], "model": route["model"], "text": result["response"]})
        except GuardianError as error:
            opinions.append({"id": f"Opinion {index}", "provider": route["provider"], "model": route["model"], "error": str(error)})

    successful = [item for item in opinions if "text" in item]
    if not successful:
        raise GuardianError("Every council member failed; no synthesis was fabricated.")
    anonymized = "\n\n".join(f"{item['id']}:\n{item['text']}" for item in successful)
    reviews: list[dict] = []
    for index, route in enumerate(routes, start=1):
        try:
            review = complete_task_with_model(
                brain, "review",
                "Review these anonymized candidate answers to the original request below. Rank them by accuracy, completeness, and practical value. Explain concrete strengths, risks, and missing evidence.\n\n"
                f"Original request:\n{prompt}\n\nCandidates:\n{anonymized}",
                system_prompt="You are a neutral reviewer. Do not infer identities from candidate text and do not take external actions.",
                route=route,
            )
            reviews.append({"reviewer": f"Reviewer {index}", "text": review["response"]})
        except GuardianError as error:
            reviews.append({"reviewer": f"Reviewer {index}", "error": str(error)})

    chair = _chair_route(brain, task, config.get("chairman"))
    review_text = "\n\n".join(
        f"{item['reviewer']}:\n{item.get('text', 'Review unavailable: ' + item.get('error', 'unknown error'))}"
        for item in reviews
    )
    synthesis = complete_task_with_model(
        brain, task,
        "Produce a final decision-ready response to the original request. Use the independent opinions and anonymous reviews below. Resolve disagreements explicitly, preserve uncertainty, and recommend verification rather than inventing facts. Do not perform external actions.\n\n"
        f"Original request:\n{prompt}\n\nIndependent opinions:\n{anonymized}\n\nPeer reviews:\n{review_text}",
        system_prompt="You are the council chairman. Synthesize evidence; do not claim consensus where it is absent.",
        route=chair,
    )
    record = {
        "timestamp": now_utc(), "task": task, "members": opinions, "reviews": reviews,
        "chairman": {"provider": chair["provider"], "model": chair["model"]}, "response": synthesis["response"],
    }
    artifact_dir = brain.directory / "artifacts"
    artifact_dir.mkdir(exist_ok=True)
    artifact = artifact_dir / f"council_{now_utc().replace(':', '-').replace(' ', '_')}.json"
    artifact.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    append_journey(brain, "LLM Council Completed", [f"Task: {task}", f"Members attempted: {len(routes)}", f"Artifact: {artifact.name}"])
    return {"task": task, "chairman": record["chairman"], "response": record["response"], "artifact": str(artifact), "members": opinions, "reviews": reviews}
