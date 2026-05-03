"""Drug-node canonicalization and extraction for network graphs."""
from __future__ import annotations

import re

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
    # biospecimens / procedures often miscoded as DRUG (or MeSH-tagged onto a trial)
    "blood sample", "blood draw", "blood specimen collection",
    "biopsy", "tumor biopsy", "tissue biopsy",
    "questionnaire", "survey", "observation", "exercise", "education", "counseling",
    "imaging", "ct scan", "mri", "pet scan", "ultrasound", "x-ray",
    "biomarker analysis", "biomarker assessment", "laboratory biomarker analysis",
    "gene expression profiling", "immunohistochemistry", "flow cytometry",
    "pharmacological study", "pharmacokinetic study",
    # broad classes / MeSH umbrella terms (not a specific molecule)
    "chemotherapy", "chemo", "radiotherapy", "radiation", "radiation therapy",
    "immunotherapy", "targeted therapy", "combination chemotherapy",
    "antineoplastic agents", "antineoplastic", "antibodies", "antibodies monoclonal",
    "monoclonal antibodies", "cancer vaccines", "vaccines",
    "colony-stimulating factors", "immunoglobulin g", "immunoglobulins",
    "cytokines", "interleukins", "interferons", "growth factors",
    "adjuvants immunologic", "adjuvants",
    "antigens", "ctla-4 antigen", "gp100 antigen", "pd-l1 antigen",
    "introns", "exons", "rna", "dna",  # MeSH biological structures
    "disulfides", "sulfides", "salts",  # chemical classes
    "investigator's choice", "physician's choice", "patient's choice",
    # arm-label artifacts
    "arm a", "arm b", "arm c", "arm 1", "arm 2", "arm 3",
    "cohort a", "cohort b", "cohort 1", "cohort 2",
    "experimental arm", "experimental", "treatment", "intervention",
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
    r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|kg|iu|units|%|mg/m2|mg/kg)\b",
    re.IGNORECASE,
)
_FORM_PATTERN = re.compile(rf"\b(?:{_DOSAGE_FORMS})\b", re.IGNORECASE)
_PAREN_PATTERN = re.compile(r"\([^)]*\)")
_BRACKET_PATTERN = re.compile(r"\[[^\]]*\]")
_WHITESPACE = re.compile(r"\s+")

# Salt / ester / hydrate suffixes are stripped from the end so related
# salt-form names collapse to the parent INN.
_SALT_SUFFIX = re.compile(
    r"\s+(?:"
    r"mesylate|besylate|tosylate|fumarate|maleate|succinate|tartrate|"
    r"citrate|acetate|gluconate|lactate|nitrate|"
    r"hydrochloride|hcl|hydrobromide|sulfate|sulphate|phosphate|"
    r"sodium|potassium|calcium|disodium|dipotassium|"
    r"chloride|bromide|iodide|"
    r"s-malate|malate|"
    r"monohydrate|dihydrate|trihydrate|hemihydrate|hydrate|anhydrous"
    r")\s*$",
    re.IGNORECASE,
)


def canonicalize_drug(name: str) -> str:
    """Lowercase + strip parentheticals, dosage values, dosage forms, salts."""
    s = name.strip()
    s = _PAREN_PATTERN.sub(" ", s)
    s = _BRACKET_PATTERN.sub(" ", s)
    s = _DOSE_PATTERN.sub(" ", s)
    s = _FORM_PATTERN.sub(" ", s)
    s = re.sub(r"[,;]+", " ", s)
    s = _WHITESPACE.sub(" ", s).strip().lower()
    while True:
        stripped = _SALT_SUFFIX.sub("", s).strip()
        if stripped == s or not stripped:
            break
        s = stripped
    return s


def _is_specific_drug_name(name: str, canon: str) -> bool:
    return bool(canon and canon not in DRUG_NAME_BLOCKLIST
                and not _ARM_LABEL_PATTERN.match(name))


def drug_names(study: dict) -> list[tuple[str, str]]:
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
    for intervention in study.get("interventions") or []:
        name = (intervention.get("name") or "").strip()
        if not name:
            continue
        itype = (intervention.get("type") or "").upper()
        if itype and itype not in DRUG_LIKE_TYPES:
            continue
        canon = canonicalize_drug(name)
        if not _is_specific_drug_name(name, canon) or canon in seen:
            continue
        seen.add(canon)
        out.append((canon, mesh_by_canon.get(canon, name)))

    # MeSH terms unrelated to listed interventions: still useful (clinically canonical).
    for mesh in mesh_terms:
        canon = canonicalize_drug(mesh)
        if _is_specific_drug_name(mesh, canon) and canon not in seen:
            seen.add(canon)
            out.append((canon, mesh))
    return out
