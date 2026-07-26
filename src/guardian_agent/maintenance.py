"""Persistent zero-completion maintenance coordinator."""

from __future__ import annotations

import fcntl
import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from guardian_agent.citations import list_citations, verify_citation
from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc
from guardian_agent.evaluation import (
    evaluation_regression_alerts,
    run_evaluation,
)
from guardian_agent.external_skills import audit_external_skills
from guardian_agent.gateway import probe_provider_capacity
from guardian_agent.runtime import is_kill_switch_active
from guardian_agent.omniroute_logs import audit_omniroute_logs
from guardian_agent.vault import redact_secrets


MAINTENANCE_FILE = "maintenance.json"
VALID_JOB_TYPES = {
    "deterministic-evaluation",
    "external-skill-audit",
    "evaluation-regression-check",
    "provider-probe",
    "citation-verify",
    "omniroute-log-audit",
}


def _path(brain: ProjectBrain) -> Path:
    return brain.directory / MAINTENANCE_FILE


def _default_jobs() -> list[dict]:
    return [
        _new_job("deterministic-evaluation", 86400, {}),
        _new_job("external-skill-audit", 86400, {}),
        _new_job("evaluation-regression-check", 86400, {}),
    ]


def _new_job(job_type: str, interval_seconds: int, parameters: dict) -> dict:
    return {
        "id": f"maint-{uuid.uuid4().hex[:10]}",
        "type": job_type,
        "enabled": True,
        "interval_seconds": interval_seconds,
        "parameters": parameters,
        "last_run_epoch": None,
        "next_run_epoch": 0,
        "failure_count": 0,
        "last_status": "never",
        "last_error": None,
    }


def initialize_maintenance(brain: ProjectBrain) -> dict:
    path = _path(brain)
    if not path.exists():
        payload = {
            "version": 1,
            "created_at": now_utc(),
            "policy": {
                "model_completions_allowed": False,
                "maximum_jobs_per_run": 10,
                "note": "Network jobs require explicit configuration; live model evaluation is never scheduled.",
            },
            "jobs": _default_jobs(),
        }
        _save(brain, payload)
        append_journey(
            brain,
            "Safe Maintenance Schedule Initialized",
            ["Installed three local zero-completion maintenance jobs."],
        )
    return _load(brain)


def _load(brain: ProjectBrain) -> dict:
    path = _path(brain)
    if not path.exists():
        return initialize_maintenance(brain)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GuardianError(f"Invalid maintenance configuration: {error}") from error
    if not isinstance(payload.get("jobs"), list):
        raise GuardianError("Invalid maintenance configuration: jobs must be a list.")
    return payload


def _save(brain: ProjectBrain, payload: dict) -> None:
    path = _path(brain)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def add_maintenance_job(
    brain: ProjectBrain,
    job_type: str,
    interval_seconds: int,
    *,
    provider_id: str | None = None,
    model_id: str | None = None,
) -> dict:
    if job_type not in VALID_JOB_TYPES:
        raise GuardianError(
            f"Unknown maintenance job type {job_type!r}; use: "
            + ", ".join(sorted(VALID_JOB_TYPES))
        )
    if interval_seconds < 60:
        raise GuardianError("Maintenance intervals must be at least 60 seconds.")
    parameters = {}
    if job_type == "provider-probe":
        if not provider_id or not model_id:
            raise GuardianError("Provider probe jobs require provider_id and model_id.")
        parameters = {"provider_id": provider_id, "model_id": model_id}
    elif provider_id or model_id:
        raise GuardianError("Provider/model parameters apply only to provider-probe jobs.")
    payload = _load(brain)
    duplicate = next(
        (
            job for job in payload["jobs"]
            if job.get("type") == job_type and job.get("parameters") == parameters
        ),
        None,
    )
    if duplicate:
        duplicate["interval_seconds"] = interval_seconds
        duplicate["enabled"] = True
        duplicate["next_run_epoch"] = 0
        job = duplicate
    else:
        job = _new_job(job_type, interval_seconds, parameters)
        payload["jobs"].append(job)
    _save(brain, payload)
    append_journey(
        brain,
        "Maintenance Job Configured",
        [f"Job: {job['id']}", f"Type: {job_type}", f"Interval: {interval_seconds}s"],
    )
    return job


def maintenance_status(brain: ProjectBrain) -> dict:
    payload = _load(brain)
    now_epoch = time.time()
    jobs = [
        {
            **job,
            "due": bool(
                job.get("enabled", True)
                and float(job.get("next_run_epoch") or 0) <= now_epoch
            ),
        }
        for job in payload["jobs"]
    ]
    return {
        "policy": payload.get("policy", {}),
        "kill_switch_active": is_kill_switch_active(brain),
        "job_count": len(jobs),
        "due_count": sum(job["due"] for job in jobs),
        "jobs": jobs,
    }


