"""Regression tests for gaps that previously lowered the assignment score."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.planner import plan_query
from app.schemas import AnalyzeRequest

from ._helpers import make_fake_client_class, make_study


def _study(nct: str, *, country: str = "United States", **over: Any) -> dict:
    return make_study(nct, countries=[country], **over)


def test_country_query_extracts_breast_cancer_filter(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STUB_LLM", "1")

    plan = plan_query(
        AnalyzeRequest(
            query="Which countries have the most recruiting breast cancer trials?"
        )
    )

    assert plan.visualization_type == "bar_chart"
    assert plan.aggregation.group_by == "country"
    assert plan.filters.status == "RECRUITING"
    assert plan.filters.condition == "Breast Cancer"


def test_compare_sponsor_categories_across_conditions_stays_grouped_bar(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("STUB_LLM", "1")

    corpus = [
        _study("NCT01", conditions=["Cancer"], sponsor_class="INDUSTRY"),
        _study("NCT02", conditions=["Cancer"], sponsor_class="OTHER"),
        _study("NCT03", conditions=["Diabetes"], sponsor_class="INDUSTRY"),
    ]
    monkeypatch.setattr(main_module, "CTGovClient",
                        make_fake_client_class(corpus))
    client = TestClient(main_module.app)

    response = client.post(
        "/analyze",
        json={"query": "Compare sponsor categories across conditions"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["visualization"]["type"] == "grouped_bar_chart"
    assert body["visualization"]["encoding"]["series"]["field"] == "sponsor_class"
    assert {
        (row["condition"], row["sponsor_class"])
        for row in body["visualization"]["data"]
    } == {
        ("Cancer", "Industry"),
        ("Cancer", "Other"),
        ("Diabetes", "Industry"),
    }


def test_country_top_n_uses_exact_global_counts_not_sample_window(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("STUB_LLM", "1")

    first_window = [
        _study(f"NCTUS{i:04d}", country="United States") for i in range(2000)
    ]
    later_true_top = [
        _study(f"NCTCA{i:04d}", country="Canada") for i in range(2500)
    ]
    corpus = first_window + later_true_top
    monkeypatch.setattr(main_module, "CTGovClient",
                        make_fake_client_class(corpus))
    client = TestClient(main_module.app)

    response = client.post(
        "/analyze",
        json={"query": "Which countries have the most trials?", "max_studies": 10},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["meta"]["truncated"] is False
    assert body["visualization"]["data"][0]["country"] == "Canada"
    assert body["visualization"]["data"][0]["trial_count"] == 2500
