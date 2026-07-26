"""Persistent, concurrency-safe model token and cost budgets."""

from __future__ import annotations

import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from guardian_agent.core import GuardianError, ProjectBrain


BUDGET_FILE = "model-budget.json"


@dataclass(frozen=True)
class BudgetReservation:
    id: str
    date: str
    tokens: int
    cost_usd: float


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _paths(brain: ProjectBrain) -> tuple[Path, Path]:
    audit = brain.directory / "audit"
    audit.mkdir(exist_ok=True)
    return audit / BUDGET_FILE, audit / f"{BUDGET_FILE}.lock"


def _empty_ledger(day: str) -> dict:
    return {
        "version": 1,
        "date": day,
        "spent_tokens": 0,
        "spent_cost_usd": 0.0,
        "reservations": {},
    }


def _read_ledger(path: Path, day: str) -> dict:
    if not path.exists():
        return _empty_ledger(day)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GuardianError(f"Invalid model budget ledger: {error}") from error
    if payload.get("date") != day:
        return _empty_ledger(day)
    if not isinstance(payload.get("reservations"), dict):
        raise GuardianError("Invalid model budget ledger: reservations must be an object.")
    return payload


def _write_ledger(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def _locked_ledger(brain: ProjectBrain) -> Iterator[tuple[Path, dict]]:
    path, lock_path = _paths(brain)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        ledger = _read_ledger(path, _today())
        try:
            yield path, ledger
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def estimate_tokens(text: str) -> int:
    """Return a conservative preflight bound, not a billing-token estimate."""
    return max(1, len(text.encode("utf-8")))


def estimate_route_cost(
    route: dict,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    if route.get("cost_tier") in {
        "local", "free", "free-limited", "subscription"
    }:
        return 0.0
    input_rate = route.get("input_cost_per_million")
    output_rate = route.get("output_cost_per_million")
    if not isinstance(input_rate, (int, float)) or not isinstance(output_rate, (int, float)):
        raise GuardianError(
            f"Paid route {route.get('provider')}:{route.get('model')} has no verified pricing; execution stopped."
        )
    return (
        prompt_tokens * float(input_rate)
        + completion_tokens * float(output_rate)
    ) / 1_000_000


def reserve_budget(
    brain: ProjectBrain,
    policy: dict,
    route: dict,
    prompt: str,
    system_prompt: str,
) -> BudgetReservation:
    # UTF-8 bytes bound tokenizer output for ordinary text; the fixed allowance
    # covers chat-message framing that is not present in the visible strings.
    visible_prompt_tokens = estimate_tokens(prompt) + estimate_tokens(system_prompt) + 32
    multiplier = route.get("prompt_reservation_multiplier", 1.0)
    if not isinstance(multiplier, (int, float)) or multiplier < 1:
        raise GuardianError("Route prompt reservation multiplier must be at least 1.")
    prompt_tokens = int(visible_prompt_tokens * float(multiplier) + 0.999)
    completion_tokens = int(policy.get("max_completion_tokens", 2048))
    if completion_tokens < 1:
        raise GuardianError("max_completion_tokens must be positive.")
    reserved_tokens = prompt_tokens + completion_tokens
    reserved_cost = estimate_route_cost(route, prompt_tokens, completion_tokens)
    token_limit = int(policy.get("daily_token_budget", 250000))
    cost_limit = float(policy.get("daily_cost_budget_usd", 0.0))
    if token_limit < 1 or cost_limit < 0:
        raise GuardianError("Model budget policy has invalid limits.")

    with _locked_ledger(brain) as (path, ledger):
        active_tokens = sum(
            int(item.get("tokens", 0))
            for item in ledger["reservations"].values()
            if isinstance(item, dict)
        )
        active_cost = sum(
            float(item.get("cost_usd", 0.0))
            for item in ledger["reservations"].values()
            if isinstance(item, dict)
        )
        if int(ledger.get("spent_tokens", 0)) + active_tokens + reserved_tokens > token_limit:
            raise GuardianError(
                f"Daily model token budget would be exceeded "
                f"({token_limit} tokens); execution stopped before the provider call."
            )
        if float(ledger.get("spent_cost_usd", 0.0)) + active_cost + reserved_cost > cost_limit:
            raise GuardianError(
                f"Daily model cost budget would be exceeded "
                f"(${cost_limit:.4f}); execution stopped before the provider call."
            )
        reservation = BudgetReservation(
            id=f"budget-{uuid.uuid4().hex[:12]}",
            date=ledger["date"],
            tokens=reserved_tokens,
            cost_usd=reserved_cost,
        )
        ledger["reservations"][reservation.id] = {
            "tokens": reservation.tokens,
            "cost_usd": reservation.cost_usd,
            "provider": route.get("provider"),
            "model": route.get("model"),
        }
        _write_ledger(path, ledger)
    return reservation


def settle_budget(
    brain: ProjectBrain,
    reservation: BudgetReservation,
    *,
    actual_tokens: int | None,
    actual_cost_usd: float | None,
    charge_reservation: bool,
) -> dict:
    with _locked_ledger(brain) as (path, ledger):
        record = ledger["reservations"].pop(reservation.id, None)
        if record is None:
            raise GuardianError(f"Unknown or already settled budget reservation {reservation.id}.")
        charged_tokens = (
            reservation.tokens if charge_reservation
            else max(0, int(actual_tokens or 0))
        )
        charged_cost = (
            reservation.cost_usd if charge_reservation
            else max(0.0, float(actual_cost_usd or 0.0))
        )
        ledger["spent_tokens"] = int(ledger.get("spent_tokens", 0)) + charged_tokens
        ledger["spent_cost_usd"] = float(ledger.get("spent_cost_usd", 0.0)) + charged_cost
        _write_ledger(path, ledger)
    return {"tokens": charged_tokens, "cost_usd": charged_cost}


def budget_status(brain: ProjectBrain, policy: dict) -> dict:
    with _locked_ledger(brain) as (_, ledger):
        active_tokens = sum(
            int(item.get("tokens", 0))
            for item in ledger["reservations"].values()
            if isinstance(item, dict)
        )
        active_cost = sum(
            float(item.get("cost_usd", 0.0))
            for item in ledger["reservations"].values()
            if isinstance(item, dict)
        )
        token_limit = int(policy.get("daily_token_budget", 250000))
        cost_limit = float(policy.get("daily_cost_budget_usd", 0.0))
        return {
            "date_utc": ledger["date"],
            "daily_token_budget": token_limit,
            "spent_tokens": int(ledger.get("spent_tokens", 0)),
            "reserved_tokens": active_tokens,
            "remaining_tokens": max(
                0,
                token_limit - int(ledger.get("spent_tokens", 0)) - active_tokens,
            ),
            "daily_cost_budget_usd": cost_limit,
            "spent_cost_usd": round(float(ledger.get("spent_cost_usd", 0.0)), 8),
            "reserved_cost_usd": round(active_cost, 8),
            "remaining_cost_usd": round(
                max(0.0, cost_limit - float(ledger.get("spent_cost_usd", 0.0)) - active_cost),
                8,
            ),
            "active_reservations": len(ledger["reservations"]),
        }
