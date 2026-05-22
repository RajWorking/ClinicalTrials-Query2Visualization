"""Shared enum values, labels, and fixed bucket definitions."""
from __future__ import annotations

VIZ_TYPES = (
    "bar_chart", "grouped_bar_chart", "time_series",
    "scatter_plot", "histogram", "network_graph",
)

GROUP_DIMS = (
    "phase", "overall_status", "study_type", "sex",
    "lead_sponsor", "sponsor_class", "country",
    "intervention_type", "intervention_name", "condition",
    "year", "quarter", "month",
)

NUMERIC_FIELDS = ("enrollment_count", "duration_months", "start_year")
NETWORK_KINDS = ("sponsor_drug", "drug_condition", "drug_drug", "site_drug")


# CT.gov v2 API `Phase` enum (field: Phase).
# EARLY_PHASE1 covers first-in-human exploratory studies that precede a
# formal Phase 1; NA is used for non-interventional and certain expanded
# access records where phase doesn't apply.
PHASE_LABELS = {
    "PHASE1": "Phase 1",
    "PHASE2": "Phase 2",
    "PHASE3": "Phase 3",
    "PHASE4": "Phase 4",
    "EARLY_PHASE1": "Early Phase 1",
    "NA": "Not Applicable",
}
PHASE_ENUM = tuple(PHASE_LABELS)
PHASE_VALUES = set(PHASE_ENUM)
# Roman numerals (I–IV) are the traditional FDA/clinical convention;
# CT.gov's own UI displays Arabic numerals. Both appear in literature so
# the plan verifier accepts either form.
PHASE_VARIANTS = {
    "PHASE1": ("Phase 1", "Phase I"),
    "PHASE2": ("Phase 2", "Phase II"),
    "PHASE3": ("Phase 3", "Phase III"),
    "PHASE4": ("Phase 4", "Phase IV"),
    "EARLY_PHASE1": ("Early Phase 1", "Early Phase I"),
    "NA": ("Not Applicable",),
}
PHASE_SYNONYMS = {
    "1": "PHASE1", "i": "PHASE1", "phase 1": "PHASE1",
    "phase1": "PHASE1", "phase_1": "PHASE1",
    "2": "PHASE2", "ii": "PHASE2", "phase 2": "PHASE2",
    "phase2": "PHASE2", "phase_2": "PHASE2",
    "3": "PHASE3", "iii": "PHASE3", "phase 3": "PHASE3",
    "phase3": "PHASE3", "phase_3": "PHASE3",
    "4": "PHASE4", "iv": "PHASE4", "phase 4": "PHASE4",
    "phase4": "PHASE4", "phase_4": "PHASE4",
    "early phase 1": "EARLY_PHASE1", "early_phase_1": "EARLY_PHASE1",
    "early phase i": "EARLY_PHASE1", "early phase1": "EARLY_PHASE1",
    "n/a": "NA", "not applicable": "NA", "none": "NA",
}


# CT.gov v2 API `OverallStatus` enum (field: OverallStatus).
# The last five values (AVAILABLE through WITHHELD) are only used for
# expanded access records (compassionate/emergency use outside of trials),
# not for standard trial registrations.
STATUS_LABELS = {
    "RECRUITING": "Recruiting",
    "NOT_YET_RECRUITING": "Not yet recruiting",
    "ACTIVE_NOT_RECRUITING": "Active, not recruiting",
    "COMPLETED": "Completed",
    "TERMINATED": "Terminated",
    "WITHDRAWN": "Withdrawn",
    "SUSPENDED": "Suspended",
    "ENROLLING_BY_INVITATION": "Enrolling by invitation",
    "UNKNOWN": "Unknown",
    "AVAILABLE": "Available",
    "NO_LONGER_AVAILABLE": "No longer available",
    "TEMPORARILY_NOT_AVAILABLE": "Temporarily not available",
    "APPROVED_FOR_MARKETING": "Approved for marketing",
    "WITHHELD": "Withheld",
}
STATUS_ENUM = tuple(STATUS_LABELS)
STATUS_VALUES = set(STATUS_ENUM)
# Subset exposed to the LLM planner: omits the five expanded access statuses
# (AVAILABLE, NO_LONGER_AVAILABLE, TEMPORARILY_NOT_AVAILABLE,
# APPROVED_FOR_MARKETING, WITHHELD) which appear only on compassionate-use
# records and would add noise to NL query planning.
PLANNER_STATUS_ENUM = (
    "RECRUITING", "NOT_YET_RECRUITING", "ACTIVE_NOT_RECRUITING",
    "COMPLETED", "TERMINATED", "WITHDRAWN", "SUSPENDED",
    "ENROLLING_BY_INVITATION", "UNKNOWN",
)


