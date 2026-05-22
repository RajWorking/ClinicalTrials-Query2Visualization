from app.aggregate import (
    build_bar,
    build_grouped_bar,
    build_histogram,
    build_network,
    build_scatter,
    build_time_series,
)
from app.schemas import Aggregation, Filters, QueryPlan

from ._helpers import make_study as _study


def _plan(**agg) -> QueryPlan:
    return QueryPlan(
        visualization_type="bar_chart",
        title="t",
        query_interpretation="i",
        filters=Filters(),
        aggregation=Aggregation(**agg),
    )


def test_bar_phase_groups_and_counts():
    studies = [
        _study(nct_id="NCT01", phases=["PHASE1"]),
        _study(nct_id="NCT02", phases=["PHASE2"]),
        _study(nct_id="NCT03", phases=["PHASE2"]),
        _study(nct_id="NCT04", phases=["PHASE3"]),
    ]
    out = build_bar(studies, _plan(group_by="phase"))
    by_key = {d["phase"]: d["trial_count"] for d in out["data"]}
    assert by_key == {"Phase 1": 1, "Phase 2": 2, "Phase 3": 1}
    p2 = next(d for d in out["data"] if d["phase"] == "Phase 2")
    assert {c["nct_id"] for c in p2["citations"]} == {"NCT02", "NCT03"}


def test_bar_country_handles_multivalued():
    studies = [
        _study(nct_id="NCT01", countries=["United States", "Germany"]),
        _study(nct_id="NCT02", countries=["Germany"]),
    ]
    out = build_bar(studies, _plan(group_by="country"))
    by_key = {d["country"]: d["trial_count"] for d in out["data"]}
    assert by_key == {"Germany": 2, "United States": 1}


def test_time_series_year():
    studies = [
        _study(nct_id="NCT01", start_date="2018-03-01"),
        _study(nct_id="NCT02", start_date="2020-09-12"),
        _study(nct_id="NCT03", start_date="2020-01-01"),
    ]
    out = build_time_series(studies, _plan(group_by="year"))
    by_key = {d["year"]: d["trial_count"] for d in out["data"]}
    assert by_key == {"2018": 1, "2020": 2}


def test_histogram_enrollment():
    studies = [_study(enrollment_count=v) for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]]
    out = build_histogram(studies, _plan(x_field="enrollment_count", bin_count=5))
    assert len(out["data"]) == 5
    assert sum(d["trial_count"] for d in out["data"]) == 10


def test_scatter_pairs_only_complete():
    studies = [
        _study(nct_id="NCT01", enrollment_count=100, start_date="2020-01-01", completion_date="2022-01-01"),
        _study(nct_id="NCT02", enrollment_count=None),  # dropped
    ]
    out = build_scatter(studies, _plan(x_field="duration_months", y_field="enrollment_count"))
    assert len(out["data"]) == 1
    assert out["data"][0]["nct_id"] == "NCT01"


def test_grouped_bar_two_drugs():
    a = [_study(nct_id="NCTA1", phases=["PHASE2"]), _study(nct_id="NCTA2", phases=["PHASE3"])]
    b = [_study(nct_id="NCTB1", phases=["PHASE3"])]
    out = build_grouped_bar(
        {"DrugA": a, "DrugB": b},
        _plan(group_by="phase", series="intervention_name"),
    )
    rows = {(r["phase"], r["intervention_name"]): r["trial_count"] for r in out["data"]}
    assert rows == {
        ("Phase 2", "DrugA"): 1,
        ("Phase 3", "DrugA"): 1,
        ("Phase 3", "DrugB"): 1,
    }


def test_network_sponsor_drug():
    """Drug nodes use canonical (lowercased) IDs; labels keep original casing."""
    studies = [
        _study(nct_id="NCT01", lead_sponsor="Merck",
               interventions=[{"name": "Pembro", "type": "DRUG"}]),
        _study(nct_id="NCT02", lead_sponsor="Merck",
               interventions=[{"name": "Pembro", "type": "DRUG"},
                              {"name": "Docetaxel", "type": "DRUG"}]),
        _study(nct_id="NCT03", lead_sponsor="Roche",
               interventions=[{"name": "Atezo", "type": "DRUG"}]),
    ]
    out = build_network(studies, _plan(network_kind="sponsor_drug"))
    edges = {(e["source"], e["target"]): e["weight"] for e in out["edges"]}
    assert edges[("Merck", "pembro")] == 2
    assert edges[("Merck", "docetaxel")] == 1
    assert edges[("Roche", "atezo")] == 1
    types = {n["id"]: n["type"] for n in out["nodes"]}
    assert types["Merck"] == "sponsor"
    assert types["pembro"] == "drug"
    labels = {n["id"]: n["label"] for n in out["nodes"]}
    assert labels["pembro"] == "Pembro"



