"""Shared model allow/deny policy enforced across routing and handoffs."""

from __future__ import annotations

import re

from guardian_agent.core import GuardianError


PROHIBITED_MODELS = ("claude-sonnet-4.6",)


def normalize_model_id(model_id: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", model_id.strip().lower())).strip("-")


def is_model_allowed(model_id: str) -> bool:
    normalized = normalize_model_id(model_id)
    return all(
        normalize_model_id(prohibited) not in normalized
        for prohibited in PROHIBITED_MODELS
    )


def require_model_allowed(model_id: str) -> None:
    if not is_model_allowed(model_id):
        raise GuardianError(f"Model {model_id!r} is prohibited by Guardian model policy.")
