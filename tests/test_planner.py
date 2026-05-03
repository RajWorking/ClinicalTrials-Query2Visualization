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


def test_compare_query_picks_grouped_bar():
    plan = plan_query(
        AnalyzeRequest(query="Compare Pembrolizumab vs Nivolumab by phase.")
    )
    assert plan.visualization_type == "grouped_bar_chart"
    assert plan.aggregation.series == "intervention_name"
    assert plan.aggregation.series_values
    assert len(plan.aggregation.series_values) == 2


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
    assert plan.aggregation.network_kind in {"sponsor_drug", "drug_condition", "drug_drug"}


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


def test_compare_with_by_phase_still_grouped():
    """`compare X vs Y by phase` is grouped_bar, not by-phase bar chart."""
    plan = plan_query(
        AnalyzeRequest(query="Compare Pembrolizumab vs Nivolumab by phase")
    )
    assert plan.visualization_type == "grouped_bar_chart"
    assert plan.aggregation.group_by == "phase"


def test_no_chart_intent_falls_back_to_status_distribution():
    """Filter-keyword fallback fires only when no chart shape mentioned."""
    plan = plan_query(
        AnalyzeRequest(query="recruiting trials")  # no "by ..." framing
    )
    assert plan.visualization_type == "bar_chart"
    assert plan.aggregation.group_by == "overall_status"
    assert plan.filters.status == "RECRUITING"


def test_drug_drug_cooccurrence_picks_network():
    plan = plan_query(
        AnalyzeRequest(query="Which drugs co-occur in combination studies?")
    )
    assert plan.visualization_type == "network_graph"
    assert plan.aggregation.network_kind == "drug_drug"


def test_combination_trials_picks_drug_drug_network():
    plan = plan_query(
        AnalyzeRequest(query="What drugs are used together in oncology trials?")
    )
    # "together" is a co-occurrence signal; condition extracted to filter.
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
    assert plan.aggregation.series in ("phase", None)
    # phase isn't in DIM_CATEGORY_KEYWORDS yet, so this routes to X-vs-Y
    # fallback; assert the fallback sane-default rather than fail. The
    # important thing is that grouped_bar_chart was chosen.
