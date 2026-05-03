from app.nl_extract import (
    detect_compare_axis,
    extract_filters_from_query,
    is_obviously_off_topic,
    network_kind_for,
)
from app.schemas import AnalyzeRequest


def test_extracts_common_condition_phrases():
    req = AnalyzeRequest(query="Which countries have recruiting breast cancer trials?")
    assert extract_filters_from_query(req, req.query.lower())["condition"] == "Breast Cancer"

    req = AnalyzeRequest(query="trials by phase for non-small cell lung cancer")
    assert (
        extract_filters_from_query(req, req.query.lower())["condition"]
        == "Non-Small Cell Lung Cancer"
    )


def test_extracts_initiated_since_year():
    req = AnalyzeRequest(query="trials initiated since 2015 for melanoma")
    inferred = extract_filters_from_query(req, req.query.lower())
    assert inferred["start_year"] == 2015
    assert inferred["condition"] == "Melanoma"


def test_compare_axis_and_network_kind_routing():
    assert detect_compare_axis("compare pembro vs nivo by status") == "overall_status"
    assert detect_compare_axis("compare pembro vs nivo across sponsor class") == "sponsor_class"
    assert network_kind_for("show trial sites and drugs for melanoma") == "site_drug"
    assert network_kind_for("which drugs co-occur in combination studies") == "drug_drug"


def test_off_topic_guard_is_conservative():
    assert is_obviously_off_topic(AnalyzeRequest(query="what is the weather tomorrow?"))
    assert not is_obviously_off_topic(AnalyzeRequest(query="weather effects in asthma trials"))
    assert not is_obviously_off_topic(
        AnalyzeRequest(query="what is the weather tomorrow?", condition="Asthma")
    )
