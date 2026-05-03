"""Deep citations: nct_id + datum-supporting excerpt + JSON path + URL."""
from __future__ import annotations

import re
from typing import Callable, Iterable, Optional

from .constants import (
    INTERVENTION_TYPE_LABELS,
    PHASE_LABELS,
    PHASE_VARIANTS,
    SEX_LABELS,
    SPONSOR_CLASS_LABELS,
    STATUS_LABELS,
    STUDY_TYPE_LABELS,
)
from .schemas import Citation


MAX_EXCERPT = 280
DEFAULT_PER_BUCKET = 3

_FIELD_PATHS: dict[str, str] = {
    "phase": "protocolSection.designModule.phases",
    "overall_status": "protocolSection.statusModule.overallStatus",
    "study_type": "protocolSection.designModule.studyType",
    "sex": "protocolSection.eligibilityModule.sex",
    "country": "protocolSection.contactsLocationsModule.locations[].country",
    "lead_sponsor": "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
    "sponsor_class": "protocolSection.sponsorCollaboratorsModule.leadSponsor.class",
    "condition": "protocolSection.conditionsModule.conditions",
    "site": "protocolSection.contactsLocationsModule.locations[]",
    "intervention_type": "protocolSection.armsInterventionsModule.interventions[].type",
    "intervention_name": "protocolSection.armsInterventionsModule.interventions[].name",
    "year": "protocolSection.statusModule.startDateStruct.date",
    "quarter": "protocolSection.statusModule.startDateStruct.date",
    "month": "protocolSection.statusModule.startDateStruct.date",
}

def _truncate(text: str, n: int = MAX_EXCERPT) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def study_url(nct_id: str) -> str:
    return f"https://clinicaltrials.gov/study/{nct_id}"


def _aliases_for(dim: str, value: str) -> list[str]:
    """Search terms whose presence in narrative text supports a (dim, value) datum."""
    if dim == "phase":
        canon = value.replace(" ", "").upper()
        if not canon.startswith("PHASE"):
            canon = "PHASE" + canon
        return [value, *PHASE_VARIANTS.get(canon, ())]
    if dim in ("year", "quarter", "month"):
        return [value[:4]]
    if dim in ("overall_status", "country", "condition", "intervention_name"):
        return [value]
    return []


def _find_excerpt_in_summary(summary: str, terms: list[str]) -> Optional[str]:
    if not summary or not terms:
        return None
    sentences = re.split(r"(?<=[.!?])\s+", summary)
    for term in filter(None, terms):
        pat = re.compile(re.escape(term), re.IGNORECASE)
        for sent in sentences:
            if pat.search(sent):
                return _truncate(sent.strip())
    return None


# Per-dim formatter for the structured-field fallback excerpt. Each entry
# maps a dim → (study-field → text) such that returning None means the
# study lacks that field and we should fall through.
def _list_with_more(items: list[str], label: str, n: int = 5) -> str:
    shown = ", ".join(items[:n])
    more = f" (+{len(items)-n} more)" if len(items) > n else ""
    return f"{label}: {shown}{more}"


def _label(value: Optional[str], labels: dict[str, str]) -> Optional[str]:
    if value is None:
        return None
    return labels.get(value, value)


def _labels(values: list[str], labels: dict[str, str]) -> list[str]:
    return [labels.get(value, value) for value in values if value]


_STRUCTURED_FORMATTERS: dict[str, Callable[[dict], Optional[str]]] = {
    "phase": lambda s: _list_with_more(_labels(s["phases"], PHASE_LABELS), "phases") if s.get("phases") else None,
    "overall_status": lambda s: f"overallStatus: {_label(s['overall_status'], STATUS_LABELS)}" if s.get("overall_status") else None,
    "study_type": lambda s: f"studyType: {_label(s['study_type'], STUDY_TYPE_LABELS)}" if s.get("study_type") else None,
    "sex": lambda s: f"sex: {_label(s['sex'], SEX_LABELS)}" if s.get("sex") else None,
    "lead_sponsor": lambda s: f"leadSponsor: {s['lead_sponsor']}" if s.get("lead_sponsor") else None,
    "sponsor_class": lambda s: f"leadSponsorClass: {_label(s['sponsor_class'], SPONSOR_CLASS_LABELS)}" if s.get("sponsor_class") else None,
    "country": lambda s: _list_with_more(s["countries"], "locations") if s.get("countries") else None,
    "condition": lambda s: _list_with_more(s["conditions"], "conditions") if s.get("conditions") else None,
    "site": lambda s: _list_with_more(_site_labels(s), "sites") if _site_labels(s) else None,
    "intervention_type": lambda s: _list_with_more(_labels(s["intervention_types"], INTERVENTION_TYPE_LABELS), "interventionTypes") if s.get("intervention_types") else None,
    "intervention_name": lambda s: _list_with_more(s["intervention_names"], "interventions") if s.get("intervention_names") else None,
    "year": lambda s: f"startDate: {s['start_date']}" if s.get("start_date") else None,
    "quarter": lambda s: f"startDate: {s['start_date']}" if s.get("start_date") else None,
    "month": lambda s: f"startDate: {s['start_date']}" if s.get("start_date") else None,
}