# CT.gov v2 API `LeadSponsorClass` enum (field: LeadSponsorClass).
# Classification is assigned by NLM/CT.gov based on the lead sponsor's
# organization type: INDUSTRY = commercial pharma/biotech; NIH = National
# Institutes of Health specifically; FED = other US federal agencies (DoD,
# VA, etc.); OTHER_GOV = non-US government agencies; INDIV = individual
# investigators; NETWORK = clinical research networks (e.g., ECOG-ACRIN,
# NCI cooperative groups); AMBIG = classification uncertain; OTHER =
# academic, non-profit, or other entities not fitting the above.
SPONSOR_CLASS_LABELS = {
    "INDUSTRY": "Industry",
    "NIH": "NIH",
    "FED": "Federal",
    "OTHER_GOV": "Other government",
    "INDIV": "Individual",
    "NETWORK": "Network",
    "AMBIG": "Ambiguous",
    "OTHER": "Other",
    "UNKNOWN": "Unknown",
}
SPONSOR_CLASS_ENUM = tuple(SPONSOR_CLASS_LABELS)
SPONSOR_CLASS_VALUES = set(SPONSOR_CLASS_ENUM)
SPONSOR_CLASS_SYNONYMS = {
    "industry": "INDUSTRY",
    "industry-sponsored": "INDUSTRY",
    "industry sponsored": "INDUSTRY",
    "commercial": "INDUSTRY",
    "pharma": "INDUSTRY",
    "nih": "NIH",
    "national institutes of health": "NIH",
    "federal": "FED",
    "fed": "FED",
    "government": "OTHER_GOV",
    "other government": "OTHER_GOV",
    "academic": "OTHER",
    "university": "OTHER",
    "other": "OTHER",
    "individual": "INDIV",
    "investigator": "INDIV",
    "network": "NETWORK",
    "ambiguous": "AMBIG",
    "unknown": "UNKNOWN",
}


# CT.gov v2 API `StudyType` enum (field: StudyType).
# INTERVENTIONAL = participants assigned to an intervention (standard clinical
# trial); OBSERVATIONAL = participants observed without an assigned
# intervention; EXPANDED_ACCESS = compassionate/emergency use outside of a
# clinical trial.
STUDY_TYPE_LABELS = {
    "INTERVENTIONAL": "Interventional",
    "OBSERVATIONAL": "Observational",
    "EXPANDED_ACCESS": "Expanded access",
}
STUDY_TYPE_ENUM = tuple(STUDY_TYPE_LABELS)
STUDY_TYPE_VALUES = set(STUDY_TYPE_ENUM)
STUDY_TYPE_SYNONYMS = {
    "interventional": "INTERVENTIONAL",
    "intervention": "INTERVENTIONAL",
    "clinical trial": "INTERVENTIONAL",
    "observational": "OBSERVATIONAL",
    "observation": "OBSERVATIONAL",
    "expanded access": "EXPANDED_ACCESS",
    "expanded_access": "EXPANDED_ACCESS",
}


