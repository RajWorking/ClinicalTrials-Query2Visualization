"""FastAPI app: POST /analyze, GET /healthz, GET / (demo UI)."""
from __future__ import annotations

import asyncio
import os
from datetime import date
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .aggregate import BUILDERS, build_grouped_bar
from .citations import cite_for
from .ctgov import CTGovClient, CTGovError
from .planner import plan_query
from .schemas import (
    AnalyzeRequest, AnalyzeResponse, Encoding, Filters, Meta, QueryPlan,
    VisualizationSpec,
)

load_dotenv()

app = FastAPI(title="ClinicalTrials Query → Visualization", version="0.1.0")

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.exception_handler(CTGovError)
async def ctgov_error_handler(_: Any, exc: CTGovError) -> JSONResponse:
    upstream = exc.status_code or 0
    status = 400 if 400 <= upstream < 500 else 502
    return JSONResponse(
        status_code=status,
        content={
            "error": "ClinicalTrials.gov upstream error",
            "detail": str(exc),
            "upstream_status": upstream or None,
        },
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def root() -> Any:
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "POST /analyze to use the API."}


# ---- helpers --------------------------------------------------------------

def _filters_with(filters: Filters, **overrides: Any) -> Filters:
    data = filters.model_dump()
    data.update({k: v for k, v in overrides.items() if v is not None})
    return Filters(**data)


# Map a series dimension to the Filters field that selects it.
_SERIES_TO_FILTER_FIELD = {
    "intervention_name": "drug_name",
    "condition": "condition",
    "lead_sponsor": "sponsor",
    "country": "country",
}


# Dimensions for which we fan out one tiny query per bucket value (exact
# global counts, no sampling). Each entry: (filter_field, [(value, label)]).
EXACT_COUNT_DIMS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "phase": ("phase", [
        ("PHASE1", "Phase 1"), ("PHASE2", "Phase 2"), ("PHASE3", "Phase 3"),
        ("PHASE4", "Phase 4"), ("EARLY_PHASE1", "Early Phase 1"),
        ("NA", "Not Applicable"),
    ]),
    "overall_status": ("status", [
        ("RECRUITING", "Recruiting"),
        ("NOT_YET_RECRUITING", "Not yet recruiting"),
        ("ACTIVE_NOT_RECRUITING", "Active, not recruiting"),
        ("COMPLETED", "Completed"), ("TERMINATED", "Terminated"),
        ("WITHDRAWN", "Withdrawn"), ("SUSPENDED", "Suspended"),
        ("ENROLLING_BY_INVITATION", "Enrolling by invitation"),
        ("UNKNOWN", "Unknown"),
    ]),
}


def _exact_datum(
    studies: list[dict], dim: str, label: str, total: int, **extras: Any,
) -> dict[str, Any]:
    """Datum shape for exact-count fan-out paths.

    `trial_count` is the API's totalCount (authoritative); the IDs are just
    the small sample fetched for citations, hence supporting_nct_ids_complete=False.
    """
    return {
        dim: label,
        "trial_count": total,
        "sampled": False,
        "citation_count": total,
        "supporting_nct_ids": [s["nct_id"] for s in studies if s.get("nct_id")],
        "supporting_nct_ids_complete": False,
        "citations": [c.model_dump() for c in cite_for(studies, dim, label)],
        **extras,
    }


# ---- exact-count fan-outs -------------------------------------------------

