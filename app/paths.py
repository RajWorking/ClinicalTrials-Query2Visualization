"""Analyze path selection and execution strategies."""
from __future__ import annotations

import asyncio
import os
from datetime import date
from typing import Any, NamedTuple, Optional

from fastapi import HTTPException

from .aggregate import BUILDERS, build_grouped_bar, build_grouped_bar_cross
from .constants import EXACT_COUNT_DIMS
from .ctgov import CTGovClient
from .exact_counts import (
    HIGH_CARDINALITY_FANOUT_DIMS,
    _exact_bucket_counts,
    _exact_grouped_compare,
    _exact_high_cardinality_counts,
    _exact_year_counts,
    _filters_with,
)
from .schemas import AnalyzeRequest, Filters, QueryPlan


_SERIES_TO_FILTER_FIELD = {
    "intervention_name": "drug_name",
    "condition": "condition",
    "lead_sponsor": "sponsor",
    "country": "country",
}


class PathOutcome(NamedTuple):
    built: dict[str, Any]
    total: int
    studies_used: int
    truncated: bool
    per_series_totals: Optional[dict[str, int]] = None
    warnings: tuple[str, ...] = ()


def finalize_plan(plan: QueryPlan) -> tuple[QueryPlan, list[str]]:
    warnings: list[str] = []
    if (plan.visualization_type == "time_series"
            and plan.aggregation.group_by == "year"):
        user_sy, user_ey = plan.filters.start_year, plan.filters.end_year
        sy = user_sy or 2010
        ey = user_ey or date.today().year
        if ey < sy:
            ey = sy
        if ey - sy > 30:
            sy = ey - 30
            warnings.append(
                "Year range narrowed to last 30 years for exact-count fan-out."
            )
        if user_sy is None or user_ey is None:
            defaulted = []
            if user_sy is None:
                defaulted.append(f"start_year={sy}")
            if user_ey is None:
                defaulted.append(f"end_year={ey}")
            warnings.append(
                "Time-range defaults applied for the per-year fan-out: "
                + ", ".join(defaulted)
                + ". Pass explicit start_year/end_year to override."
            )
        plan.filters.start_year = sy
        plan.filters.end_year = ey
    if (plan.visualization_type == "grouped_bar_chart"
            and not plan.aggregation.series_values
            and not plan.aggregation.series):
        warnings.append(
            "grouped_bar_chart requested without series_values or series "
            "dimension; falling back to bar_chart."
        )
        plan.visualization_type = "bar_chart"  # type: ignore[assignment]
    return plan, warnings


def _annotate_sampling(
    built: dict[str, Any], studies_used: int, total_studies: int, truncated: bool,
) -> None:
    sampled = bool(truncated and studies_used > 0 and total_studies > studies_used)
    for datum in built.get("data") or []:
        datum["sampled"] = sampled
    for edge in built.get("edges") or []:
        edge["sampled"] = sampled


