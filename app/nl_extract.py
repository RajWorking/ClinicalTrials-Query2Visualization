"""Deterministic natural-language extraction helpers for the stub planner."""
from __future__ import annotations

import re
from typing import Any, Optional

from .aliases import CONDITION_ALIASES, DRUG_ALIASES
from .schemas import AnalyzeRequest


STATUS_KEYWORDS: list[tuple[str, str]] = [
    ("not yet recruiting", "NOT_YET_RECRUITING"),
    ("active not recruiting", "ACTIVE_NOT_RECRUITING"),
    ("active, not recruiting", "ACTIVE_NOT_RECRUITING"),
    ("recruiting", "RECRUITING"),
    ("completed", "COMPLETED"),
    ("terminated", "TERMINATED"),
    ("withdrawn", "WITHDRAWN"),
    ("suspended", "SUSPENDED"),
    ("enrolling by invitation", "ENROLLING_BY_INVITATION"),
]

PHASE_KEYWORDS: list[tuple[str, str]] = [
    ("early phase 1", "EARLY_PHASE1"),
    ("early phase i", "EARLY_PHASE1"),
    ("phase 1", "PHASE1"),
    ("phase i", "PHASE1"),
    ("phase 2", "PHASE2"),
    ("phase ii", "PHASE2"),
    ("phase 3", "PHASE3"),
    ("phase iii", "PHASE3"),
    ("phase 4", "PHASE4"),
    ("phase iv", "PHASE4"),
]

SPONSOR_CLASS_KEYWORDS: list[tuple[str, str]] = [
    ("industry-sponsored", "INDUSTRY"),
    ("industry sponsored", "INDUSTRY"),
    ("industry-funded", "INDUSTRY"),
    ("industry funded", "INDUSTRY"),
    ("commercial sponsor", "INDUSTRY"),
    ("pharma-sponsored", "INDUSTRY"),
    ("pharma sponsored", "INDUSTRY"),
    ("nih-sponsored", "NIH"),
    ("nih sponsored", "NIH"),
    ("national institutes of health", "NIH"),
    ("federally sponsored", "FED"),
    ("federal sponsor", "FED"),
    ("government-sponsored", "OTHER_GOV"),
    ("government sponsored", "OTHER_GOV"),
    ("academic-sponsored", "OTHER"),
    ("academic sponsored", "OTHER"),
    ("university-sponsored", "OTHER"),
    ("university sponsored", "OTHER"),
]

STUDY_TYPE_KEYWORDS: list[tuple[str, str]] = [
    ("expanded access", "EXPANDED_ACCESS"),
    ("observational", "OBSERVATIONAL"),
    ("interventional", "INTERVENTIONAL"),
]

SEX_KEYWORDS: list[tuple[str, str]] = [
    ("female-only", "FEMALE"),
    ("female only", "FEMALE"),
    ("women-only", "FEMALE"),
    ("women only", "FEMALE"),
    ("females only", "FEMALE"),
    ("male-only", "MALE"),
    ("male only", "MALE"),
    ("men-only", "MALE"),
    ("men only", "MALE"),
    ("males only", "MALE"),
]

INTERVENTION_TYPE_KEYWORDS: list[tuple[str, str]] = [
    ("diagnostic test", "DIAGNOSTIC_TEST"),
    ("combination product", "COMBINATION_PRODUCT"),
    ("dietary supplement", "DIETARY_SUPPLEMENT"),
    ("biologic", "BIOLOGICAL"),
    ("biological", "BIOLOGICAL"),
    ("device", "DEVICE"),
    ("procedure", "PROCEDURE"),
    ("radiation", "RADIATION"),
    ("behavioral", "BEHAVIORAL"),
    ("behavioural", "BEHAVIORAL"),
    ("genetic", "GENETIC"),
    ("drug intervention", "DRUG"),
    ("drug trials", "DRUG"),
    ("drug trial", "DRUG"),
]

CONDITION_HEADS = (
    "cancer", "carcinoma", "lymphoma", "leukemia", "tumor", "tumour",
    "sarcoma", "neoplasm", "melanoma", "myeloma",
    "diabetes", "alzheimer", "parkinson", "covid", "covid-19",
    "asthma", "copd", "stroke", "depression", "anxiety", "schizophrenia",
    "arthritis", "psoriasis", "epilepsy", "obesity", "hypertension",
)
_CONDITION_HEADS_SET = set(CONDITION_HEADS)
COMMON_CONDITION_PHRASES = (
    "non-small cell lung cancer",
    "small cell lung cancer",
    "triple negative breast cancer",
    "breast cancer",
    "lung cancer",
)

