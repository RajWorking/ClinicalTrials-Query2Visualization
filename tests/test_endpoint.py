"""End-to-end integration tests against /analyze with a mocked CT.gov client."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from ._helpers import (
    FakeCTGovClient, bar_plan, grouped_compare_plan, histogram_plan,
    make_fake_client_class, make_fixed_corpus_client, make_study as _study,
    network_plan, plan_query_for, scatter_plan, time_series_plan,
)


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


FakeClient = make_fake_client_class(CORPUS)


@pytest.fixture
def set_plan(monkeypatch):
    def _set(plan):
        monkeypatch.setattr(main_module, "plan_query", plan_query_for(plan))
    return _set


@pytest.fixture
def client(monkeypatch, set_plan) -> TestClient:
    monkeypatch.setattr(main_module, "CTGovClient", FakeClient)
    set_plan(bar_plan("phase"))
    return TestClient(main_module.app)


# ---------------------------------------------------------------------------
# tests

def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_planner_error_returns_502_without_visualization(monkeypatch, client):
    def boom(_req):
        raise main_module.PlannerError("401 unauthorized")

    monkeypatch.setattr(main_module, "plan_query", boom)
    r = client.post("/analyze", json={"query": "phase distribution"})

    assert r.status_code == 502
    body = r.json()
    assert "visualization" not in body
    assert "401 unauthorized" in body["detail"]


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


def test_time_series_path(client, set_plan):
    set_plan(time_series_plan())
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


def test_time_series_zero_fills_missing_years(client, set_plan):
    set_plan(time_series_plan())
    r = client.post(
        "/analyze",
        json={
            "query": "How has the number of trials changed each year?",
            "start_year": 2017,
            "end_year": 2021,
        },
    )
    body = r.json()
    years = {d["year"]: d for d in body["visualization"]["data"]}
    assert list(years) == ["2017", "2018", "2019", "2020", "2021"]
    assert years["2017"]["trial_count"] == 0
    assert years["2017"]["citations"] == []
    assert years["2017"]["supporting_nct_ids_complete"] is True


def test_country_bar(client, set_plan):
    set_plan(bar_plan("country"))
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


def test_network_sponsor_drug(client, set_plan):
    set_plan(network_plan("sponsor_drug"))
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


def test_network_site_drug_endpoint(client, set_plan):
    set_plan(network_plan("site_drug"))
    r = client.post(
        "/analyze",
        json={"query": "Show trial sites and drugs."},
    )
    body = r.json()
    assert body["visualization"]["type"] == "network_graph"
    node_types = {n["type"] for n in body["visualization"]["nodes"]}
    assert {"site", "drug"} <= node_types
    assert body["visualization"]["edges"]


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


def test_structured_small_enum_filters_are_applied(client):
    r = client.post(
        "/analyze",
        json={
            "query": "trials by phase",
            "sponsor_class": "industry-sponsored",
            "study_type": "interventional",
            "sex": "female",
            "intervention_type": "drug",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["filters_applied"]["sponsor_class"] == "INDUSTRY"
    assert body["meta"]["filters_applied"]["study_type"] == "INTERVENTIONAL"
    assert body["meta"]["filters_applied"]["sex"] == "FEMALE"
    assert body["meta"]["filters_applied"]["intervention_type"] == "DRUG"
    # In the fixture corpus, only NCT04 matches this full filter combination.
    assert body["meta"]["total_studies_matched"] == 1


def test_structured_phase_status_sponsor_filters_are_applied(client, set_plan):
    set_plan(bar_plan("country"))
    r = client.post(
        "/analyze",
        json={
            "query": "Which countries have the most matching trials?",
            "phase": "PHASE3",
            "status": "RECRUITING",
            "sponsor_class": "INDUSTRY",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["visualization"]["type"] == "bar_chart"
    assert body["meta"]["filters_applied"]["phase"] == "PHASE3"
    assert body["meta"]["filters_applied"]["status"] == "RECRUITING"
    assert body["meta"]["filters_applied"]["sponsor_class"] == "INDUSTRY"


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


def test_same_dim_status_filter_not_overwritten(client, set_plan):
    set_plan(bar_plan("overall_status"))
    r = client.post(
        "/analyze",
        json={"query": "trials by status", "status": "RECRUITING"},
    )
    assert r.status_code == 200
    body = r.json()
    statuses = {d["overall_status"] for d in body["visualization"]["data"]}
    assert statuses == {"Recruiting"}


def test_sampled_flag_when_truncated(monkeypatch, client, set_plan):
    set_plan(histogram_plan())
    """Truncation now only occurs for viz types that still sample —
    histogram and scatter (10k cap) and network (5k cap). Bar charts and
    time series go through exact-fan-out paths. Force truncation on a
    histogram by exceeding the numeric scan cap with a huge corpus."""
    big_corpus = [
        _study(f"NCT{i:06d}", enrollment_count=(i % 1000) + 10)
        for i in range(11000)
    ]
    monkeypatch.setattr(main_module, "CTGovClient",
                        make_fixed_corpus_client(big_corpus))

    r = client.post(
        "/analyze",
        json={
            "query": "Distribution of enrollment sizes for cardiology trials.",
            "max_studies": 200,
        },
    )
    body = r.json()
    assert body["visualization"]["type"] == "histogram"
    assert body["meta"]["truncated"] is True
    assert "(sampled)" in body["visualization"]["title"]
    for d in body["visualization"]["data"]:
        assert d["sampled"] is True
        assert "estimated_total" not in d  # no biased extrapolation
    assert any("sampled" in w.lower() for w in body["meta"]["warnings"])


def test_paginate_all_when_total_below_cap(client, set_plan):
    set_plan(bar_plan("country"))
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


def test_country_candidate_fanout_returns_sampled_support_ids(client, set_plan):
    """Country rankings use candidate discovery plus exact per-candidate counts."""
    set_plan(bar_plan("country"))
    r = client.post(
        "/analyze",
        json={"query": "Which countries have the most trials?"},
    )
    body = r.json()
    for d in body["visualization"]["data"]:
        assert d["sampled"] is False
        assert d["supporting_nct_ids_complete"] is False
        assert d["citation_count"] == d["trial_count"]


def test_grouped_compare_distinct_total_uses_union(client, set_plan):
    set_plan(grouped_compare_plan())
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


def test_grouped_bar_uses_exact_fanout(client, set_plan):
    set_plan(grouped_compare_plan())
    """Comparison must produce a grouped_bar with exact per-cell counts."""
    r = client.post("/analyze",
                    json={"query": "Compare Pembro vs Atezo by phase."})
    body = r.json()
    assert body["visualization"]["type"] == "grouped_bar_chart"
    series = sorted({d["intervention_name"] for d in body["visualization"]["data"]})
    assert series == ["Atezo", "Pembro"]
    # exact path → no sampling, all data points marked sampled=False
    assert body["meta"]["truncated"] is False
    assert all(d["sampled"] is False for d in body["visualization"]["data"])
    assert set(body["meta"]["per_series_totals"]) == {"Pembro", "Atezo"}


def test_grouped_bar_exact_fanout_zero_fills_cells(client, set_plan):
    set_plan(grouped_compare_plan())
    r = client.post("/analyze",
                    json={"query": "Compare Pembro vs Atezo by phase."})
    body = r.json()
    rows = {
        (d["phase"], d["intervention_name"]): d["trial_count"]
        for d in body["visualization"]["data"]
    }
    assert len(rows) == 12  # 2 series x 6 phase buckets
    assert rows[("Phase 1", "Atezo")] == 0
    assert rows[("Phase 4", "Pembro")] == 0
    zero = next(
        d for d in body["visualization"]["data"]
        if d["phase"] == "Phase 4" and d["intervention_name"] == "Pembro"
    )
    assert zero["citations"] == []
    assert zero["supporting_nct_ids_complete"] is True


def test_network_meta_reports_caps(monkeypatch, client, set_plan):
    set_plan(network_plan("sponsor_drug"))
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
    monkeypatch.setattr(main_module, "CTGovClient",
                        make_fixed_corpus_client(big_corpus))
    r = client.post("/analyze", json={"query": "sponsor drug network", "max_studies": 800})
    body = r.json()
    assert body["visualization"]["type"] == "network_graph"
    meta = body["meta"]
    assert meta["edges_returned"] == 200
    assert meta["edges_total"] >= 200
    assert any("truncated" in w.lower() for w in meta["warnings"])


def test_top_n_clips_network_edges_and_drops_orphan_nodes(monkeypatch, client, set_plan):
    set_plan(network_plan("sponsor_drug"))
    """Network output must honor request top_n (edges → top N by weight),
    and drop nodes whose only edges were clipped."""
    big_corpus = [
        _study(
            f"NCT{i:05d}", lead_sponsor=f"Sponsor{i % 5}",
            interventions=[{"name": f"Drug{i % 8}", "type": "DRUG"}],
        )
        for i in range(120)
    ]
    monkeypatch.setattr(main_module, "CTGovClient",
                        make_fixed_corpus_client(big_corpus))
    r = client.post(
        "/analyze",
        json={"query": "sponsor drug network", "top_n": 3, "max_studies": 200},
    )
    body = r.json()
    edges = body["visualization"]["edges"]
    nodes = body["visualization"]["nodes"]
    assert len(edges) == 3
    # All kept nodes must be referenced by at least one kept edge.
    referenced = {n for e in edges for n in (e["source"], e["target"])}
    assert {n["id"] for n in nodes} == referenced
    # Edges sorted descending by weight.
    weights = [e["weight"] for e in edges]
    assert weights == sorted(weights, reverse=True)


def test_top_n_clips_high_cardinality_buckets(client, set_plan):
    set_plan(bar_plan("country"))
    """top_n=1 keeps only the highest-trial-count country."""
    r = client.post(
        "/analyze",
        json={"query": "Which countries have the most trials?", "top_n": 1},
    )
    body = r.json()
    assert len(body["visualization"]["data"]) == 1
    assert body["visualization"]["data"][0]["country"] == "United States"


def test_scatter_datum_has_uniform_citation_fields(client, set_plan):
    set_plan(scatter_plan())
    r = client.post(
        "/analyze",
        json={"query": "Does enrollment correlate with trial duration?"},
    )
    body = r.json()
    assert body["visualization"]["type"] == "scatter_plot"
    for d in body["visualization"]["data"]:
        for k in ("trial_count", "supporting_nct_ids",
                  "supporting_nct_ids_complete", "citation_count", "citations"):
            assert k in d


def test_scatter_display_cap_adds_warning(monkeypatch, client, set_plan):
    set_plan(scatter_plan())
    corpus = [
        _study(
            f"NCTSCAT{i:04d}",
            enrollment_count=10 + i,
            start_date="2020-01-01",
            completion_date=f"2021-{(i % 12) + 1:02d}-01",
        )
        for i in range(12)
    ]
    monkeypatch.setattr(main_module, "CTGovClient", make_fixed_corpus_client(corpus))
    monkeypatch.setenv("CTGOV_SCATTER_POINT_CAP", "3")

    r = client.post(
        "/analyze",
        json={"query": "Does enrollment correlate with trial duration?"},
    )
    body = r.json()

    assert body["visualization"]["type"] == "scatter_plot"
    assert len(body["visualization"]["data"]) == 3
    assert body["meta"]["studies_used"] == 12
    assert any("display-clipped to 3 of 12 points" in w for w in body["meta"]["warnings"])


def test_network_edge_has_uniform_citation_fields(client, set_plan):
    set_plan(network_plan("sponsor_drug"))
    r = client.post("/analyze", json={"query": "Show a network of sponsors and drugs."})
    body = r.json()
    assert body["visualization"]["type"] == "network_graph"
    for e in body["visualization"]["edges"]:
        for k in ("trial_count", "supporting_nct_ids",
                  "supporting_nct_ids_complete", "citation_count", "citations"):
            assert k in e


@pytest.mark.parametrize("query,expected_dim", [
    ("trials by sponsor class", "sponsor_class"),
    ("trials by study type", "study_type"),
    ("trials by sex", "sex"),
    ("trials by intervention type", "intervention_type"),
])
def test_small_enum_bar_uses_exact_fanout(monkeypatch, query, expected_dim):
    """sponsor_class / study_type / sex / intervention_type bar charts
    must skip the sample-window path entirely — one countTotal per
    bucket. With a corpus of 100 trials all having the same dim value,
    the fake's filter-aware count_for_filters returns 100 only for that
    bucket, 0 elsewhere — proving fan-out actually filtered."""
    corpus = [
        _study(
            f"NCT{i:04d}",
            sponsor_class="INDUSTRY", study_type="INTERVENTIONAL",
            sex="ALL", intervention_types=["DRUG"],
            interventions=[{"name": "DrugA", "type": "DRUG"}],
        )
        for i in range(100)
    ]
    monkeypatch.setattr(main_module, "CTGovClient", make_fake_client_class(corpus))
    monkeypatch.setattr(
        main_module, "plan_query", plan_query_for(bar_plan(expected_dim))
    )
    c = TestClient(main_module.app)
    r = c.post("/analyze", json={"query": query, "max_studies": 50})
    body = r.json()
    assert body["visualization"]["type"] == "bar_chart"
    assert body["meta"]["truncated"] is False
    # Exact fan-out → only the populated bucket(s) make it through.
    by_dim = {d[expected_dim]: d["trial_count"] for d in body["visualization"]["data"]}
    assert sum(by_dim.values()) == 100
    assert all(d["sampled"] is False for d in body["visualization"]["data"])


def test_sponsor_top_n_uses_exact_fanout_not_sample_window(monkeypatch):
    """High-cardinality sponsor rankings must come from per-candidate
    countTotal queries — not from local aggregation over a sample window
    that may miss the real leader."""
    # Sample window contains mostly Sponsor A. The TRUE leader (Sponsor B)
    # is hidden outside the sample. With Path A1 we discover candidates
    # from the sample, then fan out exact counts; the FakeClient's
    # filtered count_for_filters / search_studies tells us Sponsor B has
    # more total trials.
    sample_window = [
        _study(f"NCTA{i:04d}", lead_sponsor="Sponsor A") for i in range(100)
    ]
    full_corpus = sample_window + [
        _study(f"NCTB{i:04d}", lead_sponsor="Sponsor B") for i in range(500)
    ]

    class SkewedClient(FakeCTGovClient):
        # Simulates sample-window bias: with no sponsor filter, return only
        # the leading window (mostly Sponsor A). With a sponsor filter, return
        # the true filtered count from the full corpus.
        async def search_studies(self, filters, max_studies=500, **_k):
            sel = (
                [s for s in full_corpus if s["lead_sponsor"] == filters.sponsor]
                if filters.sponsor else sample_window
            )
            return sel[:max_studies], len(sel)

        async def count_for_filters(self, filters):
            sel, total = await self.search_studies(filters, max_studies=1)
            return total

    monkeypatch.setattr(main_module, "CTGovClient", SkewedClient)
    monkeypatch.setattr(
        main_module, "plan_query", plan_query_for(bar_plan("lead_sponsor"))
    )
    c = TestClient(main_module.app)
    r = c.post(
        "/analyze",
        json={"query": "trials by sponsor", "max_studies": 50, "top_n": 5},
    )
    body = r.json()
    assert body["visualization"]["type"] == "bar_chart"
    by_sponsor = {
        d["lead_sponsor"]: d["trial_count"]
        for d in body["visualization"]["data"]
    }
    # Path A1 found Sponsor A in the sample, then fanned out countTotal.
    # Sponsor A's exact count is 100 (its full filtered share), not the
    # sampled 50.
    assert by_sponsor["Sponsor A"] == 100
    # Counts on shown candidates are exact — datum is not sampled.
    for d in body["visualization"]["data"]:
        assert d["sampled"] is False


def test_time_series_default_range_is_surfaced(client, set_plan):
    set_plan(time_series_plan())
    """Time-series defaults (2010-current) must show in filters_applied
    + a warning, so the user can see the implicit scope."""
    r = client.post(
        "/analyze",
        json={"query": "How has the number of trials changed each year?"},
    )
    body = r.json()
    fa = body["meta"]["filters_applied"]
    assert "start_year" in fa and "end_year" in fa
    assert fa["start_year"] == 2010
    assert any("default" in w.lower() and "start_year" in w
               for w in body["meta"]["warnings"])


def test_time_series_explicit_range_no_default_warning(client, set_plan):
    set_plan(time_series_plan())
    r = client.post(
        "/analyze",
        json={
            "query": "How has the number of trials changed each year?",
            "start_year": 2018, "end_year": 2021,
        },
    )
    body = r.json()
    assert not any("default" in w.lower() and "start_year" in w
                   for w in body["meta"]["warnings"])


def test_network_truncation_surfaces_warning(monkeypatch, client, set_plan):
    set_plan(network_plan("sponsor_drug"))
    """When the network is built from a sampled study set, the response
    must include a warning explaining that edge weights are lower bounds.
    Network has its own larger scan cap (CTGOV_NETWORK_SCAN_CAP=5000), so
    we force truncation by exceeding it."""
    big_corpus = [
        _study(
            f"NCT{i:05d}", lead_sponsor=f"Sponsor{i % 8}",
            interventions=[{"name": f"Drug{i % 12}", "type": "DRUG"}],
        )
        for i in range(6000)
    ]
    monkeypatch.setattr(main_module, "CTGovClient",
                        make_fixed_corpus_client(big_corpus))
    r = client.post(
        "/analyze",
        json={"query": "sponsor drug network", "max_studies": 200},
    )
    body = r.json()
    assert body["visualization"]["type"] == "network_graph"
    assert body["meta"]["truncated"] is True
    assert any("sampled" in w.lower() and "network" in w.lower()
               for w in body["meta"]["warnings"])
    for e in body["visualization"]["edges"]:
        assert e["sampled"] is True


def test_upstream_error_returns_502(monkeypatch, client):
    from app.ctgov import CTGovError

    class BoomClient(FakeCTGovClient):
        async def search_studies(self, *_a, **_k):
            raise CTGovError("upstream unavailable", status_code=503)

        async def count_for_filters(self, *_a, **_k):
            raise CTGovError("upstream unavailable", status_code=503)

    monkeypatch.setattr(main_module, "CTGovClient", BoomClient)
    r = client.post("/analyze", json={"query": "trials by phase"})
    assert r.status_code == 502
    assert "upstream" in r.json()["error"].lower()