def _chart_built(
    data: list[dict[str, Any]],
    x_field: str,
    *,
    x_type: str = "nominal",
    series_field: Optional[str] = None,
    extras: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    encoding: dict[str, Any] = {
        "x": {"field": x_field, "type": x_type},
        "y": {"field": "trial_count", "type": "quantitative"},
    }
    if series_field:
        encoding["series"] = {"field": series_field, "type": "nominal"}
    built: dict[str, Any] = {"data": data, "encoding": encoding}
    if extras:
        built.update(extras)
    return built


async def _fetch_with_cap(
    client: CTGovClient, filters: Filters, min_studies: int, cap: int,
) -> tuple[list[dict], int, int, bool]:
    base_total = await client.count_for_filters(filters)
    target = max(min_studies, min(base_total, cap))
    studies, total = await client.search_studies(filters, max_studies=target)
    studies_used = len(studies)
    return studies, total, studies_used, studies_used < total


async def _path_year_fanout(
    client: CTGovClient, plan: QueryPlan, req: AnalyzeRequest,
) -> PathOutcome:
    sy, ey = plan.filters.start_year, plan.filters.end_year
    assert sy is not None and ey is not None
    data, total = await _exact_year_counts(client, plan.filters, sy, ey)
    built = _chart_built(data, "year", x_type="ordinal")
    return PathOutcome(built, total, total, False)


async def _path_exact_bar(
    client: CTGovClient, plan: QueryPlan, req: AnalyzeRequest,
) -> PathOutcome:
    filter_field, buckets = EXACT_COUNT_DIMS[plan.aggregation.group_by]
    data, total, bucket_memberships = await _exact_bucket_counts(
        client, plan.filters, filter_field, buckets, plan.aggregation.group_by,
    )
    built = _chart_built(
        data, plan.aggregation.group_by,
        extras={"_bucket_memberships": bucket_memberships},
    )
    return PathOutcome(built, total, total, False)


async def _path_high_card_bar(
    client: CTGovClient, plan: QueryPlan, req: AnalyzeRequest,
) -> PathOutcome:
    filter_field = HIGH_CARDINALITY_FANOUT_DIMS[plan.aggregation.group_by]
    sample_cap = int(os.environ.get("CTGOV_HIGH_CARD_SCAN_CAP", "10000"))
    sample_size = max(req.max_studies, sample_cap)
    candidate_cap = int(os.environ.get("CTGOV_HIGH_CARD_CANDIDATE_CAP", "100"))
    data, total, candidates_sampled = await _exact_high_cardinality_counts(
        client, plan.filters, filter_field,
        plan.aggregation.group_by, sample_size=sample_size,
        candidate_cap=candidate_cap,
    )
    warnings: list[str] = []
    if candidates_sampled:
        warnings.append(
            f"Top-N candidates were discovered from a sample window of up "
            f"to {sample_size} trials (full result set: {total}). Trial "
            "counts on each shown bucket are *exact* via per-candidate "
            "countTotal queries, but values that appear *only* in the "
            "unsampled portion of the result set are missing from the "
            "candidate list."
        )
    return PathOutcome(
        _chart_built(data, plan.aggregation.group_by),
        total, total, False, warnings=tuple(warnings),
    )

async def _path_grouped_bar_cross(
    client: CTGovClient, plan: QueryPlan, req: AnalyzeRequest,
) -> PathOutcome:
    cap = int(os.environ.get("CTGOV_PAGINATE_CAP", "2000"))
    studies, total, studies_used, truncated = await _fetch_with_cap(
        client, plan.filters, req.max_studies, cap,
    )
    built = build_grouped_bar_cross(studies, plan)
    _annotate_sampling(built, studies_used, total, truncated)
    return PathOutcome(built, total, studies_used, truncated)


async def _path_grouped_compare_exact(
    client: CTGovClient, plan: QueryPlan, req: AnalyzeRequest,
    series_field: str,
) -> PathOutcome:
    rows, total, bucket_memberships, per_series_totals, lower_bound = (
        await _exact_grouped_compare(
            client, plan.filters, series_field,
            plan.aggregation.series, plan.aggregation.series_values,
            plan.aggregation.group_by,
        )
    )
    warnings: list[str] = []
    if lower_bound:
        warnings.append(
            "One or more series exceeded the ID-fetch cap. Per-series and "
            "per-cell counts remain exact, but total_studies_matched "
            "(distinct trials) is a lower bound — the union of NCT IDs "
            "could not be fully enumerated."
        )
    built = _chart_built(
        rows, plan.aggregation.group_by,
        series_field=plan.aggregation.series,
        extras={"_bucket_memberships": bucket_memberships},
    )
    return PathOutcome(
        built, total, bucket_memberships, False,
        per_series_totals=per_series_totals, warnings=tuple(warnings),
    )


async def _path_grouped_compare_sampled(
    client: CTGovClient, plan: QueryPlan, req: AnalyzeRequest,
    series_field: str,
) -> PathOutcome:
    studies_by_series, per_series_totals, truncated = await _fetch_series_studies(
        client, plan.filters, series_field,
        plan.aggregation.series_values, req.max_studies,
    )
    total = sum(per_series_totals.values())
    studies_used = sum(len(studies) for studies in studies_by_series.values())
    built = build_grouped_bar(studies_by_series, plan)
    _annotate_sampling(built, studies_used, total, truncated)
    warnings: list[str] = []
    if _has_series_overlap(studies_by_series, plan.aggregation):
        warnings.append(
            "Some trials appear in multiple comparison groups "
            "(combination studies). Per-series totals are independent "
            "counts; the overall total may double-count overlap."
        )
    return PathOutcome(
        built, total, studies_used, truncated,
        per_series_totals=per_series_totals, warnings=tuple(warnings),
    )


async def _fetch_series_studies(
    client: CTGovClient,
    filters: Filters,
    series_field: str,
    series_values: list[str],
    max_studies: int,
) -> tuple[dict[str, list[dict]], dict[str, int], bool]:
    results = await asyncio.gather(*(
        client.search_studies(
            _filters_with(filters, **{series_field: sv}),
            max_studies=max_studies,
        )
        for sv in series_values
    ))
    truncated = False
    studies_by_series: dict[str, list[dict]] = {}
    per_series_totals: dict[str, int] = {}
    for sv, (studies, total) in zip(series_values, results):
        studies_by_series[sv] = studies
        per_series_totals[sv] = total
        if len(studies) >= max_studies and total > len(studies):
            truncated = True
    return studies_by_series, per_series_totals, truncated


async def _path_generic(
    client: CTGovClient, plan: QueryPlan, req: AnalyzeRequest,
) -> PathOutcome:
    if plan.visualization_type in ("histogram", "scatter_plot"):
        cap = int(os.environ.get("CTGOV_NUMERIC_SCAN_CAP", "10000"))
    elif plan.visualization_type == "network_graph":
        cap = int(os.environ.get("CTGOV_NETWORK_SCAN_CAP", "5000"))
    else:
        cap = int(os.environ.get("CTGOV_PAGINATE_CAP", "2000"))
    studies, total, studies_used, truncated = await _fetch_with_cap(
        client, plan.filters, req.max_studies, cap,
    )
    built = BUILDERS[plan.visualization_type](studies, plan)
    _annotate_sampling(built, studies_used, total, truncated)
    return PathOutcome(built, total, studies_used, truncated)


def _series_field_for(plan: QueryPlan) -> dict[str, Any]:
    series_field = _SERIES_TO_FILTER_FIELD.get(plan.aggregation.series or "")
    if not series_field:
        raise HTTPException(
            400,
            f"grouped_bar_chart with series={plan.aggregation.series} "
            "is not supported (no filter mapping).",
        )
    return {"series_field": series_field}


_PATH_RULES: list[tuple[Any, Any, Any]] = [
    (
        lambda p: (p.visualization_type == "time_series"
                   and p.aggregation.group_by == "year"),
        _path_year_fanout, lambda _p: {},
    ),
    (
        lambda p: (p.visualization_type == "bar_chart"
                   and p.aggregation.group_by in EXACT_COUNT_DIMS),
        _path_exact_bar, lambda _p: {},
    ),
    (
        lambda p: (p.visualization_type == "bar_chart"
                   and p.aggregation.group_by in HIGH_CARDINALITY_FANOUT_DIMS),
        _path_high_card_bar, lambda _p: {},
    ),
    (
        lambda p: (p.visualization_type == "grouped_bar_chart"
                   and p.aggregation.series and p.aggregation.group_by
                   and not p.aggregation.series_values),
        _path_grouped_bar_cross, lambda _p: {},
    ),
    (
        lambda p: (p.visualization_type == "grouped_bar_chart"
                   and p.aggregation.series and p.aggregation.series_values
                   and p.aggregation.group_by in EXACT_COUNT_DIMS),
        _path_grouped_compare_exact, _series_field_for,
    ),
    (
        lambda p: (p.visualization_type == "grouped_bar_chart"
                   and p.aggregation.series and p.aggregation.series_values),
        _path_grouped_compare_sampled, _series_field_for,
    ),
]


def select_path(plan: QueryPlan) -> tuple[Any, dict[str, Any]]:
    for predicate, handler, extras_fn in _PATH_RULES:
        if predicate(plan):
            return handler, extras_fn(plan)
    return _path_generic, {}


def _has_series_overlap(
    studies_by_series: dict[str, list[dict]], agg: Any,
) -> bool:
    if agg.series != "intervention_name":
        return False
    values_lower = [v.lower() for v in agg.series_values]
    for series_value in agg.series_values:
        for study in studies_by_series.get(series_value, []):
            names_lower = [
                n.lower() for n in (study.get("intervention_names") or [])
            ]
            for value_lower in values_lower:
                if value_lower != series_value.lower() and value_lower in names_lower:
                    return True
    return False