# Tokens that frame the question rather than name the disease. When walking
# backward from a head ("...breast cancer"), stop at any of these.
CONDITION_STOPWORDS: set[str] = {
    "a", "an", "the", "any", "all", "some", "no",
    "this", "that", "these", "those", "such",
    "of", "for", "in", "on", "at", "by", "to", "from", "with", "without",
    "and", "or", "but", "as", "than", "into", "onto", "over", "under",
    "have", "has", "had", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "can", "could", "would", "should", "will", "may",
    "i", "we", "you", "they", "their", "our", "us", "me", "he", "she", "it",
    "most", "more", "many", "much", "few", "fewer", "less", "least", "top",
    "best", "worst", "common", "frequent", "popular",
    "recruiting", "completed", "terminated", "withdrawn", "suspended",
    "active", "ongoing", "current", "currently", "running", "open", "closed",
    "enrolling", "available", "approved",
    "trial", "trials", "study", "studies", "research",
    "country", "countries", "sponsor", "sponsors", "phase", "phases",
    "year", "years", "decade", "decades", "site", "sites",
    "what", "which", "where", "how", "when", "who", "why", "whose",
    "show", "list", "give", "tell", "find", "search", "compare",
    "number", "count", "amount", "rate", "frequency", "distribution",
    "across", "between", "per", "each", "every",
}

DIM_CATEGORY_KEYWORDS: dict[str, str] = {
    "sponsor categor": "sponsor_class",
    "sponsor class": "sponsor_class",
    "intervention type": "intervention_type",
    "study type": "study_type",
    "sex eligibility": "sex",
    "phase distribution": "phase",
    "phases": "phase",
}
DIM_AXIS_KEYWORDS: dict[str, str] = {
    "condition": "condition", "conditions": "condition",
    "disease": "condition", "diseases": "condition",
    "country": "country", "countries": "country",
    "phase": "phase", "phases": "phase",
    "year": "year", "years": "year",
    "sponsor": "lead_sponsor", "sponsors": "lead_sponsor",
}

NET_SIGNALS = (
    "network", "co-occur", "co occur", "cooccur",
    "combination studies", "combination trials", "combinations", "combined with",
    "used together", "drugs together", "together in",
    "co-prescribed", "co prescribed",
)
NET_DRUG_DRUG_SIGNALS = (
    "co-occur", "co occur", "cooccur", "combination", "combined", "together",
)
NET_SITE_SIGNALS = (
    "trial site", "trial sites", "site", "sites",
    "location", "locations", "facility", "facilities",
)

# (regex, group_by, title hint) — explicit "by <dim>" framings.
BY_DIM_PATTERNS: list[tuple[str, str, str]] = [
    (r"\b(?:by|across|per)\s+phase(?:s)?\b|\bphase\s+distribution\b", "phase", "phase"),
    (
        r"\b(?:by|across|per)\s+(?:year|years)\b|\bper\s+year\b|"
        r"\beach\s+year\b|\bover\s+time\b|\bsince\s+\d{4}\b|\btrend\b",
        "year", "year",
    ),
    (
        r"\b(?:by|across|per)\s+countr(?:y|ies)\b|"
        r"\b(?:which|what)\s+countries\b|\bgeograph(?:y|ic)\b",
        "country", "country",
    ),
    (r"\b(?:by|across|per)\s+status(?:es)?\b|\bstatus\s+distribution\b",
     "overall_status", "status"),
    (r"\b(?:by|across|per)\s+sponsor\s+class\b|\bindustry\s+vs\s+academic\b",
     "sponsor_class", "sponsor class"),
    (r"\b(?:by|across|per)\s+sponsors?\b|\bmost\s+active\s+sponsors?\b|"
     r"\btop\s+sponsors?\b", "lead_sponsor", "sponsor"),
    (r"\b(?:by|across|per)\s+study\s+type\b|"
     r"\bobservational\s+vs\s+interventional\b", "study_type", "study type"),
    (r"\b(?:by|across|per)\s+(?:sex|gender)\b|\bsex\s+eligibility\b",
     "sex", "sex eligibility"),
    (r"\b(?:by|across|per)\s+intervention\s+type\b",
     "intervention_type", "intervention type"),
    (r"\b(?:by|across|per)\s+condition(?:s)?\b", "condition", "condition"),
]

# X-vs-Y comparison regex (multi-word entities, refusing stop-word tokens).
COMPARE_STOP = r"(?:by|for|in|across|over|between|on|at|vs|versus|and)"
COMPARE_ENTITY = (
    rf"[A-Za-z][\w\-]*(?:\s+(?!{COMPARE_STOP}\b)[A-Za-z][\w\-]*){{0,3}}"
)
COMPARE_PATTERN = re.compile(
    rf"(?:compare\s+)?({COMPARE_ENTITY})\s+(?:vs\.?|versus|and)\s+({COMPARE_ENTITY})"
)

STRUCTURED_REQUEST_FIELDS = (
    "drug_name", "condition", "sponsor", "country",
    "phase", "status", "sponsor_class", "study_type", "sex",
    "intervention_type", "start_year", "end_year",
)

CLINICAL_SIGNALS = (
    "trial", "trials", "clinical", "study", "studies", "phase", "sponsor",
    "drug", "drugs", "intervention", "condition", "disease", "patient",
    "patients", "enrollment", "recruiting", "completed", "observational",
    "interventional", "registry", "ct.gov", "clinicaltrials",
    *CONDITION_HEADS,
    *COMMON_CONDITION_PHRASES,
)
OFF_TOPIC_SIGNALS = (
    "weather", "forecast", "stock price", "recipe", "sports", "football",
    "basketball", "movie", "song", "poem", "joke", "capital of",
    "translate", "salary", "restaurant", "flight", "hotel",
)


