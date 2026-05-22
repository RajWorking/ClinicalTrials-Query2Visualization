"""Drug-node canonicalization and extraction for network graphs."""
from __future__ import annotations

import re

# Three of the eleven InterventionType values in the CT.gov v2 API that
# represent pharmacological agents. The remaining eight (DEVICE, PROCEDURE,
# RADIATION, BEHAVIORAL, GENETIC, DIETARY_SUPPLEMENT, DIAGNOSTIC_TEST, OTHER)
# are not drug-like and are excluded from drug network nodes.
DRUG_LIKE_TYPES = {"DRUG", "BIOLOGICAL", "COMBINATION_PRODUCT"}

# CT.gov protocols with multiple arms frequently enter the arm label as an
# intervention name (e.g., "Arm A", "Cohort 1", "Group 2", "Part 1") rather
# than the actual drug. This pattern catches those artifacts before they
# become spurious network nodes.
_ARM_LABEL_PATTERN = re.compile(
    r"^(?:arm|cohort|group|stage|part|step)\s*[a-z0-9\-]+$", re.IGNORECASE,
)

# Standard pharmaceutical route-of-administration and dosage-form terms.
# CT.gov sponsors enter these as part of the intervention name
# (e.g., "Pembrolizumab 200 mg IV infusion"). Stripping them lets
# "Pembrolizumab 200 mg injection" and "Pembrolizumab" collapse to the
# same canonical node.
_DOSAGE_FORMS = (
    r"injection|infusion|tablet|tablets|capsule|capsules|solution|"
    r"suspension|cream|ointment|gel|patch|spray|drops|inhaler|"
    r"oral|iv|i\.v\.|subcutaneous|sc|sublingual"
)
# Standard drug dosing notation: mg/mcg/g/ml/kg/IU/% for fixed doses;
# mg/m² and mg/kg for BSA- and weight-adjusted dosing.
_DOSE_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|kg|iu|units|%|mg/m2|mg/kg)\b",
    re.IGNORECASE,
)
_FORM_PATTERN = re.compile(rf"\b(?:{_DOSAGE_FORMS})\b", re.IGNORECASE)
_PAREN_PATTERN = re.compile(r"\([^)]*\)")
_BRACKET_PATTERN = re.compile(r"\[[^\]]*\]")
_WHITESPACE = re.compile(r"\s+")

# Pharmaceutical salt, ester, and hydration-state suffixes. WHO INN
# (International Nonproprietary Name) is the global standard identifier for
# a drug substance and never includes the salt form. CT.gov sponsors often
# register the formulated salt name (e.g., "Imatinib Mesylate", "Cabozantinib
# S-malate") rather than the INN stem. Stripping these collapses salt variants
# to the parent INN so they resolve to one network node.
#   - Acid-addition salts: mesylate (methanesulfonate), besylate
#     (benzenesulfonate), tosylate (p-toluenesulfonate), fumarate, maleate,
#     succinate, tartrate, citrate, acetate, gluconate, lactate, nitrate,
#     hydrochloride (HCl), hydrobromide, sulfate/sulphate, phosphate
#   - Metal salts: sodium, potassium, calcium, disodium, dipotassium,
#     chloride, bromide, iodide
#   - Malate forms: s-malate (used for cabozantinib), malate
#   - Hydration states: mono/di/trihydrate, hemihydrate, hydrate, anhydrous
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
    return bool(canon and not _ARM_LABEL_PATTERN.match(name))


def drug_names(study: dict) -> list[tuple[str, str]]:
    """Drug-like interventions as (canonical_id, display_label), deduped per study.

    Filters non-drug intervention types and arm-label artifacts. When a MeSH
    term shares a canonical form with an intervention, the MeSH form wins as
    the display label.
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
