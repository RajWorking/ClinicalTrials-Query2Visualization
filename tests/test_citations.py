from app.citations import cite_for, cite_network_edge

from ._helpers import make_study


def test_structured_phase_fallback_uses_display_labels_not_python_repr():
    study = make_study("NCTPHASE", brief_summary="", phases=["PHASE1", "PHASE2"])

    [citation] = cite_for([study], "phase", "Phase 1", n=1)

    assert citation.excerpt == "phases: Phase 1, Phase 2"
    assert "[" not in citation.excerpt
    assert "PHASE1" not in citation.excerpt


def test_structured_intervention_type_fallback_uses_display_labels():
    study = make_study(
        "NCTTYPE",
        brief_summary="",
        intervention_types=["DRUG", "BIOLOGICAL"],
    )

    [citation] = cite_for([study], "intervention_type", "Drug", n=1)

    assert citation.excerpt == "interventionTypes: Drug, Biological"
    assert "[" not in citation.excerpt


def test_network_edge_drug_excerpt_formats_lists_cleanly():
    study = make_study(
        "NCTEDGE",
        brief_summary="",
        lead_sponsor="Merck",
        intervention_names=["Pembrolizumab", "Nivolumab"],
    )

    [citation] = cite_network_edge([study], "sponsor", "drug", n=1)

    assert "leadSponsor: Merck" in citation.excerpt
    assert "interventions: Pembrolizumab, Nivolumab" in citation.excerpt
    assert "[" not in citation.excerpt
