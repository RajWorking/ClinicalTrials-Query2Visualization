from app.constants import (
    EXACT_COUNT_DIMS,
    INTERVENTION_TYPE_VALUES,
    PHASE_LABELS,
    PHASE_VALUES,
    PHASE_VARIANTS,
    SEX_VALUES,
    SPONSOR_CLASS_VALUES,
    STATUS_VALUES,
    STUDY_TYPE_VALUES,
)
from app.drugs import canonicalize_drug, drug_names

from ._helpers import make_study as _study


def test_exact_count_bucket_values_are_schema_values():
    allowed_by_dim = {
        "phase": PHASE_VALUES,
        "overall_status": STATUS_VALUES,
        "sponsor_class": SPONSOR_CLASS_VALUES,
        "study_type": STUDY_TYPE_VALUES,
        "sex": SEX_VALUES,
        "intervention_type": INTERVENTION_TYPE_VALUES,
    }
    for dim, (_filter_field, buckets) in EXACT_COUNT_DIMS.items():
        assert {value for value, _label in buckets} <= allowed_by_dim[dim]


def test_phase_labels_and_citation_variants_share_source():
    for code, label in PHASE_LABELS.items():
        assert label in PHASE_VARIANTS[code]


def test_drug_canonicalization_and_extraction_boundaries():
    assert canonicalize_drug("Pembrolizumab 200 mg injection") == "pembrolizumab"
    assert canonicalize_drug("Cabozantinib S-malate") == "cabozantinib"

    study = _study(
        interventions=[
            {"name": "PEMBROLIZUMAB 200 mg injection", "type": "DRUG"},
            {"name": "Arm A", "type": "DRUG"},           # filtered by arm-label regex
            {"name": "MRI scan", "type": "DIAGNOSTIC_TEST"},  # filtered by type
        ],
        intervention_mesh=["pembrolizumab"],
    )
    assert drug_names(study) == [("pembrolizumab", "pembrolizumab")]
