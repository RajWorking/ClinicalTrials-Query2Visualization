"""LLM-as-planner: NL query -> QueryPlan.

Calls OpenRouter (OpenAI-compatible endpoint) to convert a natural-language
question into a structured QueryPlan. All counts are computed deterministically
downstream — the LLM only chooses filters, aggregation, and viz type.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from pydantic import ValidationError

from .plan_verifier import PlannerError, verify_plan
from .planner_schema import PLAN_JSON_SCHEMA, SYSTEM_PROMPT
from .schemas import AnalyzeRequest, QueryPlan


_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

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


def _client_kwargs() -> dict[str, Any]:
    """OpenAI-SDK kwargs pointed at the OpenRouter endpoint."""
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENROUTER_BASE_URL") or _OPENROUTER_BASE_URL
    kwargs: dict[str, Any] = {"base_url": base_url}
    if api_key:
        kwargs["api_key"] = api_key
    headers = {k: v for k, v in {
        "HTTP-Referer": os.environ.get("OPENROUTER_SITE_URL"),
        "X-Title": os.environ.get("OPENROUTER_APP_NAME", "Cheiron"),
    }.items() if v}
    if headers:
        kwargs["default_headers"] = headers
    return kwargs


def _planner_model() -> str:
    return os.environ.get("OPENROUTER_MODEL") or "openai/gpt-4o-mini"


def _llm_plan(req: AnalyzeRequest, repair_hint: Optional[str] = None) -> QueryPlan:
    from openai import OpenAI  # imported lazily to avoid a hard dep in tests

    overrides = {k: getattr(req, k) for k in _OVERRIDABLE if getattr(req, k) is not None}
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

    resp = OpenAI(**_client_kwargs()).chat.completions.create(
        model=_planner_model(),
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


def plan_query(req: AnalyzeRequest) -> QueryPlan:
    try:
        plan = _llm_plan(req)
    except ValidationError as e:
        try:
            plan = _llm_plan(req, repair_hint=str(e)[:400])
        except ValidationError as e2:
            raise PlannerError(f"LLM returned invalid plan after repair: {e2}") from e2
        except Exception as e2:  # noqa: BLE001 - external SDK/provider boundary.
            raise PlannerError(f"LLM planner failed during repair: {e2}") from e2
    except Exception as e:  # noqa: BLE001 - external SDK/provider boundary.
        raise PlannerError(f"LLM planner failed: {e}") from e
    plan = verify_plan(plan, req)
    return merge_user_overrides(plan, req)
