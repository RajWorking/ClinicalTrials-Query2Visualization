"""Shared test fixtures: study factory + filter-aware fake CT.gov client."""
from __future__ import annotations

from typing import Any

from app.planner import merge_user_overrides
from app.schemas import AnalyzeRequest, Aggregation, Filters, QueryPlan


def plan_query_for(plan: QueryPlan):
    """Return a test planner that always yields the provided plan."""
    def _plan(req: AnalyzeRequest) -> QueryPlan:
        return merge_user_overrides(plan.model_copy(deep=True), req)
    return _plan


def make_plan(
    visualization_type: str,
    *,
    group_by: str | None = None,
    series: str | None = None,
    series_values: list[str] | None = None,
    x_field: str | None = None,
    y_field: str | None = None,
    bin_count: int = 10,
    network_kind: str | None = None,
    filters: Filters | None = None,
    title: str | None = None,
) -> QueryPlan:
    return QueryPlan(
        visualization_type=visualization_type,  # type: ignore[arg-type]
        title=title or f"Test {visualization_type}",
        query_interpretation="Test plan.",
        filters=filters or Filters(),
        aggregation=Aggregation(
            group_by=group_by,  # type: ignore[arg-type]
            series=series,  # type: ignore[arg-type]
            series_values=series_values,
            x_field=x_field,  # type: ignore[arg-type]
            y_field=y_field,  # type: ignore[arg-type]
            bin_count=bin_count,
            network_kind=network_kind,  # type: ignore[arg-type]
        ),
    )


def bar_plan(group_by: str = "phase", *, filters: Filters | None = None) -> QueryPlan:
    return make_plan("bar_chart", group_by=group_by, filters=filters)


def time_series_plan(*, filters: Filters | None = None) -> QueryPlan:
    return make_plan("time_series", group_by="year", filters=filters)


def grouped_compare_plan(
    *,
    group_by: str = "phase",
    series_values: list[str] | None = None,
    filters: Filters | None = None,
) -> QueryPlan:
    return make_plan(
        "grouped_bar_chart",
        group_by=group_by,
        series="intervention_name",
        series_values=series_values or ["Pembro", "Atezo"],
        filters=filters,
    )


def network_plan(
    network_kind: str = "sponsor_drug", *, filters: Filters | None = None,
) -> QueryPlan:
    return make_plan("network_graph", network_kind=network_kind, filters=filters)


def histogram_plan(*, filters: Filters | None = None) -> QueryPlan:
    return make_plan(
        "histogram",
        x_field="enrollment_count",
        bin_count=12,
        filters=filters,
    )


def scatter_plan(*, filters: Filters | None = None) -> QueryPlan:
    return make_plan(
        "scatter_plot",
        x_field="duration_months",
        y_field="enrollment_count",
        filters=filters,
    )


_BASE_STUDY: dict[str, Any] = {
    "nct_id": "NCT00000001", "brief_title": "A title",
    "brief_summary": "Summary text", "phases": ["PHASE2"],
    "study_type": "INTERVENTIONAL", "sex": "ALL",
    "overall_status": "RECRUITING",
    "start_date": "2020-05-01", "completion_date": "2022-05-01",
    "enrollment_count": 100, "lead_sponsor": "Acme",
    "sponsor_class": "INDUSTRY", "conditions": ["Cancer"],
    "interventions": [{"name": "DrugA", "type": "DRUG"}],
    "intervention_names": ["DrugA"], "intervention_types": ["DRUG"],
    "locations": [{
        "facility": "Acme Research Site",
        "city": "New York",
        "state": "NY",
        "country": "United States",
    }],
    "countries": ["United States"],
}