# CT.gov v2 API `Sex` enum (field: Sex, representing eligibility sex).
# Three values: ALL (no sex restriction on eligibility), FEMALE, MALE.
SEX_LABELS = {
    "ALL": "All",
    "FEMALE": "Female",
    "MALE": "Male",
}
SEX_ENUM = tuple(SEX_LABELS)
SEX_VALUES = set(SEX_ENUM)
SEX_SYNONYMS = {
    "all": "ALL",
    "any": "ALL",
    "both": "ALL",
    "female": "FEMALE",
    "females": "FEMALE",
    "women": "FEMALE",
    "woman": "FEMALE",
    "male": "MALE",
    "males": "MALE",
    "men": "MALE",
    "man": "MALE",
}


# CT.gov v2 API `InterventionType` enum (field: InterventionType).
# All eleven values as defined in the CT.gov data model.
INTERVENTION_TYPE_LABELS = {
    "DRUG": "Drug",
    "BIOLOGICAL": "Biological",
    "DEVICE": "Device",
    "PROCEDURE": "Procedure",
    "RADIATION": "Radiation",
    "BEHAVIORAL": "Behavioral",
    "GENETIC": "Genetic",
    "DIETARY_SUPPLEMENT": "Dietary supplement",
    "COMBINATION_PRODUCT": "Combination product",
    "DIAGNOSTIC_TEST": "Diagnostic test",
    "OTHER": "Other",
}
INTERVENTION_TYPE_ENUM = tuple(INTERVENTION_TYPE_LABELS)
INTERVENTION_TYPE_VALUES = set(INTERVENTION_TYPE_ENUM)
INTERVENTION_TYPE_SYNONYMS = {
    "drug": "DRUG",
    "drugs": "DRUG",
    "biologic": "BIOLOGICAL",
    "biological": "BIOLOGICAL",
    "biologics": "BIOLOGICAL",
    "device": "DEVICE",
    "devices": "DEVICE",
    "procedure": "PROCEDURE",
    "procedures": "PROCEDURE",
    "radiation": "RADIATION",
    "behavioral": "BEHAVIORAL",
    "behavioural": "BEHAVIORAL",
    "genetic": "GENETIC",
    "dietary supplement": "DIETARY_SUPPLEMENT",
    "dietary_supplement": "DIETARY_SUPPLEMENT",
    "supplement": "DIETARY_SUPPLEMENT",
    "combination product": "COMBINATION_PRODUCT",
    "combination_product": "COMBINATION_PRODUCT",
    "diagnostic test": "DIAGNOSTIC_TEST",
    "diagnostic_test": "DIAGNOSTIC_TEST",
    "diagnostic": "DIAGNOSTIC_TEST",
    "other": "OTHER",
}


# Dimensions whose complete set of values is a closed enum defined by CT.gov.
# For these dims the paths layer issues one countTotal API call per bucket
# value instead of paginating all matching studies — exact counts at O(buckets)
# API calls rather than O(pages). Open-ended dims (lead_sponsor, country,
# condition, intervention_name) are ineligible because their value spaces are
# unbounded.
EXACT_COUNT_DIMS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "phase": ("phase", [(v, PHASE_LABELS[v]) for v in PHASE_ENUM]),
    "overall_status": (
        "status",
        [(v, STATUS_LABELS[v]) for v in PLANNER_STATUS_ENUM],
    ),
    "sponsor_class": (
        "sponsor_class",
        [(v, SPONSOR_CLASS_LABELS[v]) for v in SPONSOR_CLASS_ENUM],
    ),
    "study_type": (
        "study_type",
        [(v, STUDY_TYPE_LABELS[v]) for v in STUDY_TYPE_ENUM],
    ),
    "sex": ("sex", [(v, SEX_LABELS[v]) for v in SEX_ENUM]),
    "intervention_type": (
        "intervention_type",
        [(v, INTERVENTION_TYPE_LABELS[v]) for v in INTERVENTION_TYPE_ENUM],
    ),
}