async def _exact_bucket_counts(
    client: CTGovClient,
    base_filters: Filters,
    filter_field: str,
    buckets: list[tuple[str, str]],
    group_by: str,
) -> tuple[list[dict[str, Any]], int, int]:
    """One search per bucket value in parallel.

    Returns (data, base_total, bucket_memberships):
      - base_total: distinct trials matching the unfiltered base
      - bucket_memberships: sum of bucket trial_counts

    Respects an existing same-dim filter — only iterates the matching bucket.
    """
    existing = getattr(base_filters, filter_field, None)
    if existing:
        buckets = [b for b in buckets if b[0] == existing]

    async def one(value: str, label: str) -> Optional[dict[str, Any]]:
        f = _filters_with(base_filters, **{filter_field: value})
        studies, total = await client.search_studies(f, max_studies=5, page_size=5)
        if total == 0:
            return None
        return _exact_datum(studies, group_by, label, total)

    bucket_task = asyncio.gather(*(one(v, l) for v, l in buckets))
    base_task = client.count_for_filters(base_filters)
    results, base_total = await asyncio.gather(bucket_task, base_task)
    data = [r for r in results if r is not None]
    data.sort(key=lambda d: -d["trial_count"])
    return data, base_total, sum(d["trial_count"] for d in data)


async def _exact_grouped_compare(
    client: CTGovClient,
    base_filters: Filters,
    series_field: str,
    series_dim: str,
    series_values: list[str],
    group_by: str,
) -> tuple[list[dict[str, Any]], int, int, dict[str, int]]:
    """Per (series_value × bucket_value) exact countTotal fan-out.

    Returns (rows, distinct_total, bucket_memberships, per_series_totals).
    distinct_total comes from the union of NCT IDs across compared series.
    """
    if group_by not in EXACT_COUNT_DIMS:
        raise ValueError(f"exact grouped compare not supported for {group_by}")
    bucket_field, buckets = EXACT_COUNT_DIMS[group_by]

    async def cell(sv: str, bvalue: str, blabel: str) -> Optional[dict[str, Any]]:
        f = _filters_with(base_filters, **{series_field: sv, bucket_field: bvalue})
        studies, total = await client.search_studies(f, max_studies=5, page_size=5)
        if total == 0:
            return None
        return _exact_datum(studies, group_by, blabel, total, **{series_dim: sv})

    cell_tasks = [cell(sv, bv, bl) for sv in series_values for bv, bl in buckets]
    id_tasks = [
        client.ids_for_filters(_filters_with(base_filters, **{series_field: sv}))
        for sv in series_values
    ]
    cell_results, *id_results = await asyncio.gather(
        asyncio.gather(*cell_tasks), *id_tasks,
    )
    rows = [r for r in cell_results if r is not None]
    rows.sort(key=lambda d: (d[group_by], d[series_dim]))

    per_series = {sv: 0 for sv in series_values}
    for r in rows:
        per_series[r[series_dim]] += r["trial_count"]
    bucket_memberships = sum(per_series.values())

    union: set[str] = set()
    truncated_any = False
    for ids, _t, truncated in id_results:
        union |= ids
        truncated_any = truncated_any or truncated
    distinct_total = len(union)
    if truncated_any:
        # Some series exceeded the ID-fetch cap; the union is a lower bound.
        distinct_total = max(distinct_total, max(per_series.values(), default=0))
    return rows, distinct_total, bucket_memberships, per_series


async def _exact_year_counts(
    client: CTGovClient, base_filters: Filters, start_year: int, end_year: int,
) -> tuple[list[dict[str, Any]], int]:
    """One countTotal request per year in parallel."""

    async def one(year: int) -> Optional[dict[str, Any]]:
        f = _filters_with(base_filters, start_year=year, end_year=year)
        studies, total = await client.search_studies(f, max_studies=5, page_size=5)
        if total == 0:
            return None
        return _exact_datum(studies, "year", str(year), total)

    results = await asyncio.gather(*(one(y) for y in range(start_year, end_year + 1)))
    data = [r for r in results if r is not None]
    data.sort(key=lambda d: d["year"])
    return data, sum(d["trial_count"] for d in data)


def _annotate_sampling(
    built: dict[str, Any], studies_used: int, total_studies: int, truncated: bool,
) -> None:
    """Mark each datum with `sampled` flag. No biased extrapolation."""
    sampled = bool(truncated and studies_used > 0 and total_studies > studies_used)
    for d in built.get("data") or []:
        d["sampled"] = sampled


# ---- /analyze -------------------------------------------------------------

