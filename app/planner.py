"""LLM-as-planner: NL query -> QueryPlan.

The LLM (or stub heuristic) only chooses filters + aggregation + viz type.
All counts are computed deterministically downstream.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from .nl_extract import (
    BY_DIM_PATTERNS,
    COMPARE_PATTERN,
    DIM_AXIS_KEYWORDS,
    DIM_CATEGORY_KEYWORDS,
    detect_compare_axis,
    extract_filters_from_query,
    network_kind_for,
)
from .plan_verifier import (
    PlannerError,
    should_use_off_topic_fallback,
    validate_plan_intent,
    verify_plan,
)
from .planner_schema import PLAN_JSON_SCHEMA, SYSTEM_PROMPT
from .schemas import AnalyzeRequest, Aggregation, Filters, QueryPlan


# ---- structured-field overrides ------------------------------------------

_OVERRIDABLE = (
    "drug_name", "condition", "sponsor", "country",
    "phase", "status", "sponsor_class", "study_type", "sex",
    "intervention_type", "start_year", "end_year",
)


def merge_user_overrides(plan: QueryPlan, req: AnalyzeRequest) -> QueryPlan:
    """User-provided structured fields override anything the LLM picked."""
    for k in _OVERRIDABLE:
        v = getattr(req, k)
        if v is not None:
            setattr(plan.filters, k, v)
    return plan


# ---- stub planner --------------------------------------------------------

def _stub_plan(req: AnalyzeRequest) -> QueryPlan:
    """Heuristic keyword routing — used when STUB_LLM=1."""
    q = req.query.lower()
    inf = extract_filters_from_query(req, q)
    drug, cond = inf["drug_name"], inf["condition"]

    def base_filters(**overrides: Any) -> Filters:
        return Filters(sponsor=req.sponsor, country=req.country, **{**inf, **overrides})

    def make(viz: Any, title: str, interp: str, agg: Aggregation,
             filters: Optional[Filters] = None) -> QueryPlan:
        return QueryPlan(
            visualization_type=viz, title=title, query_interpretation=interp,
            filters=filters or base_filters(), aggregation=agg,
        )

    # 1. Cross-dimension comparison ("compare sponsor class across conditions").
    # Only applies when both sides of the comparison are dimensions, not named
    # entities — otherwise we'd misread "compare A vs B by sponsor class" as
    # "compare sponsor_class across sponsor".
    if "compare" in q and not COMPARE_PATTERN.search(q):
        series_dim = next(
            (dim for kw, dim in DIM_CATEGORY_KEYWORDS.items() if kw in q), None,
        )
        axis_dim = None
        if (m := re.search(r"\b(?:across|by|over|between)\s+([\w\-]+)", q)):
            axis_dim = DIM_AXIS_KEYWORDS.get(m.group(1).lower())
        if series_dim and axis_dim and series_dim != axis_dim:
            return make(
                "grouped_bar_chart",
                f"Compare {series_dim.replace('_',' ')} across {axis_dim.replace('_',' ')}",
                f"Group trials by {axis_dim} and break each group down by "
                f"{series_dim}. Each cell is a deterministic CT.gov count.",
                Aggregation(group_by=axis_dim, series=series_dim),  # type: ignore[arg-type]
            )

    # 2. X-vs-Y comparison.
    if "compare" in q or " vs " in q or " versus " in q:
        m = COMPARE_PATTERN.search(q)
        names = [m.group(1).strip().title(), m.group(2).strip().title()] if m else []
        axis = detect_compare_axis(q) or "phase"
        # If the user already says "compare X vs Y by <self>" don't echo — the
        # comparison axis must be a different dimension.
        if axis == "intervention_name":
            axis = "phase"
        axis_label = axis.replace("_", " ")
        return make(
            "grouped_bar_chart",
            f"{axis_label.title()} distribution: "
            f"{' vs '.join(names) or 'comparison'}",
            f"Compare {axis_label} distribution between specified items.",
            Aggregation(
                group_by=axis, series="intervention_name",  # type: ignore[arg-type]
                series_values=names or None,
            ),
            # Drop drug_name from top-level filters; series_values drive the
            # per-query fetches.
            filters=base_filters(drug_name=None),
        )

    # 3. Relationship / network signals.
    if kind := network_kind_for(q):
        return make(
            "network_graph",
            f"Network ({kind.replace('_', ' ↔ ')})",
            f"Build a {kind} network from matching trials.",
            Aggregation(network_kind=kind),
        )

    # 4. Explicit "by <dim>" framings.
    for pat, dim, hint in BY_DIM_PATTERNS:
        if re.search(pat, q):
            viz = "time_series" if dim == "year" else "bar_chart"
            return make(
                viz,
                f"Trials by {hint}" + (f" ({drug or cond})" if drug or cond else ""),
                f"Distribute matching trials by {hint}.",
                Aggregation(group_by=dim),  # type: ignore[arg-type]
            )

    # 5. Filter keywords without explicit "by ..." framing.
    if "status" in q or "recruiting" in q or "completed" in q:
        return make(
            "bar_chart", "Trials by status",
            "Distribute matching trials by overall status.",
            Aggregation(group_by="overall_status"),
        )

    if "phase" in q and ("distribut" in q or "across" in q):
        return make(
            "bar_chart",
            f"Trials by phase{f' ({drug or cond})' if drug or cond else ''}",
            "Distribute matching trials by phase.",
            Aggregation(group_by="phase"),
        )

    if "intervention" in q and "type" in q:
        return make(
            "bar_chart", "Trials by intervention type",
            "Distribute matching trials by intervention type.",
            Aggregation(group_by="intervention_type"),
        )

    if "enrollment" in q and ("histogram" in q or "distribution" in q):
        return make(
            "histogram", "Enrollment size distribution",
            "Histogram of enrollment counts.",
            Aggregation(x_field="enrollment_count", bin_count=12),
        )

    if "enrollment" in q and "duration" in q:
        return make(
            "scatter_plot", "Enrollment vs duration",
            "Scatter of enrollment count vs trial duration.",
            Aggregation(x_field="duration_months", y_field="enrollment_count"),
        )

    # 6. Default: trials per year.
    return make(
        "time_series",
        f"Trials per year{f' ({drug or cond})' if drug or cond else ''}",
        "Count trials by start year.",
        Aggregation(group_by="year"),
    )


# ---- OpenAI planner ------------------------------------------------------

def _openai_plan(req: AnalyzeRequest, repair_hint: Optional[str] = None) -> QueryPlan:
    from openai import OpenAI  # imported lazily

    client = OpenAI()
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    overrides = {
        k: getattr(req, k)
        for k in _OVERRIDABLE
        if getattr(req, k) is not None
    }

    system = SYSTEM_PROMPT
    if repair_hint:
        system += (
            "\n\nIMPORTANT — REPAIR ATTEMPT: Your previous response was "
            "rejected. Re-read the schema carefully. Specific issue:\n"
            + repair_hint
            + "\n\nReturn STRICTLY valid JSON matching the schema. Use canonical "
            "enum values exactly (PHASE3 not 'phase 3'; RECRUITING not "
            "'recruiting'). If you cannot honor a constraint, omit the field "
            "rather than inventing a value."
        )

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(
                {"query": req.query, "structured_overrides": overrides}
            )},
        ],
        response_format={"type": "json_schema", "json_schema": PLAN_JSON_SCHEMA},
        temperature=0,
    )
    raw = resp.choices[0].message.content or "{}"
    return QueryPlan.model_validate_json(raw)


def _safe_default_plan(req: AnalyzeRequest, reason: str) -> QueryPlan:
    """Last-resort plan when both LLM and stub heuristics fail."""
    if req.start_year or req.end_year:
        viz, agg, title = "time_series", Aggregation(group_by="year"), "Trials per year"
    else:
        viz, agg, title = "bar_chart", Aggregation(group_by="phase"), "Trials by phase"
    return QueryPlan(
        visualization_type=viz,  # type: ignore[arg-type]
        title=title,
        query_interpretation=(
            f"Could not interpret query precisely; falling back to a default "
            f"{viz} view. Reason: {reason}"
        ),
        filters=Filters(**{k: getattr(req, k) for k in _OVERRIDABLE}),
        aggregation=agg,
        notes=f"fallback:{reason}",
    )


def _plan_without_overrides(req: AnalyzeRequest) -> QueryPlan:
    if os.environ.get("STUB_LLM", "").lower() in ("1", "true", "yes"):
        try:
            return _stub_plan(req)
        except (RuntimeError, TypeError, ValueError) as e:
            return _safe_default_plan(req, f"stub planner error: {e}")

    try:
        return _openai_plan(req)
    except Exception as e:  # noqa: BLE001 - external SDK/model boundary.
        try:
            return _openai_plan(req, repair_hint=str(e)[:400])
        except Exception as e2:  # noqa: BLE001 - final external-boundary fallback.
            return _safe_default_plan(req, f"LLM planner failed: {e2}")


def plan_query(req: AnalyzeRequest) -> QueryPlan:
    try:
        plan = _plan_without_overrides(req)
        if should_use_off_topic_fallback(req):
            plan = _safe_default_plan(req, "query appears outside the clinical-trials domain")
        plan = verify_plan(plan, req)
        return merge_user_overrides(plan, req)
    except (RuntimeError, TypeError, ValueError) as e:
        raise PlannerError(str(e)) from e


# Backward-compatible test hook; implementation now lives in plan_verifier.py.
_BY_DIM_PATTERNS = BY_DIM_PATTERNS
_COMPARE_PATTERN = COMPARE_PATTERN
_DIM_AXIS_KEYWORDS = DIM_AXIS_KEYWORDS
_DIM_CATEGORY_KEYWORDS = DIM_CATEGORY_KEYWORDS
_detect_compare_axis = detect_compare_axis
_extract_filters_from_query = extract_filters_from_query
_network_kind_for = network_kind_for
_validate_plan_intent = validate_plan_intent
