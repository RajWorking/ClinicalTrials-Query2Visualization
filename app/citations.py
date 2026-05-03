"""Deep citations: nct_id + datum-supporting excerpt + JSON path + URL."""
from __future__ import annotations

import re
from typing import Callable, Iterable, Optional

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
    "intervention_type": "protocolSection.armsInterventionsModule.interventions[].type",
    "intervention_name": "protocolSection.armsInterventionsModule.interventions[].name",
    "year": "protocolSection.statusModule.startDateStruct.date",
    "quarter": "protocolSection.statusModule.startDateStruct.date",
    "month": "protocolSection.statusModule.startDateStruct.date",
}

_PHASE_VARIANTS = {
    "PHASE1": ("Phase 1", "Phase I"),
    "PHASE2": ("Phase 2", "Phase II"),
    "PHASE3": ("Phase 3", "Phase III"),
    "PHASE4": ("Phase 4", "Phase IV"),
    "EARLY_PHASE1": ("Early Phase 1", "Early Phase I"),
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
        return [value, *_PHASE_VARIANTS.get(canon, ())]
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


_STRUCTURED_FORMATTERS: dict[str, Callable[[dict], Optional[str]]] = {
    "phase": lambda s: f"phases: {s['phases']}" if s.get("phases") else None,
    "overall_status": lambda s: f"overallStatus: {s['overall_status']}" if s.get("overall_status") else None,
    "study_type": lambda s: f"studyType: {s['study_type']}" if s.get("study_type") else None,
    "sex": lambda s: f"sex: {s['sex']}" if s.get("sex") else None,
    "lead_sponsor": lambda s: f"leadSponsor: {s['lead_sponsor']}" if s.get("lead_sponsor") else None,
    "sponsor_class": lambda s: f"leadSponsorClass: {s['sponsor_class']}" if s.get("sponsor_class") else None,
    "country": lambda s: _list_with_more(s["countries"], "locations") if s.get("countries") else None,
    "condition": lambda s: _list_with_more(s["conditions"], "conditions") if s.get("conditions") else None,
    "intervention_type": lambda s: f"interventionTypes: {s['intervention_types']}" if s.get("intervention_types") else None,
    "intervention_name": lambda s: f"interventions: {s['intervention_names'][:5]}" if s.get("intervention_names") else None,
    "year": lambda s: f"startDate: {s['start_date']}" if s.get("start_date") else None,
    "quarter": lambda s: f"startDate: {s['start_date']}" if s.get("start_date") else None,
    "month": lambda s: f"startDate: {s['start_date']}" if s.get("start_date") else None,
}


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
