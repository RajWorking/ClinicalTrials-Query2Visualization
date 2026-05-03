"""Replay a recorded ClinicalTrials.gov response through the real client.

Verifies:
  - normalize() parses the actual v2 schema correctly
  - filters_to_params() builds expected query params
  - countTotal / pagination flow works end to end
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.ctgov import CTGovClient, filters_to_params, normalize
from app.schemas import Filters


FIXTURE = Path(__file__).parent / "fixtures" / "pembrolizumab_3.json"


def test_normalize_pulls_expected_fields_from_real_payload():
    raw = json.loads(FIXTURE.read_text())
    studies = raw["studies"]
    assert len(studies) == 3

    flat = normalize(studies[0])
    assert flat["nct_id"].startswith("NCT")
    assert "Pembrolizumab" in (flat["brief_title"] or "")
    assert flat["phases"]
    assert flat["overall_status"]
    assert flat["start_date"]
    assert "United States" in (flat["countries"] or [])
    # interventions retain (name, type) pairs
    assert flat["interventions"]
    assert all("name" in i for i in flat["interventions"])


def test_filters_to_params_normalizes_brand_name():
    """Filters with 'Keytruda' should hit the API as 'pembrolizumab'."""
    p = filters_to_params(Filters(drug_name="Keytruda"))
    assert p["query.intr"].lower() == "pembrolizumab"


def test_filters_to_params_normalizes_condition_alias():
    p = filters_to_params(Filters(condition="NSCLC"))
    assert "non-small cell lung cancer" in p["query.cond"].lower()


def test_filters_to_params_phase_advanced_filter():
    p = filters_to_params(Filters(phase="PHASE3"))
    assert "AREA[Phase]PHASE3" in p["filter.advanced"]


def test_filters_to_params_year_range():
    p = filters_to_params(Filters(start_year=2020, end_year=2023))
    assert "RANGE[2020-01-01,2023-12-31]" in p["filter.advanced"]


@pytest.mark.asyncio
async def test_search_studies_via_mocked_transport():
    """End-to-end through the httpx layer using MockTransport."""
    raw = FIXTURE.read_text()

    def handler(req: httpx.Request) -> httpx.Response:
        # Verify the client sent expected params + headers
        assert req.url.path == "/api/v2/studies"
        params = dict(req.url.params)
        assert params.get("query.intr", "").lower() == "pembrolizumab"
        assert "User-Agent" in req.headers
        return httpx.Response(200, text=raw,
                              headers={"content-type": "application/json"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(
        base_url="https://clinicaltrials.gov/api/v2", transport=transport,
        headers={"User-Agent": "test"},
    )
    async with CTGovClient(client=client) as c:
        studies, total = await c.search_studies(
            Filters(drug_name="Keytruda"), max_studies=3, page_size=3,
        )
    assert total == 2847
    assert len(studies) == 3
    assert all(s["nct_id"].startswith("NCT") for s in studies)
