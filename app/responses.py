"""Analyze response assembly and post-processing."""
from __future__ import annotations

import os
from typing import Any, Optional

from .paths import PathOutcome
from .schemas import (
    AnalyzeRequest, AnalyzeResponse, Encoding, Meta, QueryPlan, SPEC_BY_TYPE,
)


def build_analyze_response(
    *,
    req: AnalyzeRequest,
    plan: QueryPlan,
    outcome: PathOutcome,
    warnings: list[str],
) -> AnalyzeResponse:
    built = outcome.built
    total = outcome.total
    studies_used = outcome.studies_used
    truncated = outcome.truncated
    warnings.extend(outcome.warnings)

    if truncated and plan.visualization_type != "network_graph":
        warnings.append(
            f"Result is sampled: only the first {studies_used} of "
            f"{total} matching trials were scanned. Counts on each datum are "
            "lower bounds; we deliberately do NOT extrapolate, because "
            "pagination order is not random."
        )
    if truncated and plan.visualization_type == "network_graph":
        warnings.append(
            f"Network was built from a sampled study set: only the first "
            f"{studies_used} of {total} matching trials were scanned. Edge "
            "weights are lower bounds for the relationship strength, and "
            "relationships present only in the unsampled portion are missing "
            "entirely. Each edge carries `sampled: true` to flag this."
        )

    _apply_top_n(req, plan, built)
    _apply_scatter_point_cap(plan, built, warnings)
    _append_network_truncation_warnings(built, warnings)

    return _build_response(
        plan=plan, built=built, total=total, studies_used=studies_used,
        truncated=truncated, warnings=warnings,
        per_series_totals=outcome.per_series_totals,
    )


def _apply_top_n(
    req: AnalyzeRequest, plan: QueryPlan, built: dict[str, Any],
) -> None:
    if req.top_n is not None and built.get("data") is not None:
        if plan.visualization_type != "time_series":
            built["data"] = sorted(
                built["data"], key=lambda d: -d.get("trial_count", 0),
            )[: req.top_n]

    if (req.top_n is not None and plan.visualization_type == "network_graph"
            and built.get("edges") is not None):
        edges_sorted = sorted(
            built["edges"], key=lambda e: -e.get("weight", 0),
        )[: req.top_n]
        built["edges"] = edges_sorted
        kept_ids = {n for edge in edges_sorted
                    for n in (edge["source"], edge["target"])}
        built["nodes"] = [
            node for node in (built.get("nodes") or []) if node["id"] in kept_ids
        ]
        meta = built.get("_network_meta") or {}
        meta["edges_returned"] = len(edges_sorted)
        meta["nodes_returned"] = len(built["nodes"])
        built["_network_meta"] = meta


def _apply_scatter_point_cap(
    plan: QueryPlan, built: dict[str, Any], warnings: list[str],
) -> None:
    if plan.visualization_type != "scatter_plot" or built.get("data") is None:
        return
    cap = int(os.environ.get("CTGOV_SCATTER_POINT_CAP", "1000"))
    if cap <= 0 or len(built["data"]) <= cap:
        return
    original = len(built["data"])
    built["data"] = built["data"][:cap]
    warnings.append(
        f"Scatter output was display-clipped to {cap} of {original} points "
        "via CTGOV_SCATTER_POINT_CAP; source scan metadata is unchanged."
    )


def _append_network_truncation_warnings(
    built: dict[str, Any], warnings: list[str],
) -> None:
    meta = built.get("_network_meta")
    if not meta:
        return
    if meta["edges_total"] > meta["edges_returned"]:
        warnings.append(
            f"Network was truncated to the {meta['edges_returned']} "
            f"highest-weight edges out of {meta['edges_total']} total. "
            "Lower-weight relationships are omitted for readability."
        )
    if meta["nodes_total"] > meta["nodes_returned"]:
        warnings.append(
            f"{meta['nodes_total'] - meta['nodes_returned']} nodes were "
            "dropped because their only edges were truncated."
        )


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
    spec_cls = SPEC_BY_TYPE[plan.visualization_type]
    spec_kwargs: dict[str, Any] = {
        "type": plan.visualization_type,
        "title": plan.title + (" (sampled)" if truncated else ""),
        "encoding": Encoding(**built["encoding"]),
    }
    for key in ("data", "nodes", "edges"):
        if key in built and key in spec_cls.model_fields:
            spec_kwargs[key] = built[key]

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
        visualization=spec_cls(**spec_kwargs),
        meta=Meta(**meta_kwargs),
    )