def _site_labels(study: dict) -> list[str]:
    labels = []
    for loc in study.get("locations") or []:
        facility = (loc.get("facility") or "").strip()
        country = (loc.get("country") or "").strip()
        city = (loc.get("city") or "").strip()
        label = facility or city or country
        if label and country and country not in label:
            label = f"{label} ({country})"
        if label:
            labels.append(label)
    if not labels:
        labels = list(study.get("countries") or [])
    return labels


def _network_field_text(study: dict, node_type: str) -> Optional[tuple[str, str]]:
    if node_type == "sponsor" and study.get("lead_sponsor"):
        return (
            f"leadSponsor: {study['lead_sponsor']}",
            _FIELD_PATHS["lead_sponsor"],
        )
    if node_type == "drug" and study.get("intervention_names"):
        return (
            _list_with_more(study["intervention_names"], "interventions"),
            _FIELD_PATHS["intervention_name"],
        )
    if node_type == "condition" and study.get("conditions"):
        return (
            _list_with_more(study["conditions"], "conditions"),
            _FIELD_PATHS["condition"],
        )
    if node_type == "site":
        labels = _site_labels(study)
        if labels:
            return (_list_with_more(labels, "sites"), _FIELD_PATHS["site"])
    return None


def _one_citation(study: dict, dim: Optional[str], value: Optional[str]) -> Citation:
    nct = study["nct_id"]
    title = (study.get("brief_title") or "").strip()
    summary = (study.get("brief_summary") or "").strip()

    # 1. Narrative sentence from briefSummary that mentions the bucket value.
    if dim and value:
        excerpt = _find_excerpt_in_summary(summary, _aliases_for(dim, value))
        if excerpt:
            return Citation(
                nct_id=nct, excerpt=excerpt,
                source_field="protocolSection.descriptionModule.briefSummary",
                url=study_url(nct),
            )

    # 2. Structured-field value at the bucket's source path.
    if dim and (formatter := _STRUCTURED_FORMATTERS.get(dim)):
        text = formatter(study)
        if text:
            return Citation(
                nct_id=nct, excerpt=_truncate(text),
                source_field=_FIELD_PATHS[dim], url=study_url(nct),
            )

    # 3. Brief title fallback.
    return Citation(
        nct_id=nct,
        excerpt=_truncate(title or summary),
        source_field="protocolSection.identificationModule.briefTitle"
        if title else "protocolSection.descriptionModule.briefSummary",
        url=study_url(nct),
    )


def cite_for(
    studies: Iterable[dict],
    dim: Optional[str],
    value: Optional[str],
    n: int = DEFAULT_PER_BUCKET,
) -> list[Citation]:
    out: list[Citation] = []
    for s in studies:
        if not s.get("nct_id"):
            continue
        out.append(_one_citation(s, dim, value))
        if len(out) >= n:
            break
    return out


def cite(studies: Iterable[dict], n: int = DEFAULT_PER_BUCKET) -> list[Citation]:
    """Generic citations — for scatter and network where there's no single dim."""
    return cite_for(studies, None, None, n=n)


def cite_network_edge(
    studies: Iterable[dict],
    source_type: str,
    target_type: str,
    n: int = DEFAULT_PER_BUCKET,
) -> list[Citation]:
    """Structured citations for relationship edges.

    The excerpt names the source-side and target-side CT.gov fields that form
    the edge, so network relationships are traceable rather than title-only.
    """
    out: list[Citation] = []
    for s in studies:
        if not s.get("nct_id"):
            continue
        parts: list[str] = []
        paths: list[str] = []
        for node_type in dict.fromkeys((source_type, target_type)):
            formatted = _network_field_text(s, node_type)
            if formatted:
                text, path = formatted
                parts.append(text)
                paths.append(path)
        if parts:
            out.append(Citation(
                nct_id=s["nct_id"],
                excerpt=_truncate("; ".join(parts)),
                source_field=" + ".join(dict.fromkeys(paths)),
                url=study_url(s["nct_id"]),
            ))
        else:
            out.append(_one_citation(s, None, None))
        if len(out) >= n:
            break
    return out
