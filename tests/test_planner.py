import os

import pytest

from app.planner import plan_query
from app.schemas import AnalyzeRequest


@pytest.fixture(autouse=True)
def stub_mode(monkeypatch):
    monkeypatch.setenv("STUB_LLM", "1")


def test_time_trend_query_picks_time_series():
    plan = plan_query(
        AnalyzeRequest(
            query="How has the number of trials for this drug changed per year since 2015?",
            drug_name="Pembrolizumab",
        )
    )
    assert plan.visualization_type == "time_series"
    assert plan.aggregation.group_by == "year"
    assert plan.filters.drug_name == "Pembrolizumab"


def test_distribution_query_picks_bar():
    plan = plan_query(
        AnalyzeRequest(
            query="How are diabetes trials distributed across phases?",
            condition="Diabetes",
        )
    )
    assert plan.visualization_type == "bar_chart"
    assert plan.aggregation.group_by == "phase"


def test_country_query_picks_bar_country():
    plan = plan_query(
        AnalyzeRequest(
            query="Which countries have the most recruiting trials?",
            status="RECRUITING",
        )
    )
    assert plan.visualization_type == "bar_chart"
    assert plan.aggregation.group_by == "country"
    assert plan.filters.status == "RECRUITING"


def test_network_query_picks_network():
    plan = plan_query(
        AnalyzeRequest(query="Show a network of sponsors and drugs for melanoma.",
                       condition="Melanoma")
    )
    assert plan.visualization_type == "network_graph"
    assert plan.aggregation.network_kind in {
        "sponsor_drug", "drug_condition", "drug_drug", "site_drug",
    }


def test_site_drug_query_picks_site_network():
    plan = plan_query(
        AnalyzeRequest(query="Show trial sites and drugs for melanoma.")
    )
    assert plan.visualization_type == "network_graph"
    assert plan.aggregation.network_kind == "site_drug"


def test_user_overrides_win():
    plan = plan_query(
        AnalyzeRequest(query="trials by phase", phase="PHASE3")
    )
    assert plan.filters.phase == "PHASE3"


def test_stub_extracts_status_from_query():
    """No structured `status` field, but query mentions 'recruiting'."""
    plan = plan_query(
        AnalyzeRequest(query="Which countries have the most recruiting trials?")
    )
    assert plan.filters.status == "RECRUITING"


def test_stub_extracts_condition_head_from_query():
    plan = plan_query(
        AnalyzeRequest(query="How many recruiting breast cancer trials are there?")
    )
    assert plan.filters.status == "RECRUITING"
    assert "cancer" in (plan.filters.condition or "").lower()


@pytest.mark.parametrize("query,expected", [
    ("Which countries have the most recruiting breast cancer trials?", "Breast Cancer"),
    ("completed trials by country for lung cancer", "Lung Cancer"),
    ("trials by phase for non-small cell lung cancer", "Non-Small Cell Lung Cancer"),
])
def test_stub_extracts_common_multiword_conditions(query, expected):
    plan = plan_query(AnalyzeRequest(query=query))
    assert plan.filters.condition == expected


def test_stub_extracts_condition_alias_from_query():
    plan = plan_query(
        AnalyzeRequest(query="trials by phase for NSCLC")
    )
    # NSCLC alias resolves to "Non-small cell lung cancer"
    assert "non-small cell lung cancer" in (plan.filters.condition or "").lower()


def test_stub_extracts_drug_alias_from_query():
    plan = plan_query(
        AnalyzeRequest(query="trials per year for keytruda since 2018")
    )
    assert (plan.filters.drug_name or "").lower() == "pembrolizumab"
    assert plan.filters.start_year == 2018


def test_stub_extracts_year_range_between():
    plan = plan_query(
        AnalyzeRequest(query="trials by phase between 2018 and 2022")
    )
    assert plan.filters.start_year == 2018
    assert plan.filters.end_year == 2022


def test_stub_extracts_phase_filter_from_query():
    plan = plan_query(
        AnalyzeRequest(query="How many Phase 3 recruiting trials by country?")
    )
    assert plan.aggregation.group_by == "country"
    assert plan.filters.phase == "PHASE3"
    assert plan.filters.status == "RECRUITING"


