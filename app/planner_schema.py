"""OpenAI structured-output schema and planner prompt."""
from __future__ import annotations

from typing import Any

from .constants import (
    GROUP_DIMS,
    INTERVENTION_TYPE_ENUM,
    NETWORK_KINDS,
    NUMERIC_FIELDS,
    PHASE_ENUM,
    PLANNER_STATUS_ENUM,
    SEX_ENUM,
    SPONSOR_CLASS_ENUM,
    STUDY_TYPE_ENUM,
    VIZ_TYPES,
)


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
  - network_graph: relationships (sponsor_drug | drug_condition | drug_drug | site_drug)

For grouped_bar_chart with comparisons (e.g. "Drug A vs Drug B"), set
aggregation.series = "intervention_name" and series_values = ["A", "B"];
leave drug_name unset on top-level filters (per-query fetches drive the comparison).

If the user already supplied a structured field (drug_name, condition, etc.)
the request layer overrides yours, so don't worry about re-extracting it.
Use filter fields when the query contains clear constraints such as
industry-sponsored (sponsor_class=INDUSTRY), observational
(study_type=OBSERVATIONAL), female-only (sex=FEMALE), or drug intervention
(intervention_type=DRUG).

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

Q: "Show trial sites and drugs for melanoma."
→ network_graph, network_kind=site_drug, condition="Melanoma"

Q: "Drugs that are often combined in cancer studies."
→ network_graph, network_kind=drug_drug, condition="Cancer"

Q: "Distribution of enrollment sizes for cardiology trials."
→ histogram, x_field=enrollment_count, bin_count=12, condition="Cardiology"

Q: "Does enrollment correlate with trial duration for industry-sponsored trials?"
→ scatter_plot, x_field=duration_months, y_field=enrollment_count
"""


def _nullable_enum(values: tuple[str, ...]) -> dict[str, Any]:
    return {"anyOf": [{"type": "string", "enum": values}, {"type": "null"}]}


def _nullable(*types: str) -> dict[str, Any]:
    return {"anyOf": [{"type": t} for t in types] + [{"type": "null"}]}


PLAN_JSON_SCHEMA: dict[str, Any] = {
    "name": "QueryPlan",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "visualization_type": {"type": "string", "enum": VIZ_TYPES},
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
                    "phase": _nullable_enum(PHASE_ENUM),
                    "status": _nullable_enum(PLANNER_STATUS_ENUM),
                    "sponsor_class": _nullable_enum(SPONSOR_CLASS_ENUM),
                    "study_type": _nullable_enum(STUDY_TYPE_ENUM),
                    "sex": _nullable_enum(SEX_ENUM),
                    "intervention_type": _nullable_enum(INTERVENTION_TYPE_ENUM),
                    "start_year": _nullable("integer"),
                    "end_year": _nullable("integer"),
                },
                "required": [
                    "drug_name", "condition", "sponsor", "country",
                    "free_text", "phase", "status", "sponsor_class",
                    "study_type", "sex", "intervention_type",
                    "start_year", "end_year",
                ],
            },
            "aggregation": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "group_by": _nullable_enum(GROUP_DIMS),
                    "series": _nullable_enum(GROUP_DIMS),
                    "metric": {"type": "string", "enum": ["count"]},
                    "x_field": _nullable_enum(NUMERIC_FIELDS),
                    "y_field": _nullable_enum(NUMERIC_FIELDS),
                    "bin_count": {"type": "integer", "minimum": 2, "maximum": 50},
                    "network_kind": _nullable_enum(NETWORK_KINDS),
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
