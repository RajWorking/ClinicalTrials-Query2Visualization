import pytest

from app.planner import plan_query
from app.schemas import AnalyzeRequest


@pytest.fixture(autouse=True)
def stub_mode(monkeypatch):
    monkeypatch.setenv("STUB_LLM", "1")


def test_off_topic_query_gets_safe_default_warning():
    plan = plan_query(AnalyzeRequest(query="What is the weather tomorrow?"))
    assert plan.visualization_type == "bar_chart"
    assert plan.aggregation.group_by == "phase"
    assert plan.notes and plan.notes.startswith("fallback:")
    assert "outside the clinical-trials domain" in plan.notes


def test_trial_query_with_off_topic_word_still_plans_normally():
    plan = plan_query(AnalyzeRequest(query="weather effects in asthma trials by phase"))
    assert plan.visualization_type == "bar_chart"
    assert plan.aggregation.group_by == "phase"
    assert plan.notes is None
