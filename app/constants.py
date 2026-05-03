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
PLANNER_STATUS_ENUM = (
    "RECRUITING", "NOT_YET_RECRUITING", "ACTIVE_NOT_RECRUITING",
    "COMPLETED", "TERMINATED", "WITHDRAWN", "SUSPENDED",
    "ENROLLING_BY_INVITATION", "UNKNOWN",
)


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


COUNTRY_BUCKETS = [
    "Argentina", "Australia", "Austria", "Belgium", "Brazil", "Bulgaria",
    "Canada", "Chile", "China", "Colombia", "Croatia", "Czechia", "Denmark",
    "Egypt", "Finland", "France", "Germany", "Greece", "Hong Kong", "Hungary",
    "India", "Ireland", "Israel", "Italy", "Japan", "Korea, Republic of",
    "Malaysia", "Mexico", "Netherlands", "New Zealand", "Norway", "Poland",
    "Portugal", "Romania", "Russian Federation", "Singapore", "South Africa",
    "Spain", "Sweden", "Switzerland", "Taiwan", "Thailand", "Turkey",
    "Ukraine", "United Kingdom", "United States",
    "Algeria", "Bangladesh", "Belarus", "Bosnia and Herzegovina", "Costa Rica",
    "Cyprus", "Dominican Republic", "Estonia", "Georgia", "Iceland",
    "Indonesia", "Iran, Islamic Republic of", "Jordan", "Kenya", "Kuwait",
    "Latvia", "Lebanon", "Lithuania", "Luxembourg", "Malta", "Morocco",
    "Pakistan", "Panama", "Peru", "Philippines", "Puerto Rico", "Qatar",
    "Saudi Arabia", "Serbia", "Slovakia", "Slovenia", "Sri Lanka",
    "United Arab Emirates", "Uruguay", "Viet Nam",
]