def test_stub_extracts_small_enum_filters_from_query():
    plan = plan_query(
        AnalyzeRequest(
            query=(
                "Does enrollment correlate with trial duration for "
                "industry-sponsored observational female-only biologic trials?"
            )
        )
    )
    assert plan.visualization_type == "scatter_plot"
    assert plan.filters.sponsor_class == "INDUSTRY"
    assert plan.filters.study_type == "OBSERVATIONAL"
    assert plan.filters.sex == "FEMALE"
    assert plan.filters.intervention_type == "BIOLOGICAL"


def test_chart_intent_wins_over_filter_keyword():
    """`recruiting breast cancer trials by phase` → bar by phase, not status."""
    plan = plan_query(
        AnalyzeRequest(query="recruiting breast cancer trials by phase")
    )
    assert plan.visualization_type == "bar_chart"
    assert plan.aggregation.group_by == "phase"
    # status keyword still extracts to filter
    assert plan.filters.status == "RECRUITING"
    assert "cancer" in (plan.filters.condition or "").lower()


def test_completed_trials_by_country():
    plan = plan_query(
        AnalyzeRequest(query="completed trials by country for diabetes")
    )
    assert plan.visualization_type == "bar_chart"
    assert plan.aggregation.group_by == "country"
    assert plan.filters.status == "COMPLETED"
    assert "diabetes" in (plan.filters.condition or "").lower()


@pytest.mark.parametrize("axis_phrase,expected_dim", [
    ("phase", "phase"),
    ("year", "year"),
    ("status", "overall_status"),
    ("country", "country"),
    ("sponsor class", "sponsor_class"),
])
def test_compare_axis_routes_grouped_bar(axis_phrase, expected_dim):
    """`compare X vs Y by <axis>` → grouped_bar with the requested axis."""
    plan = plan_query(AnalyzeRequest(
        query=f"Compare Pembrolizumab vs Nivolumab by {axis_phrase}",
    ))
    assert plan.visualization_type == "grouped_bar_chart"
    assert plan.aggregation.group_by == expected_dim
    assert plan.aggregation.series == "intervention_name"
    assert plan.aggregation.series_values == ["Pembrolizumab", "Nivolumab"]


def test_validate_plan_repairs_axis_when_llm_disagrees(monkeypatch):
    """A plan with the wrong axis must be repaired when the query is
    unambiguous, and the correction must be surfaced in
    query_interpretation so the response is auditable."""
    from app.planner import _validate_plan_intent
    from app.schemas import Aggregation, Filters, QueryPlan

    plan = QueryPlan(
        visualization_type="grouped_bar_chart",
        title="Phase distribution: Pembrolizumab vs Nivolumab",
        query_interpretation="Compare phase distribution.",
        filters=Filters(),
        aggregation=Aggregation(
            group_by="phase",
            series="intervention_name",
            series_values=["Pembrolizumab", "Nivolumab"],
        ),
    )
    repaired = _validate_plan_intent(
        plan,
        AnalyzeRequest(query="Compare Pembrolizumab vs Nivolumab by year"),
    )
    assert repaired.aggregation.group_by == "year"
    assert "axis repaired" in repaired.query_interpretation.lower()


def test_no_chart_intent_falls_back_to_status_distribution():
    """Filter-keyword fallback fires only when no chart shape mentioned."""
    plan = plan_query(
        AnalyzeRequest(query="recruiting trials")  # no "by ..." framing
    )
    assert plan.visualization_type == "bar_chart"
    assert plan.aggregation.group_by == "overall_status"
    assert plan.filters.status == "RECRUITING"


@pytest.mark.parametrize("query", [
    "Which drugs co-occur in combination studies?",
    "What drugs are used together in oncology trials?",
])
def test_drug_drug_cooccurrence_signals_pick_network(query):
    plan = plan_query(AnalyzeRequest(query=query))
    assert plan.visualization_type == "network_graph"
    assert plan.aggregation.network_kind == "drug_drug"


def test_compare_sponsor_categories_across_conditions():
    plan = plan_query(
        AnalyzeRequest(query="Compare sponsor categories across conditions")
    )
    assert plan.visualization_type == "grouped_bar_chart"
    assert plan.aggregation.group_by == "condition"
    assert plan.aggregation.series == "sponsor_class"


def test_compare_phases_across_sponsors():
    plan = plan_query(
        AnalyzeRequest(query="Compare phase distribution across sponsors")
    )
    assert plan.visualization_type == "grouped_bar_chart"
    # group_by = sponsor (the axis after "across")
    assert plan.aggregation.group_by == "lead_sponsor"
    # series = phase (the dim being compared)
    assert plan.aggregation.series == "phase"