@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    try:
        plan: QueryPlan = plan_query(req)
    except Exception as e:  # planner failure (very rare; planner has its own fallback)
        raise HTTPException(502, f"Query planning failed: {e}") from e

    warnings: list[str] = []
    per_series_totals: Optional[dict[str, int]] = None
    if plan.notes and plan.notes.startswith("fallback:"):
        warnings.append("Query understanding fell back to a safe default. " + plan.notes)

    async with CTGovClient() as client:
        # Path A0: per-year exact fan-out for time_series.
        if (plan.visualization_type == "time_series"
                and plan.aggregation.group_by == "year"):
            sy = plan.filters.start_year or 2010
            ey = plan.filters.end_year or date.today().year
            if ey < sy:
                ey = sy
            if ey - sy > 30:
                sy = ey - 30
                warnings.append(
                    "Year range narrowed to last 30 years for exact-count fan-out."
                )
            data, total = await _exact_year_counts(client, plan.filters, sy, ey)
            built = {
                "data": data,
                "encoding": {
                    "x": {"field": "year", "type": "ordinal"},
                    "y": {"field": "trial_count", "type": "quantitative"},
                },
            }
            studies_used = total
            truncated = False

        # Path A: exact bar-chart counts for known small enums.
        elif (plan.visualization_type == "bar_chart"
                and plan.aggregation.group_by in EXACT_COUNT_DIMS):
            filter_field, buckets = EXACT_COUNT_DIMS[plan.aggregation.group_by]
            data, total, bucket_memberships = await _exact_bucket_counts(
                client, plan.filters, filter_field, buckets, plan.aggregation.group_by,
            )
            built = {
                "data": data,
                "encoding": {
                    "x": {"field": plan.aggregation.group_by, "type": "nominal"},
                    "y": {"field": "trial_count", "type": "quantitative"},
                },
                "_bucket_memberships": bucket_memberships,
            }
            studies_used = total
            truncated = False

        # Path B: grouped_bar comparison.
        elif (plan.visualization_type == "grouped_bar_chart"
                and plan.aggregation.series and plan.aggregation.series_values):
            series_field = _SERIES_TO_FILTER_FIELD.get(plan.aggregation.series)
            if not series_field:
                raise HTTPException(
                    400,
                    f"grouped_bar_chart with series={plan.aggregation.series} "
                    "is not supported (no filter mapping).",
                )

            # Path B1: small-enum group_by → exact cell-by-cell fan-out.
            if plan.aggregation.group_by in EXACT_COUNT_DIMS:
                rows, total, bucket_memberships, per_series_totals = (
                    await _exact_grouped_compare(
                        client, plan.filters, series_field,
                        plan.aggregation.series, plan.aggregation.series_values,
                        plan.aggregation.group_by,
                    )
                )
                built = {
                    "data": rows,
                    "encoding": {
                        "x": {"field": plan.aggregation.group_by, "type": "nominal"},
                        "y": {"field": "trial_count", "type": "quantitative"},
                        "series": {"field": plan.aggregation.series, "type": "nominal"},
                    },
                    "_bucket_memberships": bucket_memberships,
                }
                studies_used = bucket_memberships
                truncated = False
            # Path B2: high-cardinality group_by → per-series fetch + local agg.
            else:
                results = await asyncio.gather(*(
                    client.search_studies(
                        _filters_with(plan.filters, **{series_field: sv}),
                        max_studies=req.max_studies,
                    )
                    for sv in plan.aggregation.series_values
                ))
                truncated = False
                studies_by_series: dict[str, list[dict]] = {}
                per_series_totals = {}
                for sv, (studies, t) in zip(plan.aggregation.series_values, results):
                    studies_by_series[sv] = studies
                    per_series_totals[sv] = t
                    if len(studies) >= req.max_studies and t > len(studies):
                        truncated = True
                # Local aggregation may double-count trials present in
                # multiple series (combination studies); per-series totals
                # remain accurate because they're independent counts.
                total = sum(per_series_totals.values())
                studies_used = sum(len(s) for s in studies_by_series.values())
                built = build_grouped_bar(studies_by_series, plan)
                _annotate_sampling(built, studies_used, total, truncated)
                if _has_series_overlap(studies_by_series, plan.aggregation):
                    warnings.append(
                        "Some trials appear in multiple comparison groups "
                        "(combination studies). Per-series totals are "
                        "independent counts; the overall total may "
                        "double-count overlap."
                    )

        # Path C: generic sample-then-aggregate.
        else:
            if plan.visualization_type == "grouped_bar_chart":
                warnings.append(
                    "grouped_bar_chart requested without series_values; "
                    "falling back to bar_chart."
                )
                plan.visualization_type = "bar_chart"

            # Paginate everything when the matched total fits below the cap;
            # otherwise honor max_studies and report sampled.
            cap = int(os.environ.get("CTGOV_PAGINATE_CAP", "2000"))
            base_total = await client.count_for_filters(plan.filters)
            target = max(req.max_studies, min(base_total, cap))
            studies, total = await client.search_studies(plan.filters, max_studies=target)
            studies_used = len(studies)
            truncated = studies_used < total
            built = BUILDERS[plan.visualization_type](studies, plan)
            _annotate_sampling(built, studies_used, total, truncated)

    if truncated and plan.visualization_type != "network_graph":
        warnings.append(
            f"Result is sampled: only the first {studies_used} of "
            f"{total} matching trials were scanned. Counts on each datum are "
            "lower bounds; we deliberately do NOT extrapolate, because "
            "pagination order is not random."
        )

    nm = built.get("_network_meta")
    if nm:
        if nm["edges_total"] > nm["edges_returned"]:
            warnings.append(
                f"Network was truncated to the {nm['edges_returned']} "
                f"highest-weight edges out of {nm['edges_total']} total. "
                "Lower-weight relationships are omitted for readability."
            )
        if nm["nodes_total"] > nm["nodes_returned"]:
            warnings.append(
                f"{nm['nodes_total'] - nm['nodes_returned']} nodes were "
                "dropped because their only edges were truncated."
            )

    return _build_response(
        plan=plan, built=built, total=total, studies_used=studies_used,
        truncated=truncated, warnings=warnings,
        per_series_totals=per_series_totals,
    )


