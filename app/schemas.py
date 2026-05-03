from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import (
    BaseModel, ConfigDict, Field, ValidationInfo, field_validator,
    model_serializer, model_validator,
)

from .constants import (
    INTERVENTION_TYPE_SYNONYMS,
    INTERVENTION_TYPE_VALUES,
    PHASE_SYNONYMS,
    PHASE_VALUES,
    SEX_SYNONYMS,
    SEX_VALUES,
    SPONSOR_CLASS_SYNONYMS,
    SPONSOR_CLASS_VALUES,
    STATUS_VALUES,
    STUDY_TYPE_SYNONYMS,
    STUDY_TYPE_VALUES,
)


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
NetworkKind = Literal["sponsor_drug", "drug_condition", "drug_drug", "site_drug"]


# field name → (allowed values, synonym map). One row per enum-typed field.
_ENUM_NORMALIZERS: dict[str, tuple[set[str], dict[str, str]]] = {
    "phase": (PHASE_VALUES, PHASE_SYNONYMS),
    "status": (STATUS_VALUES, {}),
    "sponsor_class": (SPONSOR_CLASS_VALUES, SPONSOR_CLASS_SYNONYMS),
    "study_type": (STUDY_TYPE_VALUES, STUDY_TYPE_SYNONYMS),
    "sex": (SEX_VALUES, SEX_SYNONYMS),
    "intervention_type": (INTERVENTION_TYPE_VALUES, INTERVENTION_TYPE_SYNONYMS),
}


def _norm_enum_field(v: Any, field_name: str) -> Any:
    if v is None or not isinstance(v, str):
        return v
    s = v.strip()
    if not s:
        return None
    values, synonyms = _ENUM_NORMALIZERS[field_name]
    upper = s.upper().replace(" ", "_").replace("-", "_").replace(",", "")
    if upper in values:
        return upper
    if (canon := synonyms.get(s.lower())):
        return canon
    msg = f"{field_name} must be one of {sorted(values)} (got {v!r})."
    if field_name == "phase":
        msg += " Common synonyms like 'Phase 3', '3', or 'III' are also accepted."
    raise ValueError(msg)


class _PhaseStatusModel(BaseModel):
    """Base model that normalizes enum-typed string fields before validation."""

    @field_validator(*_ENUM_NORMALIZERS.keys(),
                     mode="before", check_fields=False)
    @classmethod
    def _v_enum(cls, v: Any, info: ValidationInfo) -> Any:
        return _norm_enum_field(v, info.field_name)


class AnalyzeRequest(_PhaseStatusModel):
    query: str = Field(..., min_length=1, description="Natural-language question about clinical trials.")
    drug_name: Optional[str] = None
    condition: Optional[str] = None
    sponsor: Optional[str] = None
    country: Optional[str] = None
    phase: Optional[str] = Field(None, description=f"One of: {sorted(PHASE_VALUES)}.")
    status: Optional[str] = Field(None, description=f"One of: {sorted(STATUS_VALUES)}.")
    sponsor_class: Optional[str] = Field(
        None, description=f"One of: {sorted(SPONSOR_CLASS_VALUES)}."
    )
    study_type: Optional[str] = Field(
        None, description=f"One of: {sorted(STUDY_TYPE_VALUES)}."
    )
    sex: Optional[str] = Field(None, description=f"One of: {sorted(SEX_VALUES)}.")
    intervention_type: Optional[str] = Field(
        None, description=f"One of: {sorted(INTERVENTION_TYPE_VALUES)}."
    )
    start_year: Optional[int] = Field(None, ge=1900, le=2100)
    end_year: Optional[int] = Field(None, ge=1900, le=2100)
    max_studies: int = Field(500, ge=1, le=2000)
    top_n: Optional[int] = Field(
        None, ge=1, le=200,
        description="If set, bar/grouped_bar/network output is clipped to the "
        "top N highest-weight buckets/edges.",
    )

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
    # Small-enum dims used by exact-count fan-out (one countTotal query per
    # bucket value). Not user-overridable on AnalyzeRequest — the planner
    # may set these, and the fan-out path sets them per-cell.
    sponsor_class: Optional[str] = None
    study_type: Optional[str] = None
    sex: Optional[str] = None
    intervention_type: Optional[str] = None

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
    bin_count: int = Field(10, ge=2, le=50)
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


class Channel(BaseModel):
    """Typed Vega-Lite-style channel descriptor.

    The fields are optional because x/y/series and network channels use
    different subsets. Serialization omits Nones so the emitted JSON stays
    byte-for-byte compatible in shape with the previous dict channels.
    """
    model_config = ConfigDict(extra="forbid")

    field: Optional[str] = None
    type: Optional[str] = None
    title: Optional[str] = None
    id: Optional[str] = None
    label: Optional[str] = None
    source: Optional[str] = None
    target: Optional[str] = None
    weight: Optional[str] = None

    @model_serializer
    def _serialize(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in self.__dict__.items()
            if value is not None
        }


