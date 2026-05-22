"""Test the OpenAI planner path with a mocked client.

Verifies:
  - the SDK call shape (system prompt + user payload + json_schema)
  - the response is validated through QueryPlan
  - first-attempt failure triggers a repair retry with stricter prompt
  - persistent failure raises PlannerError (no silent fallback)
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app import planner
from app.plan_verifier import PlannerError
from app.schemas import AnalyzeRequest


@pytest.fixture
def fake_openai(monkeypatch):
    """Builds a configurable fake OpenAI client and installs it in the SDK."""
    state = {"calls": [], "responses": [], "client_kwargs": []}

    class FakeCompletions:
        def create(self, **kwargs):
            state["calls"].append(kwargs)
            r = state["responses"].pop(0)
            if isinstance(r, Exception):
                raise r
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=r))]
            )

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, *_, **kwargs):
            state["client_kwargs"].append(kwargs)
            self.chat = FakeChat()

    # Patch the SDK class lookup inside _openai_plan.
    fake_module = SimpleNamespace(OpenAI=FakeOpenAI)
    monkeypatch.setitem(__import__("sys").modules, "openai", fake_module)
    return state


VALID_PLAN_JSON = json.dumps({
    "visualization_type": "bar_chart",
    "title": "Trials by phase",
    "query_interpretation": "Distribute trials by phase.",
    "filters": {
        "drug_name": "Pembrolizumab",
        "condition": None, "sponsor": None, "country": None,
        "free_text": None, "phase": None, "status": None,
        "sponsor_class": None, "study_type": None,
        "sex": None, "intervention_type": None,
        "start_year": None, "end_year": None,
    },
    "aggregation": {
        "group_by": "phase", "series": None, "metric": "count",
        "x_field": None, "y_field": None, "bin_count": 10,
        "network_kind": None, "series_values": None,
    },
    "notes": None,
})


def test_openai_planner_happy_path(fake_openai):
    fake_openai["responses"].append(VALID_PLAN_JSON)

    plan = planner.plan_query(
        AnalyzeRequest(query="phases for pembrolizumab", drug_name="Pembrolizumab")
    )
    assert plan.visualization_type == "bar_chart"
    assert plan.aggregation.group_by == "phase"
    assert plan.filters.drug_name == "Pembrolizumab"

    # Verify the call shape.
    [call] = fake_openai["calls"]
    assert call["response_format"]["type"] == "json_schema"
    assert call["response_format"]["json_schema"]["name"] == "QueryPlan"
    sys_prompt = call["messages"][0]["content"]
    assert "QueryPlan" in sys_prompt or "ClinicalTrials" in sys_prompt
    user_payload = json.loads(call["messages"][1]["content"])
    assert user_payload["query"] == "phases for pembrolizumab"


def test_openrouter_api_key_and_base_url(fake_openai, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    fake_openai["responses"].append(VALID_PLAN_JSON)

    planner.plan_query(AnalyzeRequest(query="phases for pembrolizumab"))

    [client_kwargs] = fake_openai["client_kwargs"]
    assert client_kwargs["api_key"] == "sk-or-v1-test"
    assert client_kwargs["base_url"] == "https://openrouter.ai/api/v1"
    [call] = fake_openai["calls"]
    assert call["model"] == "openai/gpt-4o-mini"


def test_openai_planner_repair_on_first_failure(fake_openai):
    """First call returns malformed JSON; repair attempt fixes it."""
    fake_openai["responses"].extend([
        "{not json",        # first call → ValidationError
        VALID_PLAN_JSON,    # repair attempt → success
    ])
    plan = planner.plan_query(AnalyzeRequest(query="phases for pembrolizumab"))
    assert plan.visualization_type == "bar_chart"
    # Second call must include repair_hint in system prompt.
    sys_prompt_2 = fake_openai["calls"][1]["messages"][0]["content"]
    assert "REPAIR ATTEMPT" in sys_prompt_2
    assert "PHASE3" in sys_prompt_2  # canonical-value reminder is in the static hint


def test_openai_planner_two_failures_raises(fake_openai):
    """Two invalid model payloads raise PlannerError — no silent fallback."""
    fake_openai["responses"].extend([
        "{not json",
        "{still not json",
    ])
    with pytest.raises(PlannerError, match="invalid plan"):
        planner.plan_query(AnalyzeRequest(query="something weird", start_year=2020))


def test_openai_provider_error_raises_without_mock_response(fake_openai):
    """Provider/API failures, e.g. 401s, must not fall back to mock data."""
    fake_openai["responses"].append(RuntimeError("401 unauthorized"))

    with pytest.raises(PlannerError, match="401 unauthorized"):
        planner.plan_query(AnalyzeRequest(query="phases for pembrolizumab"))

    assert len(fake_openai["calls"]) == 1


def test_filters_phase_validation_rejects_garbage_from_planner():
    """Even if the planner returns 'phase 9000', Filters validation cleans up."""
    from app.schemas import Filters
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Filters(phase="phase 9000")


def test_filters_phase_synonyms_normalized_in_planner_output():
    """LLM might emit 'Phase 3' / 'III' — Filters must canonicalize."""
    from app.schemas import Filters

    assert Filters(phase="Phase 3").phase == "PHASE3"
    assert Filters(phase="III").phase == "PHASE3"
    assert Filters(status="recruiting").status == "RECRUITING"