def extract_condition_phrase(q: str) -> Optional[str]:
    """Walk backward from a condition head, stopping at stopwords."""
    for phrase in COMMON_CONDITION_PHRASES:
        if re.search(rf"\b{re.escape(phrase)}\b", q.lower()):
            return phrase.title()

    tokens = re.findall(r"[\w\-]+", q.lower())
    for i, tok in enumerate(tokens):
        if tok not in _CONDITION_HEADS_SET:
            continue
        qualifier: list[str] = []
        for j in range(i - 1, -1, -1):
            t = tokens[j]
            if t in CONDITION_STOPWORDS or t in _CONDITION_HEADS_SET:
                break
            qualifier.insert(0, t)
            if len(qualifier) >= 3:
                break
        return " ".join(qualifier + [tok]).title()
    return None


def keyword_value(
    q: str, pairs: list[tuple[str, str]], existing: Optional[str] = None,
) -> Optional[str]:
    if existing:
        return existing
    for kw, val in pairs:
        if kw in q:
            return val
    return None


def alias_match(q: str, aliases: dict[str, str]) -> Optional[str]:
    """First alias whose key matches a word boundary in q -> canonical value."""
    for alias, full in aliases.items():
        if re.search(rf"\b{re.escape(alias)}\b", q):
            return full
    return None


def year_bounds(q: str, sy: Optional[int], ey: Optional[int]) -> tuple[
    Optional[int], Optional[int],
]:
    if not sy and (m := re.search(r"\b(?:initiated\s+|started\s+)?since\s+(\d{4})\b", q)):
        sy = int(m.group(1))
    if not sy and not ey and (m := re.search(
        r"\bbetween\s+(\d{4})\s+(?:and|to|-)\s+(\d{4})\b", q
    )):
        sy, ey = int(m.group(1)), int(m.group(2))
    if not ey and (m := re.search(r"\b(?:before|until|by)\s+(\d{4})\b", q)):
        ey = int(m.group(1))
    return sy, ey


def extract_filters_from_query(req: AnalyzeRequest, q: str) -> dict[str, Any]:
    """Best-effort filter inference. Each value is req.X or inferred-from-q."""
    cond = req.condition or alias_match(q, CONDITION_ALIASES) or extract_condition_phrase(q)
    drug_alias = alias_match(q, DRUG_ALIASES)
    drug = req.drug_name or (drug_alias.title() if drug_alias else None)
    sy, ey = year_bounds(q, req.start_year, req.end_year)
    return {
        "status": keyword_value(q, STATUS_KEYWORDS, req.status),
        "phase": keyword_value(q, PHASE_KEYWORDS, req.phase),
        "condition": cond,
        "drug_name": drug,
        "sponsor_class": keyword_value(q, SPONSOR_CLASS_KEYWORDS, req.sponsor_class),
        "study_type": keyword_value(q, STUDY_TYPE_KEYWORDS, req.study_type),
        "sex": keyword_value(q, SEX_KEYWORDS, req.sex),
        "intervention_type": keyword_value(
            q, INTERVENTION_TYPE_KEYWORDS, req.intervention_type,
        ),
        "start_year": sy,
        "end_year": ey,
    }


def has_any(q: str, signals: tuple[str, ...]) -> bool:
    return any(signal in q for signal in signals)


def network_kind_for(q: str) -> Optional[str]:
    mentions_site_drugs = has_any(q, NET_SITE_SIGNALS) and "drug" in q
    mentions_sponsor_drugs = "sponsor" in q and "drug" in q
    if not (
        has_any(q, NET_SIGNALS)
        or mentions_sponsor_drugs
        or mentions_site_drugs
    ):
        return None
    if mentions_site_drugs:
        return "site_drug"
    if has_any(q, NET_DRUG_DRUG_SIGNALS):
        return "drug_drug"
    if mentions_sponsor_drugs:
        return "sponsor_drug"
    if "condition" in q or "disease" in q:
        return "drug_condition"
    return "sponsor_drug"


def detect_compare_axis(q: str) -> Optional[str]:
    """Pull the requested axis from "compare A vs B by <axis>"."""
    for pat, dim, _hint in BY_DIM_PATTERNS:
        if re.search(pat, q):
            return dim
    return None


def has_structured_query_fields(req: AnalyzeRequest) -> bool:
    return any(getattr(req, field) is not None for field in STRUCTURED_REQUEST_FIELDS)


def is_obviously_off_topic(req: AnalyzeRequest) -> bool:
    """Conservative guard for requests that are plainly not trial questions."""
    if has_structured_query_fields(req):
        return False
    q = req.query.lower()
    has_clinical_signal = any(signal in q for signal in CLINICAL_SIGNALS)
    has_off_topic_signal = any(signal in q for signal in OFF_TOPIC_SIGNALS)
    return has_off_topic_signal and not has_clinical_signal
