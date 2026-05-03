"""Deterministic aggregation of normalized studies into visualization data."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Optional

from .citations import cite, cite_for
from .schemas import Aggregation, QueryPlan


# ---- network-graph entity filters -----------------------------------------

DRUG_LIKE_TYPES = {"DRUG", "BIOLOGICAL", "COMBINATION_PRODUCT"}

# Names (canonicalized) that don't identify a specific molecule.
DRUG_NAME_BLOCKLIST = {
    # placebo / control / vehicle
    "placebo", "saline", "vehicle", "normal saline", "matching placebo",
    "placebo control", "placebo comparator", "control", "control arm",
    "no intervention", "sham", "sham comparator", "untreated", "active comparator",
    # supportive / SOC
    "best supportive care", "supportive care", "standard of care", "soc",
    "standard therapy", "standard treatment", "usual care",
    # biospecimens / procedures often miscoded as DRUG
    "blood sample", "blood draw", "biopsy", "questionnaire", "survey",
    "observation", "exercise", "education", "counseling",
    # broad classes
    "chemotherapy", "chemo", "radiotherapy", "radiation",
    "immunotherapy", "targeted therapy", "combination chemotherapy",
    "investigator's choice", "physician's choice", "patient's choice",
    # arm-label artifacts
    "arm a", "arm b", "arm c", "arm 1", "arm 2", "arm 3",
    "cohort a", "cohort b", "cohort 1", "cohort 2",
    "experimental arm", "experimental",
}

_ARM_LABEL_PATTERN = re.compile(
    r"^(?:arm|cohort|group|stage|part|step)\s*[a-z0-9\-]+$", re.IGNORECASE,
)

_DOSAGE_FORMS = (
    r"injection|infusion|tablet|tablets|capsule|capsules|solution|"
    r"suspension|cream|ointment|gel|patch|spray|drops|inhaler|"
    r"oral|iv|i\.v\.|subcutaneous|sc|sublingual"
)
_DOSE_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|kg|iu|units|%|mg/m2|mg/kg)\b", re.IGNORECASE,
)
_FORM_PATTERN = re.compile(rf"\b(?:{_DOSAGE_FORMS})\b", re.IGNORECASE)
_PAREN_PATTERN = re.compile(r"\([^)]*\)")
_BRACKET_PATTERN = re.compile(r"\[[^\]]*\]")
_WHITESPACE = re.compile(r"\s+")


def canonicalize_drug(name: str) -> str:
    """Lowercase + strip parentheticals, dosage values, dosage forms."""
    s = name.strip()
    s = _PAREN_PATTERN.sub(" ", s)
    s = _BRACKET_PATTERN.sub(" ", s)
    s = _DOSE_PATTERN.sub(" ", s)
    s = _FORM_PATTERN.sub(" ", s)
    s = re.sub(r"[,;]+", " ", s)
    return _WHITESPACE.sub(" ", s).strip().lower()


# ---- field accessors ------------------------------------------------------

PHASE_LABEL = {
    "PHASE1": "Phase 1", "PHASE2": "Phase 2", "PHASE3": "Phase 3",
    "PHASE4": "Phase 4", "EARLY_PHASE1": "Early Phase 1", "NA": "Not Applicable",
}
STATUS_LABEL = {
    "RECRUITING": "Recruiting", "NOT_YET_RECRUITING": "Not yet recruiting",
    "ACTIVE_NOT_RECRUITING": "Active, not recruiting", "COMPLETED": "Completed",
    "TERMINATED": "Terminated", "WITHDRAWN": "Withdrawn", "SUSPENDED": "Suspended",
    "ENROLLING_BY_INVITATION": "Enrolling by invitation", "UNKNOWN": "Unknown",
    "AVAILABLE": "Available", "NO_LONGER_AVAILABLE": "No longer available",
    "TEMPORARILY_NOT_AVAILABLE": "Temporarily not available",
    "APPROVED_FOR_MARKETING": "Approved for marketing", "WITHHELD": "Withheld",
}


def _parse_year(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    try:
        return int(date_str[:4])
    except (ValueError, TypeError):
        return None


def _parse_ym(date_str: Optional[str]) -> Optional[tuple[int, int]]:
    if not date_str or len(date_str) < 7:
        return None
    try:
        return int(date_str[:4]), int(date_str[5:7])
    except (ValueError, TypeError):
        return None


def _duration_months(study: dict) -> Optional[float]:
    s, e = _parse_ym(study.get("start_date")), _parse_ym(study.get("completion_date"))
    if not s or not e:
        return None
    months = (e[0] - s[0]) * 12 + (e[1] - s[1])
    return float(months) if months >= 0 else None


def _values_for_dim(study: dict, dim: str) -> list[str]:
    """One or more bucket-values for a study under a given dimension."""
    if dim == "phase":
        phases = study.get("phases") or []
        return [PHASE_LABEL.get(p, p) for p in phases] or ["Not Applicable"]
    if dim == "overall_status":
        s = study.get("overall_status")
        return [STATUS_LABEL.get(s, s)] if s else []
    if dim in ("study_type", "sex", "sponsor_class"):
        s = study.get(dim)
        return [s.title()] if s else []
    if dim == "country":
        return list(study.get("countries") or [])
    if dim == "intervention_type":
        return sorted({t.title() for t in (study.get("intervention_types") or []) if t})
    if dim == "intervention_name":
        return sorted({n for n in (study.get("intervention_names") or []) if n})
    if dim == "lead_sponsor":
        s = study.get("lead_sponsor")
        return [s] if s else []
    if dim == "condition":
        return list(study.get("conditions") or [])
    if dim == "year":
        y = _parse_year(study.get("start_date"))
        return [str(y)] if y else []
    if dim == "quarter":
        ym = _parse_ym(study.get("start_date"))
        return [f"{ym[0]}-Q{(ym[1]-1)//3 + 1}"] if ym else []
    if dim == "month":
        ym = _parse_ym(study.get("start_date"))
        return [f"{ym[0]}-{ym[1]:02d}"] if ym else []
    return []


# ---- builders -------------------------------------------------------------

def _datum(slist: list[dict], dim: str, key: str, **extras: Any) -> dict[str, Any]:
    """Common datum shape for bar/grouped_bar/time_series/histogram buckets."""
    nct_ids = [s["nct_id"] for s in slist if s.get("nct_id")]
    return {
        dim: key,
        "trial_count": len(slist),
        "supporting_nct_ids": nct_ids,
        "supporting_nct_ids_complete": True,
        "citation_count": len(nct_ids),
        "citations": [c.model_dump() for c in cite_for(slist, dim, key)],
        **extras,
    }


def _bucket_studies(studies: list[dict], dim: str) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for s in studies:
        for v in _values_for_dim(s, dim):
            buckets[v].append(s)
    return buckets


def build_bar(studies: list[dict], plan: QueryPlan) -> dict[str, Any]:
    dim = plan.aggregation.group_by or "phase"
    buckets = _bucket_studies(studies, dim)
    items = sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return {
        "data": [_datum(slist, dim, key) for key, slist in items],
        "encoding": {
            "x": {"field": dim, "type": "nominal"},
            "y": {"field": "trial_count", "type": "quantitative"},
        },
    }


def build_grouped_bar(
    studies_by_series: dict[str, list[dict]], plan: QueryPlan,
) -> dict[str, Any]:
    """studies_by_series maps series_value (e.g. drug name) -> matching trials."""
    group_dim = plan.aggregation.group_by or "phase"
    series_dim = plan.aggregation.series or "intervention_name"
    rows: list[dict[str, Any]] = []
    for series_value, studies in studies_by_series.items():
        for key, slist in _bucket_studies(studies, group_dim).items():
            rows.append(_datum(slist, group_dim, key, **{series_dim: series_value}))
    rows.sort(key=lambda r: (r[group_dim], r[series_dim]))
    return {
        "data": rows,
        "encoding": {
            "x": {"field": group_dim, "type": "nominal"},
            "y": {"field": "trial_count", "type": "quantitative"},
            "series": {"field": series_dim, "type": "nominal"},
        },
    }


def build_time_series(studies: list[dict], plan: QueryPlan) -> dict[str, Any]:
    dim = plan.aggregation.group_by or "year"
    if dim not in ("year", "quarter", "month"):
        dim = "year"
    items = sorted(_bucket_studies(studies, dim).items(), key=lambda kv: kv[0])
    return {
        "data": [_datum(slist, dim, key) for key, slist in items],
        "encoding": {
            "x": {"field": dim, "type": "temporal" if dim != "year" else "ordinal"},
            "y": {"field": "trial_count", "type": "quantitative"},
        },
    }


def _numeric_values(studies: list[dict], field: str) -> list[tuple[float, dict]]:
    out: list[tuple[float, dict]] = []
    for s in studies:
        v: Optional[float] = None
        if field == "enrollment_count":
            raw = s.get("enrollment_count")
            v = float(raw) if isinstance(raw, (int, float)) else None
        elif field == "duration_months":
            v = _duration_months(s)
        elif field == "start_year":
            y = _parse_year(s.get("start_date"))
            v = float(y) if y else None
        if v is not None:
            out.append((v, s))
    return out


def build_histogram(studies: list[dict], plan: QueryPlan) -> dict[str, Any]:
    field = plan.aggregation.x_field or "enrollment_count"
    pairs = _numeric_values(studies, field)
    encoding = {
        "x": {"field": "bin", "type": "ordinal", "title": field},
        "y": {"field": "trial_count", "type": "quantitative"},
    }
    if not pairs:
        return {"data": [], "encoding": encoding}
    values = [v for v, _ in pairs]
    lo, hi = min(values), max(values)
    nbins = max(2, plan.aggregation.bin_count or 10)
    width = (hi - lo) / nbins or 1.0
    buckets: list[list[dict]] = [[] for _ in range(nbins)]
    for v, s in pairs:
        buckets[min(int((v - lo) / width), nbins - 1)].append(s)
    data = []
    for i, slist in enumerate(buckets):
        a, b = lo + i * width, lo + (i + 1) * width
        label = f"{int(a)}–{int(b)}" if width >= 1 else f"{a:.2f}–{b:.2f}"
        data.append(_datum(slist, "bin", label, bin_start=a, bin_end=b))
    return {"data": data, "encoding": encoding}


def build_scatter(studies: list[dict], plan: QueryPlan) -> dict[str, Any]:
    xf = plan.aggregation.x_field or "duration_months"
    yf = plan.aggregation.y_field or "enrollment_count"
    points: list[dict[str, Any]] = []
    for s in studies:
        xv, yv = _numeric_values([s], xf), _numeric_values([s], yf)
        if not xv or not yv:
            continue
        points.append({
            xf: xv[0][0], yf: yv[0][0],
            "nct_id": s.get("nct_id"),
            "citations": [c.model_dump() for c in cite([s], n=1)],
        })
    return {
        "data": points,
        "encoding": {
            "x": {"field": xf, "type": "quantitative"},
            "y": {"field": yf, "type": "quantitative"},
        },
    }


# ---- network builder ------------------------------------------------------

def _drug_names(study: dict) -> list[tuple[str, str]]:
    """Drug-like interventions as (canonical_id, display_label), deduped per study.

    Filters non-drug intervention types, arm-label artifacts, and blocklisted
    names. When a MeSH term shares a canonical form with an intervention, the
    MeSH form wins as the display label.
    """
    mesh_terms = [
        (t or "").strip()
        for t in (study.get("intervention_mesh") or [])
        if (t or "").strip()
    ]
    mesh_by_canon = {canonicalize_drug(t): t for t in mesh_terms}

    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for i in study.get("interventions") or []:
        name = (i.get("name") or "").strip()
        if not name:
            continue
        itype = (i.get("type") or "").upper()
        if itype and itype not in DRUG_LIKE_TYPES:
            continue
        if _ARM_LABEL_PATTERN.match(name):
            continue
        canon = canonicalize_drug(name)
        if not canon or canon in DRUG_NAME_BLOCKLIST or canon in seen:
            continue
        seen.add(canon)
        out.append((canon, mesh_by_canon.get(canon, name)))

    # MeSH terms unrelated to listed interventions: still useful (clinically canonical).
    for mesh in mesh_terms:
        canon = canonicalize_drug(mesh)
        if canon and canon not in seen and canon not in DRUG_NAME_BLOCKLIST:
            seen.add(canon)
            out.append((canon, mesh))
    return out


def build_network(studies: list[dict], plan: QueryPlan) -> dict[str, Any]:
    """Build a graph keyed by canonical IDs with majority-vote display labels."""
    kind = plan.aggregation.network_kind or "sponsor_drug"
    edges: dict[tuple[str, str], list[dict]] = defaultdict(list)
    nodes: dict[str, str] = {}
    label_votes: dict[str, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))

    def add_node(node_id: str, node_type: str, label: Optional[str] = None) -> None:
        if not node_id:
            return
        if node_id not in nodes:
            nodes[node_id] = node_type
        if label:
            label_votes[node_id][label] += 1

    for s in studies:
        if kind == "sponsor_drug":
            sponsor = (s.get("lead_sponsor") or "").strip()
            drugs = _drug_names(s) if sponsor else []
            if not drugs:
                continue
            add_node(sponsor, "sponsor", sponsor)
            for canon, display in drugs:
                add_node(canon, "drug", display)
                edges[(sponsor, canon)].append(s)
        elif kind == "drug_condition":
            for canon, display in _drug_names(s):
                add_node(canon, "drug", display)
                for cond in set(s.get("conditions") or []):
                    add_node(cond, "condition", cond)
                    edges[(canon, cond)].append(s)
        elif kind == "drug_drug":
            drugs = sorted(_drug_names(s))
            for canon, display in drugs:
                add_node(canon, "drug", display)
            for i in range(len(drugs)):
                for j in range(i + 1, len(drugs)):
                    edges[(drugs[i][0], drugs[j][0])].append(s)

    # Adaptive prune: drop weight-1 edges in dense graphs, then cap at 200.
    EDGE_CAP = 200
    sorted_edges = sorted(edges.items(), key=lambda kv: -len(kv[1]))
    edges_total = len(sorted_edges)
    min_weight = 2 if edges_total > 500 else 1
    if min_weight > 1:
        sorted_edges = [(k, v) for k, v in sorted_edges if len(v) >= min_weight]
    edge_items = sorted_edges[:EDGE_CAP]

    kept_ids = {n for (a, b), _ in edge_items for n in (a, b)}

    def best_label(node_id: str) -> str:
        votes = label_votes.get(node_id) or {}
        return max(votes.items(), key=lambda kv: (kv[1], len(kv[0])))[0] if votes else node_id

    node_list = [
        {"id": n, "label": best_label(n), "type": nodes[n]}
        for n in sorted(kept_ids, key=lambda x: best_label(x).lower())
    ]
    edge_list = [
        {
            "source": a, "target": b, "weight": len(slist),
            "citations": [c.model_dump() for c in cite(slist)],
        }
        for (a, b), slist in edge_items
    ]
    return {
        "nodes": node_list,
        "edges": edge_list,
        "encoding": {
            "nodes": {"id": "id", "label": "label", "type": "type"},
            "edges": {"source": "source", "target": "target", "weight": "weight"},
        },
        "_network_meta": {
            "nodes_returned": len(node_list),
            "nodes_total": len(nodes),
            "edges_returned": len(edge_list),
            "edges_total": edges_total,
            "min_edge_weight": min_weight,
        },
    }


BUILDERS = {
    "bar_chart": build_bar,
    "time_series": build_time_series,
    "histogram": build_histogram,
    "scatter_plot": build_scatter,
    "network_graph": build_network,
    # grouped_bar handled separately — it consumes a dict[str, list]
}