def make_study(nct: str | None = None, **over: Any) -> dict:
    """Build a normalized study dict, with sensible defaults.

    Keeps `interventions` and `intervention_names` in sync when only one is
    supplied — many tests pass just one of the two.
    """
    s = {**_BASE_STUDY, **over}
    if nct is not None:
        s["nct_id"] = nct
    if "interventions" in over and "intervention_names" not in over:
        s["intervention_names"] = [i["name"] for i in s["interventions"]]
    if "intervention_names" in over and "interventions" not in over:
        s["interventions"] = [
            {"name": n, "type": "DRUG"} for n in s["intervention_names"]
        ]
    if "countries" in over and "locations" not in over:
        s["locations"] = [
            {"facility": None, "city": None, "state": None, "country": country}
            for country in s["countries"]
        ]
    return s


class FakeCTGovClient:
    """In-memory CT.gov client. Subclass and set `CORPUS` (or override
    `search_studies` for sampling-bias scenarios)."""

    CORPUS: list[dict] = []

    def __init__(self, *_a: Any, **_k: Any) -> None:
        pass

    async def __aenter__(self) -> "FakeCTGovClient":
        return self

    async def __aexit__(self, *_a: Any) -> bool:
        return False

    def _select(self, filters: Filters) -> list[dict]:
        sel = list(self.CORPUS)
        if filters.drug_name:
            d = filters.drug_name.lower()
            sel = [s for s in sel
                   if any(d in n.lower() for n in s["intervention_names"])]
        if filters.condition:
            c = filters.condition.lower()
            sel = [s for s in sel
                   if any(c in cd.lower() for cd in s["conditions"])]
        if filters.phase:
            sel = [s for s in sel if filters.phase in s["phases"]]
        if filters.status:
            sel = [s for s in sel if s["overall_status"] == filters.status]
        if filters.sponsor_class:
            sel = [s for s in sel if s.get("sponsor_class") == filters.sponsor_class]
        if filters.study_type:
            sel = [s for s in sel if s.get("study_type") == filters.study_type]
        if filters.sex:
            sel = [s for s in sel if s.get("sex") == filters.sex]
        if filters.intervention_type:
            sel = [s for s in sel
                   if filters.intervention_type
                   in (s.get("intervention_types") or [])]
        if filters.country:
            cn = filters.country.lower()
            sel = [s for s in sel
                   if any(cn in c.lower() for c in s["countries"])]
        if filters.start_year:
            sel = [s for s in sel
                   if s.get("start_date")
                   and int(s["start_date"][:4]) >= filters.start_year]
        if filters.end_year:
            sel = [s for s in sel
                   if s.get("start_date")
                   and int(s["start_date"][:4]) <= filters.end_year]
        return sel

    async def search_studies(
        self, filters: Filters, max_studies: int = 500, **_k: Any,
    ) -> tuple[list[dict], int]:
        sel = self._select(filters)
        return sel[:max_studies], len(sel)

    async def count_for_filters(self, filters: Filters) -> int:
        return len(self._select(filters))

    async def ids_for_filters(
        self, filters: Filters, max_ids: int = 5000, page_size: int = 1000,
    ) -> tuple[set[str], int, bool]:
        sel = self._select(filters)
        kept = sel[:max_ids]
        return {s["nct_id"] for s in kept}, len(sel), len(sel) > len(kept)


def make_fake_client_class(corpus: list[dict]) -> type[FakeCTGovClient]:
    """Subclass FakeCTGovClient with a fixed CORPUS — for monkeypatching."""
    return type("CorpusClient", (FakeCTGovClient,), {"CORPUS": corpus})


def make_fixed_corpus_client(corpus: list[dict]) -> type[FakeCTGovClient]:
    """Like `make_fake_client_class` but ignores filters and always returns
    the full corpus — for tests that exercise truncation / sampling caps."""
    class C(FakeCTGovClient):
        async def search_studies(self, _filters, max_studies=500, **_k):
            return corpus[:max_studies], len(corpus)

        async def count_for_filters(self, _filters):
            return len(corpus)

        async def ids_for_filters(self, _filters, max_ids=5000, page_size=1000):
            kept = corpus[:max_ids]
            return {s["nct_id"] for s in kept}, len(corpus), len(corpus) > len(kept)
    return C
