from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


VizType = Literal[
    "bar_chart", "grouped_bar_chart", "time_series",
    "scatter_plot", "histogram", "network_graph",
]

GroupByDim = Literal[
    "phase", "overall_status", "study_type", "sex",
    "lead_sponsor", "sponsor_class", "country",
    "intervention_type", "intervention_name", "condition",
    "year", "quarter", "month",
]

NumericField = Literal["enrollment_count", "duration_months", "start_year"]
NetworkKind = Literal["sponsor_drug", "drug_condition", "drug_drug"]


PHASE_VALUES = {"PHASE1", "PHASE2", "PHASE3", "PHASE4", "EARLY_PHASE1", "NA"}

PHASE_SYNONYMS = {
    "1": "PHASE1", "i": "PHASE1", "phase 1": "PHASE1", "phase1": "PHASE1", "phase_1": "PHASE1",
    "2": "PHASE2", "ii": "PHASE2", "phase 2": "PHASE2", "phase2": "PHASE2", "phase_2": "PHASE2",
    "3": "PHASE3", "iii": "PHASE3", "phase 3": "PHASE3", "phase3": "PHASE3", "phase_3": "PHASE3",
    "4": "PHASE4", "iv": "PHASE4", "phase 4": "PHASE4", "phase4": "PHASE4", "phase_4": "PHASE4",
    "early phase 1": "EARLY_PHASE1", "early_phase_1": "EARLY_PHASE1",
    "early phase i": "EARLY_PHASE1", "early phase1": "EARLY_PHASE1",
    "n/a": "NA", "not applicable": "NA", "none": "NA",
}

STATUS_VALUES = {
    "RECRUITING", "NOT_YET_RECRUITING", "ACTIVE_NOT_RECRUITING", "COMPLETED",
    "TERMINATED", "WITHDRAWN", "SUSPENDED", "ENROLLING_BY_INVITATION",
    "UNKNOWN", "AVAILABLE", "NO_LONGER_AVAILABLE",
    "TEMPORARILY_NOT_AVAILABLE", "APPROVED_FOR_MARKETING", "WITHHELD",
}


def _norm_phase(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = v.strip()
    if not s:
        return None
    upper = s.upper().replace("-", "_")
    if upper in PHASE_VALUES:
        return upper
    if (canon := PHASE_SYNONYMS.get(s.lower())):
        return canon
    raise ValueError(
        f"phase must be one of {sorted(PHASE_VALUES)} (got {v!r}). "
        "Common synonyms like 'Phase 3', '3', or 'III' are also accepted."
    )


def _norm_status(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = v.strip()
    if not s:
        return None
    upper = s.upper().replace(" ", "_").replace("-", "_").replace(",", "")
    if upper in STATUS_VALUES:
        return upper
    raise ValueError(f"status must be one of {sorted(STATUS_VALUES)} (got {v!r}).")


class _PhaseStatusModel(BaseModel):
    """Base model that normalizes `phase` / `status` strings before validation."""

    @field_validator("phase", mode="before", check_fields=False)
    @classmethod
    def _v_phase(cls, v: Any) -> Any:
        return _norm_phase(v) if isinstance(v, str) or v is None else v

    @field_validator("status", mode="before", check_fields=False)
    @classmethod
    def _v_status(cls, v: Any) -> Any:
        return _norm_status(v) if isinstance(v, str) or v is None else v


class AnalyzeRequest(_PhaseStatusModel):
    query: str = Field(..., min_length=1, description="Natural-language question about clinical trials.")
    drug_name: Optional[str] = None
    condition: Optional[str] = None
    sponsor: Optional[str] = None
    country: Optional[str] = None
    phase: Optional[str] = Field(None, description=f"One of: {sorted(PHASE_VALUES)}.")
    status: Optional[str] = Field(None, description=f"One of: {sorted(STATUS_VALUES)}.")
    start_year: Optional[int] = Field(None, ge=1900, le=2100)
    end_year: Optional[int] = Field(None, ge=1900, le=2100)
    max_studies: int = Field(500, ge=1, le=2000)

    @model_validator(mode="after")
    def _v_year_range(self) -> "AnalyzeRequest":
        if (self.start_year is not None and self.end_year is not None
                and self.start_year > self.end_year):
            raise ValueError(
                f"start_year ({self.start_year}) must be ≤ end_year ({self.end_year})"
            )
        return self


class Filters(_PhaseStatusModel):
    drug_name: Optional[str] = None
    condition: Optional[str] = None
    sponsor: Optional[str] = None
    country: Optional[str] = None
    free_text: Optional[str] = None
    phase: Optional[str] = None
    status: Optional[str] = None
    start_year: Optional[int] = Field(None, ge=1900, le=2100)
    end_year: Optional[int] = Field(None, ge=1900, le=2100)

    @model_validator(mode="after")
    def _v_year_range(self) -> "Filters":
        # Silently auto-correct planner output; user input is guarded by the
        # request-level validator above.
        if (self.start_year is not None and self.end_year is not None
                and self.start_year > self.end_year):
            self.start_year, self.end_year = self.end_year, self.start_year
        return self


class Aggregation(BaseModel):
    group_by: Optional[GroupByDim] = None
    series: Optional[GroupByDim] = Field(None, description="Secondary grouping for grouped_bar.")
    metric: Literal["count"] = "count"
    x_field: Optional[NumericField] = None
    y_field: Optional[NumericField] = None
    bin_count: int = 10
    network_kind: Optional[NetworkKind] = None
    series_values: Optional[list[str]] = Field(
        None, description="Values to compare on the series axis (grouped_bar)."
    )


class QueryPlan(BaseModel):
    visualization_type: VizType
    title: str
    query_interpretation: str
    filters: Filters = Field(default_factory=Filters)
    aggregation: Aggregation = Field(default_factory=Aggregation)
    notes: Optional[str] = None


class Citation(BaseModel):
    nct_id: str
    excerpt: str
    source_field: Optional[str] = None
    url: Optional[str] = None


class Encoding(BaseModel):
    x: Optional[dict[str, Any]] = None
    y: Optional[dict[str, Any]] = None
    series: Optional[dict[str, Any]] = None
    nodes: Optional[dict[str, Any]] = None
    edges: Optional[dict[str, Any]] = None


class VisualizationSpec(BaseModel):
    type: VizType
    title: str
    encoding: Encoding
    data: Optional[list[dict[str, Any]]] = None
    nodes: Optional[list[dict[str, Any]]] = None
    edges: Optional[list[dict[str, Any]]] = None


class Meta(BaseModel):
    filters_applied: dict[str, Any]
    query_interpretation: str
    source: str = "clinicaltrials.gov"
    # Distinct trials matching filters; bucket_memberships sums bucket counts
    # (≥ total when the dim is multi-valued, e.g. phase).
    total_studies_matched: Optional[int] = None
    bucket_memberships: Optional[int] = None
    studies_used: int = 0
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)
    per_series_totals: Optional[dict[str, int]] = None
    nodes_returned: Optional[int] = None
    nodes_total: Optional[int] = None
    edges_returned: Optional[int] = None
    edges_total: Optional[int] = None
    min_edge_weight: Optional[int] = None


class AnalyzeResponse(BaseModel):
    visualization: VisualizationSpec
    meta: Meta