class Encoding(BaseModel):
    """Vega-Lite-style channel descriptors. Per-spec subclasses below carry
    only the channels they actually use, so the response shape per `type`
    is enforced rather than implicit."""
    model_config = ConfigDict(extra="forbid")

    x: Optional[Channel] = None
    y: Optional[Channel] = None
    series: Optional[Channel] = None
    nodes: Optional[Channel] = None
    edges: Optional[Channel] = None


def _require_encoding(encoding: Encoding, *channels: str) -> None:
    missing = [ch for ch in channels if getattr(encoding, ch) is None]
    if missing:
        raise ValueError(f"encoding missing required channel(s): {', '.join(missing)}")


class _SpecBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    encoding: Encoding


class _XYSpecBase(_SpecBase):
    @model_validator(mode="after")
    def _v_xy_encoding(self):
        _require_encoding(self.encoding, "x", "y")
        return self


# ---- Typed datum models ---------------------------------------------------
# Every visualization datum carries a uniform "support envelope": the
# trial_count it represents, whether that count is sampled, the NCT IDs
# backing it, whether that ID list is exhaustive, and a small citation
# sample. Per-viz subclasses add what's specific to that chart type
# (numeric ranges for histograms, the trial id for scatter points, the
# source/target nodes for network edges, …). Dynamic dim-key fields
# (phase, country, year, sponsor, …) come through as model extras —
# their names are driven by `aggregation.group_by` and `series`, so we
# can't pin them at schema time without losing flexibility.

class _DatumBase(BaseModel):
    """Shared shape across every chart datum and every network edge."""
    model_config = ConfigDict(extra="allow")  # for dim-key fields
    trial_count: int
    sampled: bool = False
    supporting_nct_ids: list[str] = Field(default_factory=list)
    supporting_nct_ids_complete: bool = True
    citation_count: int = 0
    citations: list[Citation] = Field(default_factory=list)


class BarDatum(_DatumBase):
    """One bar in bar_chart. Dim key (phase / country / sponsor / …) is a
    model extra named after `aggregation.group_by`."""


class GroupedBarDatum(_DatumBase):
    """One cell in grouped_bar_chart. Carries both the group_by key and
    the series key as model extras."""


class TimeSeriesDatum(_DatumBase):
    """One temporal bucket. Carries year / quarter / month as a model
    extra named after `aggregation.group_by`."""


class HistogramDatum(_DatumBase):
    bin: str
    bin_start: float
    bin_end: float


class ScatterDatum(_DatumBase):
    """One trial as an (x, y) point. Trial_count is always 1; the chosen
    `aggregation.x_field` / `y_field` come through as model extras with
    the numeric values."""
    nct_id: Optional[str] = None


class NetworkNode(BaseModel):
    id: str
    label: str
    type: str  # sponsor | drug | condition | site


class NetworkEdge(_DatumBase):
    source: str
    target: str
    weight: int


# ---- Discriminated visualization specs -----------------------------------
# `type` is the discriminator; each subclass owns the right combination of
# data / nodes / edges so consumers don't have to defend against absent
# fields per visualization type. Pydantic builds a tagged union at the
# `AnalyzeResponse.visualization` boundary.

class BarChartSpec(_XYSpecBase):
    type: Literal["bar_chart"] = "bar_chart"
    data: list[BarDatum]


class GroupedBarChartSpec(_XYSpecBase):
    type: Literal["grouped_bar_chart"] = "grouped_bar_chart"
    data: list[GroupedBarDatum]

    @model_validator(mode="after")
    def _v_grouped_encoding(self):
        _require_encoding(self.encoding, "x", "y", "series")
        return self


class TimeSeriesSpec(_XYSpecBase):
    type: Literal["time_series"] = "time_series"
    data: list[TimeSeriesDatum]


class HistogramSpec(_XYSpecBase):
    type: Literal["histogram"] = "histogram"
    data: list[HistogramDatum]


class ScatterPlotSpec(_XYSpecBase):
    type: Literal["scatter_plot"] = "scatter_plot"
    data: list[ScatterDatum]


class NetworkGraphSpec(_SpecBase):
    type: Literal["network_graph"] = "network_graph"
    nodes: list[NetworkNode]
    edges: list[NetworkEdge]

    @model_validator(mode="after")
    def _v_network_encoding(self):
        _require_encoding(self.encoding, "nodes", "edges")
        return self


VisualizationSpec = Annotated[
    Union[
        BarChartSpec, GroupedBarChartSpec, TimeSeriesSpec,
        HistogramSpec, ScatterPlotSpec, NetworkGraphSpec,
    ],
    Field(discriminator="type"),
]


# Lookup used by the response assembler to instantiate the right subclass.
SPEC_BY_TYPE: dict[str, type[BaseModel]] = {
    "bar_chart": BarChartSpec,
    "grouped_bar_chart": GroupedBarChartSpec,
    "time_series": TimeSeriesSpec,
    "histogram": HistogramSpec,
    "scatter_plot": ScatterPlotSpec,
    "network_graph": NetworkGraphSpec,
}


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
