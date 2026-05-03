import pytest
from pydantic import ValidationError

from app.schemas import AnalyzeRequest


def test_phase_canonical_passes():
    r = AnalyzeRequest(query="x", phase="PHASE3")
    assert r.phase == "PHASE3"


def test_phase_synonyms_normalized():
    assert AnalyzeRequest(query="x", phase="Phase 3").phase == "PHASE3"
    assert AnalyzeRequest(query="x", phase="3").phase == "PHASE3"
    assert AnalyzeRequest(query="x", phase="III").phase == "PHASE3"
    assert AnalyzeRequest(query="x", phase="early phase 1").phase == "EARLY_PHASE1"


def test_phase_invalid_rejected():
    with pytest.raises(ValidationError):
        AnalyzeRequest(query="x", phase="not-a-phase")


def test_status_synonyms():
    assert AnalyzeRequest(query="x", status="recruiting").status == "RECRUITING"
    assert (
        AnalyzeRequest(query="x", status="Active, not recruiting").status
        == "ACTIVE_NOT_RECRUITING"
    )


def test_new_structured_filter_synonyms():
    r = AnalyzeRequest(
        query="x",
        sponsor_class="industry-sponsored",
        study_type="observational",
        sex="women",
        intervention_type="biologic",
    )
    assert r.sponsor_class == "INDUSTRY"
    assert r.study_type == "OBSERVATIONAL"
    assert r.sex == "FEMALE"
    assert r.intervention_type == "BIOLOGICAL"


def test_new_structured_filter_invalid_rejected():
    with pytest.raises(ValidationError):
        AnalyzeRequest(query="x", sponsor_class="not-a-sponsor-class")
    with pytest.raises(ValidationError):
        AnalyzeRequest(query="x", study_type="randomized")  # not a CT.gov enum
    with pytest.raises(ValidationError):
        AnalyzeRequest(query="x", sex="other")
    with pytest.raises(ValidationError):
        AnalyzeRequest(query="x", intervention_type="robot")


def test_status_invalid_rejected():
    with pytest.raises(ValidationError):
        AnalyzeRequest(query="x", status="bogus")


def test_empty_query_rejected():
    with pytest.raises(ValidationError):
        AnalyzeRequest(query="")


def test_max_studies_bounds():
    with pytest.raises(ValidationError):
        AnalyzeRequest(query="x", max_studies=0)
    with pytest.raises(ValidationError):
        AnalyzeRequest(query="x", max_studies=10000)


def test_year_bounds():
    with pytest.raises(ValidationError):
        AnalyzeRequest(query="x", start_year=1800)


def test_year_range_inverted_rejected():
    with pytest.raises(ValidationError) as exc:
        AnalyzeRequest(query="x", start_year=2025, end_year=2020)
    assert "start_year" in str(exc.value)


def test_year_range_equal_ok():
    r = AnalyzeRequest(query="x", start_year=2020, end_year=2020)
    assert r.start_year == r.end_year == 2020


def test_filters_year_range_auto_repaired():
    """If the planner emits inverted years, Filters silently repairs them."""
    from app.schemas import Filters
    f = Filters(start_year=2025, end_year=2020)
    assert (f.start_year, f.end_year) == (2020, 2025)


def test_visualization_spec_is_discriminated_union():
    """AnalyzeResponse.visualization is a tagged union — providing the wrong
    payload shape for a given `type` must fail validation."""
    from app.schemas import (
        AnalyzeResponse, BarChartSpec, Encoding, Meta, NetworkGraphSpec,
    )

    bar = BarChartSpec(
        title="Trials by Phase",
        encoding=Encoding(
            x={"field": "phase", "type": "nominal"},
            y={"field": "trial_count", "type": "quantitative"},
        ),
        data=[{"phase": "Phase 2", "trial_count": 1, "citations": []}],
    )
    meta = Meta(filters_applied={}, query_interpretation="i")
    AnalyzeResponse(visualization=bar, meta=meta)  # accepts bar

    network = NetworkGraphSpec(
        title="Sponsor ↔ Drug",
        encoding=Encoding(
            nodes={"id": "id", "label": "label", "type": "type"},
            edges={"source": "source", "target": "target", "weight": "weight"},
        ),
        nodes=[{"id": "merck", "label": "Merck", "type": "sponsor"}],
        edges=[{
            "source": "merck", "target": "pembro", "weight": 1,
            "trial_count": 1,
        }],
    )
    AnalyzeResponse(visualization=network, meta=meta)  # accepts network