def test_network_canonicalizes_dosage_form_variants():
    """Pembrolizumab / pembrolizumab / Pembrolizumab 200 mg → one node."""
    studies = [
        _study(nct_id="NCT01", lead_sponsor="Merck",
               interventions=[{"name": "Pembrolizumab", "type": "DRUG"}]),
        _study(nct_id="NCT02", lead_sponsor="Merck",
               interventions=[{"name": "pembrolizumab", "type": "DRUG"}]),
        _study(nct_id="NCT03", lead_sponsor="Merck",
               interventions=[{"name": "Pembrolizumab 200 mg injection", "type": "DRUG"}]),
    ]
    out = build_network(studies, _plan(network_kind="sponsor_drug"))
    drug_nodes = [n for n in out["nodes"] if n["type"] == "drug"]
    assert len(drug_nodes) == 1
    edges = [e for e in out["edges"] if e["source"] == "Merck"]
    assert len(edges) == 1
    assert edges[0]["weight"] == 3


def test_network_mesh_term_preferred_when_canonicals_match():
    """When a study's intervention canonicalizes to the same form as a MeSH
    term, the MeSH term wins as the display label."""
    studies = [
        _study(
            nct_id="NCT01", lead_sponsor="Merck",
            interventions=[{"name": "PEMBROLIZUMAB 200 mg injection", "type": "DRUG"}],
            intervention_mesh=["pembrolizumab"],
        ),
    ]
    out = build_network(studies, _plan(network_kind="sponsor_drug"))
    drugs = [n for n in out["nodes"] if n["type"] == "drug"]
    assert len(drugs) == 1
    assert drugs[0]["id"] == "pembrolizumab"
    assert drugs[0]["label"] == "pembrolizumab"  # MeSH form, not the dosage form


def test_network_drug_drug_cooccurrence():
    studies = [
        _study(interventions=[{"name": "A", "type": "DRUG"},
                              {"name": "B", "type": "DRUG"}]),
        _study(interventions=[{"name": "A", "type": "DRUG"},
                              {"name": "B", "type": "DRUG"},
                              {"name": "C", "type": "DRUG"}]),
    ]
    out = build_network(studies, _plan(network_kind="drug_drug"))
    edges = {(e["source"], e["target"]): e["weight"] for e in out["edges"]}
    # Canonical IDs are lowercased.
    assert edges[("a", "b")] == 2
    assert edges[("a", "c")] == 1
    assert edges[("b", "c")] == 1


def test_network_site_drug():
    studies = [
        _study(
            nct_id="NCT01",
            interventions=[{"name": "Pembrolizumab", "type": "DRUG"}],
            locations=[{
                "facility": "Memorial Cancer Center",
                "city": "New York",
                "state": "NY",
                "country": "United States",
            }],
            countries=["United States"],
        ),
        _study(
            nct_id="NCT02",
            interventions=[{"name": "Pembrolizumab", "type": "DRUG"}],
            locations=[{
                "facility": "Memorial Cancer Center",
                "city": "New York",
                "state": "NY",
                "country": "United States",
            }],
            countries=["United States"],
        ),
    ]
    out = build_network(studies, _plan(network_kind="site_drug"))
    types = {n["id"]: n["type"] for n in out["nodes"]}
    site_id = next(node_id for node_id, typ in types.items() if typ == "site")
    assert types["pembrolizumab"] == "drug"
    edge = next(e for e in out["edges"] if e["source"] == site_id)
    assert edge["target"] == "pembrolizumab"
    assert edge["weight"] == 2
    assert "locations" in edge["citations"][0]["source_field"]
    assert "interventions" in edge["citations"][0]["source_field"]


def test_network_canonicalizes_salt_forms():
    """Drug salt / hydrate variants should collapse to the parent INN node.

    Real CT.gov data routinely lists e.g. 'Dabrafenib' and 'Dabrafenib Mesylate'
    as separate interventions on related studies, polluting the graph with
    duplicate drug nodes.
    """
    studies = [
        _study(nct_id="NCT01", lead_sponsor="GSK",
               interventions=[{"name": "Dabrafenib", "type": "DRUG"}]),
        _study(nct_id="NCT02", lead_sponsor="GSK",
               interventions=[{"name": "Dabrafenib Mesylate", "type": "DRUG"}]),
        _study(nct_id="NCT03", lead_sponsor="Exelixis",
               interventions=[{"name": "Cabozantinib S-malate", "type": "DRUG"}]),
        _study(nct_id="NCT04", lead_sponsor="Exelixis",
               interventions=[{"name": "Cabozantinib", "type": "DRUG"}]),
        _study(nct_id="NCT05", lead_sponsor="Acme",
               interventions=[{"name": "Fludarabine phosphate monohydrate",
                               "type": "DRUG"}]),
        _study(nct_id="NCT06", lead_sponsor="Acme",
               interventions=[{"name": "Fludarabine", "type": "DRUG"}]),
    ]
    out = build_network(studies, _plan(network_kind="sponsor_drug"))
    drug_nodes = {n["id"] for n in out["nodes"] if n["type"] == "drug"}
    assert drug_nodes == {"dabrafenib", "cabozantinib", "fludarabine"}