@contextmanager
def _runner_lock(brain: ProjectBrain):
    path = brain.directory / "tasks" / "maintenance-runner.lock"
    path.parent.mkdir(exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise GuardianError("Another maintenance runner currently holds the project lock.") from error
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _execute_job(brain: ProjectBrain, job: dict) -> dict:
    job_type = job["type"]
    parameters = job.get("parameters", {})
    if job_type == "deterministic-evaluation":
        result = run_evaluation(brain)
        return {"passed": result["passed"], "artifact": result["artifact"]}
    if job_type == "external-skill-audit":
        result = audit_external_skills(brain)
        return {"passed": result["passed"], "checked": result["count"]}
    if job_type == "evaluation-regression-check":
        result = evaluation_regression_alerts(brain)
        return {
            "passed": result["passed"],
            "alert_count": result["alert_count"],
            "artifact": result["artifact"],
        }
    if job_type == "provider-probe":
        result = probe_provider_capacity(
            brain,
            parameters["provider_id"],
            parameters["model_id"],
        )
        return {
            "passed": result["model_advertised"],
            "model_advertised": result["model_advertised"],
            "completion_tokens_spent": 0,
        }
    if job_type == "citation-verify":
        citations = list_citations(brain)
        changed = 0
        for citation in citations[:25]:
            result = verify_citation(brain, citation["id"])
            changed += result["verification"]["status"] == "changed"
        return {"passed": changed == 0, "checked": min(25, len(citations)), "changed": changed}
    if job_type == "omniroute-log-audit":
        result = audit_omniroute_logs(brain)
        return {
            "passed": True,
            "events": result["event_count"],
            "failures": result["failure_count"],
            "artifact": result["artifact"],
        }
    raise GuardianError(f"Unsupported maintenance job type: {job_type}")


def run_due_maintenance(
    brain: ProjectBrain,
    *,
    max_jobs: int = 10,
    force: bool = False,
) -> dict:
    if max_jobs < 1 or max_jobs > 20:
        raise GuardianError("Maintenance max_jobs must be between 1 and 20.")
    if is_kill_switch_active(brain):
        raise GuardianError("Emergency stop is active; maintenance did not run.")
    with _runner_lock(brain):
        payload = _load(brain)
        if payload.get("policy", {}).get("model_completions_allowed", False):
            raise GuardianError("Invalid maintenance policy: model completions must remain disabled.")
        now_epoch = time.time()
        due = [
            job for job in payload["jobs"]
            if job.get("enabled", True)
            and (force or float(job.get("next_run_epoch") or 0) <= now_epoch)
        ][:max_jobs]
        records = []
        for job in due:
            started = time.monotonic()
            try:
                result = _execute_job(brain, job)
                job["failure_count"] = 0
                job["last_status"] = "passed" if result.get("passed", True) else "attention"
                job["last_error"] = None
                delay = int(job["interval_seconds"])
                status = job["last_status"]
            except Exception as error:
                job["failure_count"] = int(job.get("failure_count", 0)) + 1
                job["last_status"] = "failed"
                job["last_error"] = redact_secrets(brain, str(error))[:1000]
                delay = min(86400, 60 * (2 ** min(job["failure_count"] - 1, 10)))
                result = {"passed": False}
                status = "failed"
            job["last_run_epoch"] = now_epoch
            job["next_run_epoch"] = now_epoch + delay
            records.append({
                "id": job["id"],
                "type": job["type"],
                "status": status,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "next_run_epoch": job["next_run_epoch"],
                "result": result,
                "error": job["last_error"],
            })
        _save(brain, payload)
    append_journey(
        brain,
        "Maintenance Runner Completed",
        [
            f"Jobs executed: {len(records)}",
            f"Passed: {sum(item['status'] == 'passed' for item in records)}",
            f"Attention/failed: {sum(item['status'] != 'passed' for item in records)}",
            "Model completions spent: 0",
        ],
    )
    return {
        "executed": len(records),
        "model_completions_spent": 0,
        "records": records,
    }


def scheduler_instructions(brain: ProjectBrain) -> dict:
    return {
        "recommended_interval_minutes": 15,
        "command_argv": [
            "guardian",
            "maintenance",
            "run",
            "--project",
            str(brain.root),
        ],
        "note": (
            "Invoke this argv from the user's scheduler of choice. Guardian does not "
            "install a daemon or modify cron/systemd automatically."
        ),
    }