def test_bar_chart_spec_rejects_nodes_edges_payload():
    """A bar_chart can't sneak in network-shape fields."""
    from app.schemas import BarChartSpec, Encoding

    with pytest.raises(ValidationError):
        BarChartSpec.model_validate({
            "type": "bar_chart",
            "title": "x",
            "encoding": Encoding(
                x={"field": "phase"}, y={"field": "trial_count"},
            ).model_dump(),
            "data": [{"phase": "Phase 2", "trial_count": 1}],
            "nodes": [],
            "edges": [],
        })


def test_typed_datum_rejects_missing_trial_count():
    """Each datum row is now a typed model — missing required fields fail
    at validation time instead of leaking through as untyped dicts."""
    from app.schemas import BarChartSpec, Encoding

    with pytest.raises(ValidationError):
        BarChartSpec.model_validate({
            "type": "bar_chart", "title": "x",
            "encoding": Encoding(
                x={"field": "phase"}, y={"field": "trial_count"},
            ).model_dump(),
            "data": [{"phase": "Phase 2"}],  # missing trial_count
        })


def test_typed_datum_preserves_dim_key_field():
    """The dim-key field (phase / country / sponsor / …) is dynamic; it
    flows through `model_extra` and round-trips through model_dump()."""
    from app.schemas import BarChartSpec, Encoding

    spec = BarChartSpec.model_validate({
        "type": "bar_chart", "title": "Trials by Country",
        "encoding": Encoding(
            x={"field": "country"}, y={"field": "trial_count"},
        ).model_dump(),
        "data": [
            {"country": "United States", "trial_count": 5, "citations": []},
            {"country": "Germany", "trial_count": 2, "citations": []},
        ],
    })
    dumped = spec.model_dump()
    countries = [d["country"] for d in dumped["data"]]
    assert countries == ["United States", "Germany"]


def test_typed_histogram_datum_requires_bin_bounds():
    from app.schemas import HistogramSpec, Encoding

    with pytest.raises(ValidationError):
        HistogramSpec.model_validate({
            "type": "histogram", "title": "x",
            "encoding": Encoding(
                x={"field": "bin"}, y={"field": "trial_count"},
            ).model_dump(),
            "data": [{"trial_count": 3}],  # missing bin / bin_start / bin_end
        })


def test_visualization_union_rejects_unknown_type():
    from app.schemas import AnalyzeResponse, Meta

    meta = Meta(filters_applied={}, query_interpretation="i")
    with pytest.raises(ValidationError):
        AnalyzeResponse.model_validate({
            "visualization": {
                "type": "pie_chart",  # not a valid discriminator
                "title": "x", "encoding": {}, "data": [],
            },
            "meta": meta.model_dump(),
        })


def test_chart_specs_require_xy_encoding():
    from app.schemas import BarChartSpec, Encoding

    with pytest.raises(ValidationError):
        BarChartSpec.model_validate({
            "type": "bar_chart",
            "title": "x",
            "encoding": Encoding(x={"field": "phase"}).model_dump(),
            "data": [{"phase": "Phase 2", "trial_count": 1}],
        })


def test_grouped_bar_requires_series_encoding():
    from app.schemas import Encoding, GroupedBarChartSpec

    with pytest.raises(ValidationError):
        GroupedBarChartSpec.model_validate({
            "type": "grouped_bar_chart",
            "title": "x",
            "encoding": Encoding(
                x={"field": "phase"}, y={"field": "trial_count"},
            ).model_dump(),
            "data": [{
                "phase": "Phase 2", "intervention_name": "DrugA",
                "trial_count": 1,
            }],
        })


def test_network_requires_node_edge_encoding():
    from app.schemas import Encoding, NetworkGraphSpec

    with pytest.raises(ValidationError):
        NetworkGraphSpec.model_validate({
            "type": "network_graph",
            "title": "x",
            "encoding": Encoding(nodes={"id": "id"}).model_dump(),
            "nodes": [{"id": "a", "label": "A", "type": "site"}],
            "edges": [{
                "source": "a", "target": "b", "weight": 1,
                "trial_count": 1,
            }],
        })


def test_encoding_channels_are_typed_and_serialize_to_original_shape():
    from app.schemas import Channel, Encoding

    enc = Encoding(
        x={"field": "phase", "type": "nominal"},
        y={"field": "trial_count", "type": "quantitative"},
        nodes={"id": "id", "label": "label", "type": "type"},
    )

    dumped = enc.model_dump()
    assert dumped["x"] == {"field": "phase", "type": "nominal"}
    assert dumped["y"] == {"field": "trial_count", "type": "quantitative"}
    assert dumped["nodes"] == {"id": "id", "label": "label", "type": "type"}

    with pytest.raises(ValidationError):
        Channel(field="phase", typo="not allowed")


def test_aggregation_bin_count_bounds():
    from app.schemas import Aggregation

    with pytest.raises(ValidationError):
        Aggregation(bin_count=1)
    with pytest.raises(ValidationError):
        Aggregation(bin_count=51)