def test_network_edges_carry_sampled_flag():
    """Edges must expose `sampled` for parity with bar/time-series datums.

    The network builder itself emits sampled=False; the request handler
    flips it when the underlying study set was truncated.
    """
    studies = [
        _study(nct_id="NCT01", lead_sponsor="Merck",
               interventions=[{"name": "Pembro", "type": "DRUG"}]),
    ]
    out = build_network(studies, _plan(network_kind="sponsor_drug"))
    assert out["edges"]
    for e in out["edges"]:
        assert "sampled" in e
        assert e["sampled"] is False


def test_network_filters_non_drug_interventions():
    """Non-drug intervention types must not appear as drug nodes."""
    studies = [
        _study(
            nct_id="NCT01", lead_sponsor="Acme",
            interventions=[
                {"name": "DrugX", "type": "DRUG"},
                {"name": "Surgery A", "type": "PROCEDURE"},
                {"name": "MRI scan", "type": "DIAGNOSTIC_TEST"},
            ],
        ),
    ]
    out = build_network(studies, _plan(network_kind="sponsor_drug"))
    drug_nodes = {n["id"] for n in out["nodes"] if n["type"] == "drug"}
    assert drug_nodes == {"drugx"}
    drug_labels = {n["id"]: n["label"] for n in out["nodes"] if n["type"] == "drug"}
    assert drug_labels["drugx"] == "DrugX"


def test_bar_sex_dimension():
    studies = [
        _study(nct_id="NCT01", sex="ALL"),
        _study(nct_id="NCT02", sex="FEMALE"),
        _study(nct_id="NCT03", sex="FEMALE"),
        _study(nct_id="NCT04", sex=None),  # dropped
    ]
    out = build_bar(studies, _plan(group_by="sex"))
    by_key = {d["sex"]: d["trial_count"] for d in out["data"]}
    assert by_key == {"All": 1, "Female": 2}


def test_bar_study_type_and_sponsor_class():
    studies = [
        _study(study_type="INTERVENTIONAL", sponsor_class="INDUSTRY"),
        _study(study_type="OBSERVATIONAL", sponsor_class="OTHER"),
        _study(study_type="OBSERVATIONAL", sponsor_class="INDUSTRY"),
    ]
    out = build_bar(studies, _plan(group_by="study_type"))
    assert {d["study_type"]: d["trial_count"] for d in out["data"]} == {
        "Observational": 2,
        "Interventional": 1,
    }
    out = build_bar(studies, _plan(group_by="sponsor_class"))
    assert {d["sponsor_class"]: d["trial_count"] for d in out["data"]} == {
        "Industry": 2,
        "Other": 1,
    }


def test_time_series_quarter_and_month():
    studies = [
        _study(start_date="2020-03-15"),
        _study(start_date="2020-04-01"),
        _study(start_date="2020-05-20"),
        _study(start_date="2021-01-10"),
    ]
    out = build_time_series(studies, _plan(group_by="quarter"))
    by_key = {d["quarter"]: d["trial_count"] for d in out["data"]}
    assert by_key == {"2020-Q1": 1, "2020-Q2": 2, "2021-Q1": 1}

    out = build_time_series(studies, _plan(group_by="month"))
    by_key = {d["month"]: d["trial_count"] for d in out["data"]}
    assert by_key == {"2020-03": 1, "2020-04": 1, "2020-05": 1, "2021-01": 1}


def test_histogram_duration_months():
    # 1y, 2y, 3y, 5y studies
    studies = [
        _study(nct_id="NCT01", start_date="2020-01-01", completion_date="2021-01-01"),
        _study(nct_id="NCT02", start_date="2020-01-01", completion_date="2022-01-01"),
        _study(nct_id="NCT03", start_date="2020-01-01", completion_date="2023-01-01"),
        _study(nct_id="NCT04", start_date="2020-01-01", completion_date="2025-01-01"),
    ]
    out = build_histogram(studies, _plan(x_field="duration_months", bin_count=4))
    assert sum(d["trial_count"] for d in out["data"]) == 4
