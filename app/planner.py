"""LLM-as-planner: NL query → QueryPlan.

The LLM (or stub heuristic) only chooses filters + aggregation + viz type.
All counts are computed deterministically downstream.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from .aliases import CONDITION_ALIASES, DRUG_ALIASES
from .schemas import AnalyzeRequest, Aggregation, Filters, QueryPlan


SYSTEM_PROMPT = """\
You convert natural-language questions about clinical trials into a structured
QueryPlan that downstream code will execute against the ClinicalTrials.gov API.

You DO NOT compute numbers. You only choose:
  1. filters: which trials to retrieve
  2. aggregation: how to bucket and count them
  3. visualization_type: which chart type best answers the question
  4. title and query_interpretation: human-readable strings

Pick the visualization_type that most directly answers the question:
  - bar_chart: distribution across a categorical dimension
  - grouped_bar_chart: comparison of two or more named values across a dimension
  - time_series: trend over time. Use group_by=year by default.
  - histogram: distribution of a numeric field
  - scatter_plot: two numeric fields per trial
  - network_graph: relationships (sponsor_drug | drug_condition | drug_drug)

For grouped_bar_chart with comparisons (e.g. "Drug A vs Drug B"), set
aggregation.series = "intervention_name" and series_values = ["A", "B"];
leave drug_name unset on top-level filters (per-query fetches drive the comparison).

If the user already supplied a structured field (drug_name, condition, etc.)
the request layer overrides yours, so don't worry about re-extracting it.

EXAMPLES

Q: "How has the number of pembrolizumab trials changed each year since 2015?"
→ time_series, group_by=year, drug_name="Pembrolizumab", start_year=2015

Q: "Compare Pembrolizumab vs Nivolumab by phase."
→ grouped_bar_chart, group_by=phase, series=intervention_name,
  series_values=["Pembrolizumab","Nivolumab"]

Q: "Which countries have the most recruiting breast cancer trials?"
→ bar_chart, group_by=country, condition="Breast Cancer", status="RECRUITING"

Q: "Sponsor and drug network for melanoma trials."
→ network_graph, network_kind=sponsor_drug, condition="Melanoma"

Q: "Drugs that are often combined in cancer studies."
→ network_graph, network_kind=drug_drug, condition="Cancer"

Q: "Distribution of enrollment sizes for cardiology trials."
→ histogram, x_field=enrollment_count, bin_count=12, condition="Cardiology"

