"""Deterministic plan checks applied after LLM or stub planning."""
from __future__ import annotations

from .nl_extract import detect_compare_axis, is_obviously_off_topic
from .schemas import AnalyzeRequest, QueryPlan


class PlannerError(RuntimeError):
    """Planner failed before it could produce a safe fallback."""


def validate_plan_intent(plan: QueryPlan, req: AnalyzeRequest) -> QueryPlan:
    """Repair plans whose comparison axis disagrees with the query.

    The LLM can produce grouped_bar plans that ignore an explicit "by <axis>"
    framing, e.g. "Compare Pembro vs Nivo by year" returning group_by=phase.
    When the query carries an unambiguous axis hint, trust the query and make
    the correction visible in query_interpretation.
    """
    if plan.visualization_type != "grouped_bar_chart":
        return plan
    if not (plan.aggregation.series and plan.aggregation.series_values):
        return plan
    requested_axis = detect_compare_axis(req.query.lower())
    if not requested_axis or requested_axis == "intervention_name":
        return plan
    if plan.aggregation.group_by == requested_axis:
        return plan
    original = plan.aggregation.group_by
    plan.aggregation.group_by = requested_axis  # type: ignore[assignment]
    note = (
        f" (Axis repaired: query asked for '{requested_axis}', "
        f"plan had '{original}'.)"
    )
    plan.query_interpretation = (plan.query_interpretation or "").rstrip() + note
    return plan


def verify_plan(plan: QueryPlan, req: AnalyzeRequest) -> QueryPlan:
    """Run deterministic plan checks that do not require another model call."""
    return validate_plan_intent(plan, req)


def should_use_off_topic_fallback(req: AnalyzeRequest) -> bool:
    return is_obviously_off_topic(req)