def _has_series_overlap(
    studies_by_series: dict[str, list[dict]], agg: Any,
) -> bool:
    """True if any trial appears under multiple drug-name series_values."""
    if agg.series != "intervention_name":
        return False
    values_lower = [v.lower() for v in agg.series_values]
    for sv1 in agg.series_values:
        for s in studies_by_series.get(sv1, []):
            names_lower = [n.lower() for n in (s.get("intervention_names") or [])]
            for v_lower in values_lower:
                if v_lower != sv1.lower() and v_lower in names_lower:
                    return True
    return False


def _build_response(
    *,
    plan: QueryPlan,
    built: dict[str, Any],
    total: int,
    studies_used: int,
    truncated: bool,
    warnings: list[str],
    per_series_totals: Optional[dict[str, int]],
) -> AnalyzeResponse:
    spec_kwargs: dict[str, Any] = {
        "type": plan.visualization_type,
        "title": plan.title + (" (sampled)" if truncated else ""),
        "encoding": Encoding(**built["encoding"]),
    }
    for k in ("data", "nodes", "edges"):
        if k in built:
            spec_kwargs[k] = built[k]

    meta_kwargs: dict[str, Any] = dict(
        filters_applied=plan.filters.model_dump(exclude_none=True),
        query_interpretation=plan.query_interpretation,
        total_studies_matched=total,
        studies_used=studies_used,
        truncated=truncated,
        warnings=warnings,
    )
    if per_series_totals is not None:
        meta_kwargs["per_series_totals"] = per_series_totals
    if "_network_meta" in built:
        meta_kwargs.update(built["_network_meta"])
    if "_bucket_memberships" in built:
        meta_kwargs["bucket_memberships"] = built["_bucket_memberships"]

    return AnalyzeResponse(
        visualization=VisualizationSpec(**spec_kwargs),
        meta=Meta(**meta_kwargs),
    )