Q: "Does enrollment correlate with trial duration for industry-sponsored trials?"
→ scatter_plot, x_field=duration_months, y_field=enrollment_count
"""


# ---- OpenAI structured-output JSON schema --------------------------------

_VIZ_TYPES = [
    "bar_chart", "grouped_bar_chart", "time_series",
    "scatter_plot", "histogram", "network_graph",
]
_GROUP_DIMS = [
    "phase", "overall_status", "study_type", "sex",
    "lead_sponsor", "sponsor_class", "country",
    "intervention_type", "intervention_name", "condition",
    "year", "quarter", "month",
]
_NUMERIC_FIELDS = ["enrollment_count", "duration_months", "start_year"]
_NETWORK_KINDS = ["sponsor_drug", "drug_condition", "drug_drug"]
_PHASE_ENUM = ["PHASE1", "PHASE2", "PHASE3", "PHASE4", "EARLY_PHASE1", "NA"]
_STATUS_ENUM = [
    "RECRUITING", "NOT_YET_RECRUITING", "ACTIVE_NOT_RECRUITING",
    "COMPLETED", "TERMINATED", "WITHDRAWN", "SUSPENDED",
    "ENROLLING_BY_INVITATION", "UNKNOWN",
]


def _nullable_enum(values: list[str]) -> dict[str, Any]:
    return {"anyOf": [{"type": "string", "enum": values}, {"type": "null"}]}


def _nullable(*types: str) -> dict[str, Any]:
    return {"anyOf": [{"type": t} for t in types] + [{"type": "null"}]}


PLAN_JSON_SCHEMA: dict[str, Any] = {
    "name": "QueryPlan",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "visualization_type": {"type": "string", "enum": _VIZ_TYPES},
            "title": {"type": "string"},
            "query_interpretation": {"type": "string"},
            "filters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "drug_name": _nullable("string"),
                    "condition": _nullable("string"),
                    "sponsor": _nullable("string"),
                    "country": _nullable("string"),
                    "free_text": _nullable("string"),
                    "phase": _nullable_enum(_PHASE_ENUM),
                    "status": _nullable_enum(_STATUS_ENUM),
                    "start_year": _nullable("integer"),
                    "end_year": _nullable("integer"),
                },
                "required": [
                    "drug_name", "condition", "sponsor", "country",
                    "free_text", "phase", "status", "start_year", "end_year",
                ],
            },
            "aggregation": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "group_by": _nullable_enum(_GROUP_DIMS),
                    "series": _nullable_enum(_GROUP_DIMS),
                    "metric": {"type": "string", "enum": ["count"]},
                    "x_field": _nullable_enum(_NUMERIC_FIELDS),
                    "y_field": _nullable_enum(_NUMERIC_FIELDS),
                    "bin_count": {"type": "integer", "minimum": 2, "maximum": 50},
                    "network_kind": _nullable_enum(_NETWORK_KINDS),
                    "series_values": {
                        "anyOf": [
                            {"type": "array", "items": {"type": "string"},
                             "minItems": 2, "maxItems": 6},
                            {"type": "null"},
                        ]
                    },
                },
                "required": [
                    "group_by", "series", "metric", "x_field", "y_field",
                    "bin_count", "network_kind", "series_values",
                ],
            },
            "notes": _nullable("string"),
        },
        "required": [
            "visualization_type", "title", "query_interpretation",
            "filters", "aggregation", "notes",
        ],
    },
    "strict": True,
}


# ---- structured-field overrides ------------------------------------------

_OVERRIDABLE = (
    "drug_name", "condition", "sponsor", "country",
    "phase", "status", "start_year", "end_year",
)


def merge_user_overrides(plan: QueryPlan, req: AnalyzeRequest) -> QueryPlan:
    """User-provided structured fields override anything the LLM picked."""
    for k in _OVERRIDABLE:
        v = getattr(req, k)
        if v is not None:
            setattr(plan.filters, k, v)
    return plan


# ---- NL filter extraction (used by stub planner) -------------------------

_STATUS_KEYWORDS: list[tuple[str, str]] = [
    ("not yet recruiting", "NOT_YET_RECRUITING"),
    ("active not recruiting", "ACTIVE_NOT_RECRUITING"),
    ("active, not recruiting", "ACTIVE_NOT_RECRUITING"),
    ("recruiting", "RECRUITING"),
    ("completed", "COMPLETED"),
    ("terminated", "TERMINATED"),
    ("withdrawn", "WITHDRAWN"),
    ("suspended", "SUSPENDED"),
    ("enrolling by invitation", "ENROLLING_BY_INVITATION"),
]

_CONDITION_HEADS = (
    "cancer", "carcinoma", "lymphoma", "leukemia", "tumor", "tumour",
    "sarcoma", "neoplasm", "melanoma", "myeloma",
    "diabetes", "alzheimer", "parkinson", "covid", "covid-19",
    "asthma", "copd", "stroke", "depression", "anxiety", "schizophrenia",
    "arthritis", "psoriasis", "epilepsy", "obesity", "hypertension",
)
_CONDITION_HEADS_RE = "|".join(_CONDITION_HEADS)


def _extract_filters_from_query(req: AnalyzeRequest, q: str) -> tuple[
    Optional[str], Optional[str], Optional[str], Optional[int], Optional[int]
]:
    """Best-effort (status, condition, drug, start_year, end_year) inference."""
    status = req.status
    if not status:
        for kw, val in _STATUS_KEYWORDS:
            if kw in q:
                status = val
                break

    cond = req.condition
    if not cond:
        for alias, full in CONDITION_ALIASES.items():
            if re.search(rf"\b{re.escape(alias)}\b", q):
                cond = full
                break
    if not cond:
        m = re.search(rf"([\w\-]+(?:\s+[\w\-]+){{0,2}})\s+(?:{_CONDITION_HEADS_RE})\b", q)
        if m:
            head = (re.search(rf"\b({_CONDITION_HEADS_RE})\b", q) or [None, ""])
            cond = f"{m.group(1)} {head.group(1) if hasattr(head, 'group') else ''}".strip().title()
        else:
            for head in _CONDITION_HEADS:
                if re.search(rf"\b{head}\b", q):
                    cond = head.title()
                    break

    drug = req.drug_name
    if not drug:
        for alias in DRUG_ALIASES:
            if re.search(rf"\b{re.escape(alias)}\b", q):
                drug = DRUG_ALIASES[alias].title()
                break

    sy, ey = req.start_year, req.end_year
    if not sy and (m := re.search(r"\bsince\s+(\d{4})\b", q)):
        sy = int(m.group(1))
    if not sy and not ey and (m := re.search(
        r"\bbetween\s+(\d{4})\s+(?:and|to|-)\s+(\d{4})\b", q
    )):
        sy, ey = int(m.group(1)), int(m.group(2))
    if not ey and (m := re.search(r"\b(?:before|until|by)\s+(\d{4})\b", q)):
        ey = int(m.group(1))
    return status, cond, drug, sy, ey


# ---- routing tables (used by stub planner) -------------------------------

_DIM_CATEGORY_KEYWORDS: dict[str, str] = {
    "sponsor categor": "sponsor_class",
    "sponsor class": "sponsor_class",
    "intervention type": "intervention_type",
    "study type": "study_type",
    "sex eligibility": "sex",
    "phase distribution": "phase",
    "phases": "phase",
}
_DIM_AXIS_KEYWORDS: dict[str, str] = {
    "condition": "condition", "conditions": "condition",
    "disease": "condition", "diseases": "condition",
    "country": "country", "countries": "country",
    "phase": "phase", "phases": "phase",
    "year": "year", "years": "year",
    "sponsor": "lead_sponsor", "sponsors": "lead_sponsor",
}

_NET_SIGNALS = (
    "network", "co-occur", "co occur", "cooccur",
    "combination studies", "combination trials", "combinations", "combined with",
    "used together", "drugs together", "together in",
    "co-prescribed", "co prescribed",
)
_NET_DRUG_DRUG_SIGNALS = (
    "co-occur", "co occur", "cooccur", "combination", "combined", "together",
)

# (regex, group_by, title hint) — explicit "by <dim>" framings.
_BY_DIM_PATTERNS: list[tuple[str, str, str]] = [
    (r"\b(?:by|across|per)\s+phase(?:s)?\b|\bphase\s+distribution\b", "phase", "phase"),
    (
        r"\b(?:by|across|per)\s+(?:year|years)\b|\bper\s+year\b|"
        r"\beach\s+year\b|\bover\s+time\b|\bsince\s+\d{4}\b|\btrend\b",
        "year", "year",
    ),
    (
        r"\b(?:by|across|per)\s+countr(?:y|ies)\b|"
        r"\b(?:which|what)\s+countries\b|\bgeograph(?:y|ic)\b",
        "country", "country",
    ),
    (r"\b(?:by|across|per)\s+status(?:es)?\b|\bstatus\s+distribution\b",
     "overall_status", "status"),
    (r"\b(?:by|across|per)\s+sponsors?\b|\bmost\s+active\s+sponsors?\b|"
     r"\btop\s+sponsors?\b", "lead_sponsor", "sponsor"),
    (r"\b(?:by|across|per)\s+sponsor\s+class\b|\bindustry\s+vs\s+academic\b",
     "sponsor_class", "sponsor class"),
    (r"\b(?:by|across|per)\s+study\s+type\b|"
     r"\bobservational\s+vs\s+interventional\b", "study_type", "study type"),
    (r"\b(?:by|across|per)\s+(?:sex|gender)\b|\bsex\s+eligibility\b",
     "sex", "sex eligibility"),
    (r"\b(?:by|across|per)\s+intervention\s+type\b",
     "intervention_type", "intervention type"),
    (r"\b(?:by|across|per)\s+condition(?:s)?\b", "condition", "condition"),
]

# X-vs-Y comparison regex (multi-word entities, refusing stop-word tokens).
_COMPARE_STOP = r"(?:by|for|in|across|over|between|on|at|vs|versus|and)"
_COMPARE_ENTITY = (
    rf"[A-Za-z][\w\-]*(?:\s+(?!{_COMPARE_STOP}\b)[A-Za-z][\w\-]*){{0,3}}"
)
_COMPARE_PATTERN = re.compile(
    rf"(?:compare\s+)?({_COMPARE_ENTITY})\s+(?:vs\.?|versus|and)\s+({_COMPARE_ENTITY})"
)


# ---- stub planner --------------------------------------------------------

def _stub_plan(req: AnalyzeRequest) -> QueryPlan:
    """Heuristic keyword routing — used when STUB_LLM=1."""
    q = req.query.lower()
    inf_status, inf_cond, inf_drug, inf_sy, inf_ey = _extract_filters_from_query(req, q)
    drug = req.drug_name or inf_drug
    cond = req.condition or inf_cond
    status = req.status or inf_status

    def base_filters() -> Filters:
        return Filters(
            drug_name=drug, condition=cond, sponsor=req.sponsor,
            country=req.country, phase=req.phase, status=status,
            start_year=req.start_year or inf_sy,
            end_year=req.end_year or inf_ey,
        )

    def make(viz: Any, title: str, interp: str, agg: Aggregation,
             filters: Optional[Filters] = None) -> QueryPlan:
        return QueryPlan(
            visualization_type=viz, title=title, query_interpretation=interp,
            filters=filters or base_filters(), aggregation=agg,
        )

    # 1. Cross-dimension comparison ("compare X across Y").
    if "compare" in q:
        series_dim = next(
            (dim for kw, dim in _DIM_CATEGORY_KEYWORDS.items() if kw in q), None,
        )
        axis_dim = None
        if (m := re.search(r"\b(?:across|by|over|between)\s+([\w\-]+)", q)):
            axis_dim = _DIM_AXIS_KEYWORDS.get(m.group(1).lower())
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
        m = _COMPARE_PATTERN.search(q)
        names = [m.group(1).strip().title(), m.group(2).strip().title()] if m else []
        return make(
            "grouped_bar_chart",
            f"Phase distribution: {' vs '.join(names) or 'comparison'}",
            "Compare phase distribution between specified items.",
            Aggregation(
                group_by="phase", series="intervention_name",
                series_values=names or None,
            ),
            filters=Filters(
                # Drop drug_name from top-level filters; series values drive
                # the per-query fetches.
                condition=cond, sponsor=req.sponsor, country=req.country,
                status=status,
                start_year=req.start_year or inf_sy,
                end_year=req.end_year or inf_ey,
            ),
        )

    # 3. Relationship / network signals.
    if any(s in q for s in _NET_SIGNALS) or ("sponsor" in q and "drug" in q):
        if any(s in q for s in _NET_DRUG_DRUG_SIGNALS):
            kind = "drug_drug"
        elif "sponsor" in q and "drug" in q:
            kind = "sponsor_drug"
        elif "condition" in q or "disease" in q:
            kind = "drug_condition"
        else:
            kind = "sponsor_drug"
        return make(
            "network_graph",
            f"Network ({kind.replace('_', ' ↔ ')})",
            f"Build a {kind} network from matching trials.",
            Aggregation(network_kind=kind),
        )

    # 4. Explicit "by <dim>" framings.
    for pat, dim, hint in _BY_DIM_PATTERNS:
        if re.search(pat, q):
            viz = "time_series" if dim == "year" else "bar_chart"
            return make(
                viz,
                f"Trials by {hint}" + (f" ({drug or cond})" if drug or cond else ""),
                f"Distribute matching trials by {hint}.",
                Aggregation(group_by=dim),  # type: ignore[arg-type]
            )

    # 5. Filter keywords without explicit "by …" framing.
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
        k: v for k, v in {
            "drug_name": req.drug_name, "condition": req.condition,
            "sponsor": req.sponsor, "country": req.country,
            "phase": req.phase, "status": req.status,
            "start_year": req.start_year, "end_year": req.end_year,
        }.items() if v is not None
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
        filters=Filters(
            drug_name=req.drug_name, condition=req.condition,
            sponsor=req.sponsor, country=req.country,
            phase=req.phase, status=req.status,
            start_year=req.start_year, end_year=req.end_year,
        ),
        aggregation=agg,
        notes=f"fallback:{reason}",
    )


def plan_query(req: AnalyzeRequest) -> QueryPlan:
    if os.environ.get("STUB_LLM", "").lower() in ("1", "true", "yes"):
        try:
            plan = _stub_plan(req)
        except Exception as e:  # noqa: BLE001
            plan = _safe_default_plan(req, f"stub planner error: {e}")
    else:
        try:
            plan = _openai_plan(req)
        except Exception as e:  # noqa: BLE001
            try:
                plan = _openai_plan(req, repair_hint=str(e)[:400])
            except Exception as e2:  # noqa: BLE001
                plan = _safe_default_plan(req, f"LLM planner failed: {e2}")
    return merge_user_overrides(plan, req)
