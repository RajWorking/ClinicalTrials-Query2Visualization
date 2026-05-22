"""Exact countTotal fan-out helpers for CT.gov-backed aggregations."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Optional

from .aggregate import _values_for_dim
from .citations import cite_for
from .constants import EXACT_COUNT_DIMS
from .ctgov import CTGovClient
from .schemas import Filters


# Open-ended dims whose value sets are unbounded (unlike EXACT_COUNT_DIMS).
# Strategy: scan a sample window to discover candidate values, then fire one
# exact countTotal query per candidate. Counts are exact for discovered values;
# values that appear only outside the sample window are omitted with a warning.
HIGH_CARDINALITY_FANOUT_DIMS: dict[str, str] = {
    "lead_sponsor": "sponsor",
    "country": "country",
    "condition": "condition",
    "intervention_name": "drug_name",
}


def _filters_with(filters: Filters, **overrides: Any) -> Filters:
    return filters.model_copy(
        update={k: v for k, v in overrides.items() if v is not None}
    )


def _zero_exact_datum(dim: str, label: str, **extras: Any) -> dict[str, Any]:
    return {
        dim: label,
        "trial_count": 0,
        "sampled": False,
        "citation_count": 0,
        "supporting_nct_ids": [],
        "supporting_nct_ids_complete": True,
        "citations": [],
        **extras,
    }


def _exact_datum(
    studies: list[dict], dim: str, label: str, total: int, **extras: Any,
) -> dict[str, Any]:
    """Datum shape for exact-count fan-out paths.

    `trial_count` is the API's totalCount; IDs are only a citation sample,
    hence supporting_nct_ids_complete=False.
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


async def _fetch_bucket_datum(
    client: CTGovClient, filters: Filters, dim: str, label: str, **extras: Any,
) -> Optional[dict[str, Any]]:
    studies, total = await client.search_studies(filters, max_studies=5, page_size=5)
    if total == 0:
        return None
    return _exact_datum(studies, dim, label, total, **extras)


async def _exact_bucket_counts(
    client: CTGovClient,
    base_filters: Filters,
    filter_field: str,
    buckets: list[tuple[str, str]],
    group_by: str,
) -> tuple[list[dict[str, Any]], int, int]:
    existing = getattr(base_filters, filter_field, None)
    if existing:
        buckets = [b for b in buckets if b[0] == existing]
    return await _exact_fanout_counts(
        client, base_filters, filter_field, buckets, group_by,
    )


async def _exact_fanout_counts(
    client: CTGovClient,
    base_filters: Filters,
    filter_field: str,
    buckets: list[tuple[str, str]],
    group_by: str,
    *,
    sort_key: Optional[Any] = None,
) -> tuple[list[dict[str, Any]], int, int]:
    async def one(value: str, label: str) -> Optional[dict[str, Any]]:
        f = _filters_with(base_filters, **{filter_field: value})
        return await _fetch_bucket_datum(client, f, group_by, label)

    bucket_task = asyncio.gather(*(one(v, l) for v, l in buckets))
    base_task = client.count_for_filters(base_filters)
    results, base_total = await asyncio.gather(bucket_task, base_task)
    data = [r for r in results if r is not None]
    data.sort(key=sort_key or (lambda d: -d["trial_count"]))
    return data, base_total, sum(d["trial_count"] for d in data)


async def _exact_high_cardinality_counts(
    client: CTGovClient,
    base_filters: Filters,
    filter_field: str,
    group_by: str,
    sample_size: int,
    candidate_cap: int = 50,
) -> tuple[list[dict[str, Any]], int, bool]:
    studies, base_total = await client.search_studies(
        base_filters, max_studies=sample_size,
    )
    candidate_set_sampled = len(studies) < base_total

    candidate_counts: dict[str, int] = defaultdict(int)
    for study in studies:
        for value in _values_for_dim(study, group_by):
            if value:
                candidate_counts[value] += 1
    if not candidate_counts:
        return [], base_total, candidate_set_sampled

    top_candidates = sorted(
        candidate_counts.items(), key=lambda kv: -kv[1],
    )[:candidate_cap]

    async def one(value: str) -> Optional[dict[str, Any]]:
        f = _filters_with(base_filters, **{filter_field: value})
        return await _fetch_bucket_datum(client, f, group_by, value)

    results = await asyncio.gather(*(one(v) for v, _ in top_candidates))
    data = [r for r in results if r is not None]
    data.sort(key=lambda d: -d["trial_count"])
    return data, base_total, candidate_set_sampled


async def _exact_grouped_compare(
    client: CTGovClient,
    base_filters: Filters,
    series_field: str,
    series_dim: str,
    series_values: list[str],
    group_by: str,
) -> tuple[list[dict[str, Any]], int, int, dict[str, int], bool]:
    if group_by not in EXACT_COUNT_DIMS:
        raise ValueError(f"exact grouped compare not supported for {group_by}")
    bucket_field, buckets = EXACT_COUNT_DIMS[group_by]

    async def cell(sv: str, bvalue: str, blabel: str) -> dict[str, Any]:
        f = _filters_with(base_filters, **{series_field: sv, bucket_field: bvalue})
        datum = await _fetch_bucket_datum(
            client, f, group_by, blabel, **{series_dim: sv},
        )
        return datum or _zero_exact_datum(group_by, blabel, **{series_dim: sv})

    cell_tasks = [cell(sv, bv, bl) for sv in series_values for bv, bl in buckets]
    id_tasks = [
        client.ids_for_filters(_filters_with(base_filters, **{series_field: sv}))
        for sv in series_values
    ]
    cell_results, *id_results = await asyncio.gather(
        asyncio.gather(*cell_tasks), *id_tasks,
    )
    rows = list(cell_results)
    rows.sort(key=lambda d: (d[group_by], d[series_dim]))

    per_series = {sv: 0 for sv in series_values}
    for row in rows:
        per_series[row[series_dim]] += row["trial_count"]
    bucket_memberships = sum(per_series.values())

    union: set[str] = set()
    truncated_any = False
    for ids, _total, truncated in id_results:
        union |= ids
        truncated_any = truncated_any or truncated
    distinct_total = len(union)
    if truncated_any:
        distinct_total = max(distinct_total, max(per_series.values(), default=0))
    return rows, distinct_total, bucket_memberships, per_series, truncated_any


async def _exact_year_counts(
    client: CTGovClient, base_filters: Filters, start_year: int, end_year: int,
) -> tuple[list[dict[str, Any]], int]:
    async def one(year: int) -> Optional[dict[str, Any]]:
        f = _filters_with(base_filters, start_year=year, end_year=year)
        return await _fetch_bucket_datum(client, f, "year", str(year))

    years = list(range(start_year, end_year + 1))
    results = await asyncio.gather(*(one(y) for y in years))
    data = [
        r or _zero_exact_datum("year", str(year))
        for year, r in zip(years, results)
    ]
    return data, sum(d["trial_count"] for d in data)

