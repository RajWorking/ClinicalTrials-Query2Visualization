"""Deterministic plan checks applied after LLM planning."""
from __future__ import annotations

from .schemas import AnalyzeRequest, QueryPlan


class PlannerError(RuntimeError):
    """Raised when the LLM planner fails and cannot be repaired."""


def verify_plan(plan: QueryPlan, req: AnalyzeRequest) -> QueryPlan:
    """Hook for deterministic plan checks after schema validation.

    Currently a pass-through; extend here before adding another LLM call.
    """
    return plan
