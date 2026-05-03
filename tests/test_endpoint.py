"""End-to-end integration tests against /analyze with a mocked CT.gov client."""
from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ["STUB_LLM"] = "1"  # tests don't need an OpenAI key

from app import main as main_module  # noqa: E402
from app.schemas import Filters  # noqa: E402


def _study(nct: str, **over: Any) -> dict:
    base = {
        "nct_id": nct, "brief_title": f"Study {nct}", "brief_summary": "Summary",
        "phases": ["PHASE2"], "study_type": "INTERVENTIONAL", "sex": "ALL",
        "overall_status": "RECRUITING",
        "start_date": "2020-05-01", "completion_date": "2022-05-01",
        "enrollment_count": 100, "lead_sponsor": "Acme",
        "sponsor_class": "INDUSTRY", "conditions": ["Cancer"],
        "interventions": [{"name": "DrugA", "type": "DRUG"}],
        "intervention_names": ["DrugA"], "intervention_types": ["DRUG"],
        "countries": ["United States"],
    }
    base.update(over)
    if "interventions" in over and "intervention_names" not in over:
        base["intervention_names"] = [i["name"] for i in base["interventions"]]
    return base


CORPUS = [
    _study("NCT01", phases=["PHASE1"], lead_sponsor="Merck",
           interventions=[{"name": "Pembro", "type": "DRUG"}],
           start_date="2018-01-15", countries=["United States"]),
    _study("NCT02", phases=["PHASE2"], lead_sponsor="Merck",
           interventions=[{"name": "Pembro", "type": "DRUG"},
                          {"name": "Chemo", "type": "DRUG"}],
           start_date="2019-04-15", countries=["Germany", "United States"]),
    _study("NCT03", phases=["PHASE3"], lead_sponsor="Roche",
           interventions=[{"name": "Atezo", "type": "DRUG"}],
           start_date="2020-09-01", overall_status="COMPLETED",
           countries=["Japan"]),
    _study("NCT04", phases=["PHASE3"], lead_sponsor="Pfizer",
           interventions=[{"name": "Atezo", "type": "DRUG"},
                          {"name": "Pembro", "type": "DRUG"}],
           start_date="2021-02-10", overall_status="COMPLETED",
           sex="FEMALE", enrollment_count=50,
           countries=["United States", "United Kingdom"]),
]


class FakeClient:
    def __init__(self, *_a, **_k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def search_studies(
        self, filters: Filters, max_studies: int = 500, **_k
    ) -> tuple[list[dict], int]:
        sel = list(CORPUS)
        if filters.drug_name:
            d = filters.drug_name.lower()
            sel = [s for s in sel if any(d in n.lower() for n in s["intervention_names"])]
        if filters.condition:
            c = filters.condition.lower()
            sel = [s for s in sel if any(c in cd.lower() for cd in s["conditions"])]
        if filters.phase:
            sel = [s for s in sel if filters.phase in s["phases"]]
        if filters.status:
            sel = [s for s in sel if s["overall_status"] == filters.status]
        if filters.country:
            cn = filters.country.lower()
            sel = [s for s in sel if any(cn in c.lower() for c in s["countries"])]
        if filters.start_year:
            sel = [
                s for s in sel
                if s.get("start_date") and int(s["start_date"][:4]) >= filters.start_year
            ]
        if filters.end_year:
            sel = [
                s for s in sel
                if s.get("start_date") and int(s["start_date"][:4]) <= filters.end_year
            ]
        return sel[:max_studies], len(sel)

    async def count_for_filters(self, filters: Filters) -> int:
        sel, total = await self.search_studies(filters, max_studies=1)
        return total

    async def ids_for_filters(
        self, filters: Filters, max_ids: int = 5000, page_size: int = 1000
    ) -> tuple[set[str], int, bool]:
        sel, total = await self.search_studies(filters, max_studies=max_ids)
        return {s["nct_id"] for s in sel}, total, total > len(sel)


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(main_module, "CTGovClient", FakeClient)
    return TestClient(main_module.app)


# ---------------------------------------------------------------------------
# tests

def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_bar_phase_uses_exact_count_path(client):
    r = client.post("/analyze", json={"query": "phase distribution"})
    assert r.status_code == 200
    body = r.json()
    assert body["visualization"]["type"] == "bar_chart"
    # exact count path: not sampled
    assert body["meta"]["truncated"] is False
    by_phase = {
        d["phase"]: d["trial_count"] for d in body["visualization"]["data"]
    }
    assert by_phase["Phase 3"] == 2
    assert all(d["sampled"] is False for d in body["visualization"]["data"])
    # citations present
    assert all(d["citations"] for d in body["visualization"]["data"])


def test_time_series_path(client):
    r = client.post(
        "/analyze",
        json={
            "query": "How has the number of trials changed each year?",
            "start_year": 2018,
            "end_year": 2021,
        },
    )
    body = r.json()
    assert body["visualization"]["type"] == "time_series"
    years = {d["year"]: d["trial_count"] for d in body["visualization"]["data"]}
    assert years == {"2018": 1, "2019": 1, "2020": 1, "2021": 1}
    # Per-year fan-out → not sampled.
    assert body["meta"]["truncated"] is False
    assert all(d["sampled"] is False for d in body["visualization"]["data"])


def test_country_bar(client):
    r = client.post(
        "/analyze",
        json={"query": "Which countries have the most trials?", "max_studies": 50},
    )
    body = r.json()
    assert body["visualization"]["type"] == "bar_chart"
    by_country = {
        d["country"]: d["trial_count"] for d in body["visualization"]["data"]
    }
    assert by_country["United States"] == 3


def test_grouped_bar_compare(client):
    r = client.post(
        "/analyze",
        json={"query": "Compare Pembro vs Atezo by phase."},
    )
    body = r.json()
    assert body["visualization"]["type"] == "grouped_bar_chart"
    series = sorted({d["intervention_name"] for d in body["visualization"]["data"]})
    assert series == ["Atezo", "Pembro"]


def test_network_sponsor_drug(client):
    r = client.post(
        "/analyze",
        json={"query": "Show a network of sponsors and drugs."},
    )
    body = r.json()
    assert body["visualization"]["type"] == "network_graph"
    edges = body["visualization"]["edges"]
    # Drug node IDs are canonicalized (lowercased).
    assert any(
        e["source"] == "Merck" and e["target"] == "pembro" and e["weight"] == 2
        for e in edges
    )


def test_invalid_phase_rejected(client):
    r = client.post("/analyze", json={"query": "x", "phase": "not-a-phase"})
    assert r.status_code == 422


def test_phase_synonym_accepted(client):
    r = client.post(
        "/analyze",
        json={"query": "phase distribution", "phase": "Phase 3"},
    )
    assert r.status_code == 200
    assert r.json()["meta"]["filters_applied"]["phase"] == "PHASE3"


def test_same_dim_filter_not_overwritten_by_fanout(client):
    """Regression: phase=PHASE3 + group_by=phase must yield only Phase 3."""
    r = client.post(
        "/analyze",
        json={"query": "phase distribution", "phase": "PHASE3"},
    )
    assert r.status_code == 200
    body = r.json()
    phases = {d["phase"] for d in body["visualization"]["data"]}
    assert phases == {"Phase 3"}, f"unexpected phases in result: {phases}"
    assert body["meta"]["filters_applied"]["phase"] == "PHASE3"


def test_same_dim_status_filter_not_overwritten(client):
    r = client.post(
        "/analyze",
        json={"query": "trials by status", "status": "RECRUITING"},
    )
    assert r.status_code == 200
    body = r.json()
    statuses = {d["overall_status"] for d in body["visualization"]["data"]}
    assert statuses == {"Recruiting"}


def test_sampled_flag_when_truncated(monkeypatch, client):
    """Truncation only occurs when total > EXACT_PAGINATE_CAP. Force it
    by mocking a much-larger corpus than the paginate-all ceiling."""
    big_corpus = CORPUS * 700  # 2800 studies > 2000 cap

    class BigClient(FakeClient):
        async def search_studies(self, filters, max_studies=500, **_k):
            return big_corpus[:max_studies], len(big_corpus)

        async def count_for_filters(self, *_a, **_k):
            return len(big_corpus)

    monkeypatch.setattr(main_module, "CTGovClient", BigClient)

    r = client.post(
        "/analyze",
        json={
            "query": "Which countries have the most trials?",
            "max_studies": 200,
        },
    )
    body = r.json()
    assert body["meta"]["truncated"] is True
    assert "(sampled)" in body["visualization"]["title"]
    for d in body["visualization"]["data"]:
        assert d["sampled"] is True
        assert "estimated_total" not in d  # no biased extrapolation
    assert any("sampled" in w.lower() for w in body["meta"]["warnings"])


def test_paginate_all_when_total_below_cap(client):
    """When matched total fits below the paginate-all cap, no sampling."""
    r = client.post(
        "/analyze",
        json={
            "query": "Which countries have the most trials?",
            "max_studies": 2,  # user asked for 2, but total is 4 → fetch all 4
        },
    )
    body = r.json()
    assert body["meta"]["truncated"] is False
    assert body["meta"]["studies_used"] == 4


def test_planner_fallback_warning_surfaced(monkeypatch, client):
    """When the planner falls back, the response must say so."""
    from app import planner

    def boom(_req):
        raise RuntimeError("forced stub error")

    monkeypatch.setattr(planner, "_stub_plan", boom)
    r = client.post("/analyze", json={"query": "uninterpretable nonsense"})
    assert r.status_code == 200
    body = r.json()
    assert any("fallback" in w.lower() or "default" in w.lower()
               for w in body["meta"]["warnings"])


def test_citation_excerpt_references_supporting_field(client):
    """A phase=Phase 3 datum's citation should mention the phase field."""
    r = client.post(
        "/analyze",
        json={"query": "phase distribution", "max_studies": 50},
    )
    body = r.json()
    for d in body["visualization"]["data"]:
        for c in d["citations"]:
            assert "phases" in c["excerpt"].lower() or "PHASE" in c["excerpt"].upper()


def test_data_includes_supporting_nct_ids_and_citation_count(client):
    """Every datum exposes the same two fields, plus a flag indicating
    whether the ID list is complete (aggregator paths) or a citation
    sample (exact-count paths)."""
    r = client.post("/analyze", json={"query": "phase distribution"})
    body = r.json()
    for d in body["visualization"]["data"]:
        assert "supporting_nct_ids" in d
        assert "supporting_nct_ids_complete" in d
        assert "citation_count" in d
        assert isinstance(d["supporting_nct_ids"], list)
        assert len(d["citations"]) <= 3  # capped for payload size
        assert d["citation_count"] == d["trial_count"]
    # Path A is exact-count → IDs are a citation sample, not complete
    assert body["visualization"]["data"][0]["supporting_nct_ids_complete"] is False


def test_aggregator_path_returns_complete_supporting_ids(client):
    """High-cardinality dim (country) goes through Path C — IDs are
    complete given the fetch window."""
    r = client.post(
        "/analyze",
        json={"query": "Which countries have the most trials?"},
    )
    body = r.json()
    for d in body["visualization"]["data"]:
        assert d["supporting_nct_ids_complete"] is True
        assert d["citation_count"] == len(d["supporting_nct_ids"])


def test_grouped_compare_distinct_total_uses_union(client):
    """distinct_total = |union(IDs)| across compared series, not max."""
    r = client.post(
        "/analyze",
        json={"query": "Compare Pembro vs Atezo by phase."},
    )
    body = r.json()
    pst = body["meta"]["per_series_totals"]
    # Our test corpus has 4 trials; Pembro in 3 (NCT01, NCT02, NCT04),
    # Atezo in 2 (NCT03, NCT04). Union = {NCT01, NCT02, NCT03, NCT04} = 4.
    # Sum = 3 + 2 = 5; max = 3. Union (4) > max(per_series).
    assert pst == {"Pembro": 3, "Atezo": 2}
    assert body["meta"]["total_studies_matched"] == 4


def test_citations_have_url_and_source_field(client):
    r = client.post(
        "/analyze",
        json={"query": "phase distribution", "max_studies": 50},
    )
    body = r.json()
    seen_phase_path = False
    for d in body["visualization"]["data"]:
        for c in d["citations"]:
            assert c["url"].startswith("https://clinicaltrials.gov/study/")
            assert c["url"].endswith(c["nct_id"])
            assert c["source_field"]
            if "designModule.phases" in c["source_field"]:
                seen_phase_path = True
    assert seen_phase_path, "expected at least one citation to point at the phases field"


def test_grouped_bar_uses_exact_fanout(client):
    """Comparison must use exact per-cell counts (no sampling)."""
    r = client.post(
        "/analyze",
        json={"query": "Compare Pembro vs Atezo by phase."},
    )
    body = r.json()
    assert body["visualization"]["type"] == "grouped_bar_chart"
    # exact path → no sampling, all data points marked sampled=False
    assert body["meta"]["truncated"] is False
    for d in body["visualization"]["data"]:
        assert d["sampled"] is False
    # per-series totals reported
    assert body["meta"]["per_series_totals"]
    assert set(body["meta"]["per_series_totals"].keys()) == {"Pembro", "Atezo"}


def test_network_meta_reports_caps(monkeypatch, client):
    """30 sponsors × 30 drugs × 3 trials = 900 weight-3 edges → exceeds the 200 cap."""
    big_corpus = [
        _study(
            f"NCT{i:05d}_{rep}", brief_title=f"Trial {i}/{rep}",
            lead_sponsor=f"Sponsor{i // 30}",
            interventions=[{"name": f"Drug{i % 30}", "type": "DRUG"}],
            intervention_mesh=[],
        )
        for i in range(900) for rep in range(3)
    ]

    class BigClient(FakeClient):
        async def search_studies(self, *_a, max_studies=500, **_k):
            return big_corpus[:max_studies], len(big_corpus)

        async def count_for_filters(self, *_a, **_k):
            return len(big_corpus)

    monkeypatch.setattr(main_module, "CTGovClient", BigClient)
    r = client.post("/analyze", json={"query": "sponsor drug network", "max_studies": 800})
    body = r.json()
    assert body["visualization"]["type"] == "network_graph"
    meta = body["meta"]
    assert meta["edges_returned"] == 200
    assert meta["edges_total"] >= 200
    assert any("truncated" in w.lower() for w in meta["warnings"])


def test_upstream_error_returns_502(monkeypatch, client):
    from app.ctgov import CTGovError

    class BoomClient(FakeClient):
        async def search_studies(self, *_a, **_k):
            raise CTGovError("upstream unavailable", status_code=503)

        async def count_for_filters(self, *_a, **_k):
            raise CTGovError("upstream unavailable", status_code=503)

    monkeypatch.setattr(main_module, "CTGovClient", BoomClient)
    r = client.post("/analyze", json={"query": "trials by phase"})
    assert r.status_code == 502
    assert "upstream" in r.json()["error"].lower()
