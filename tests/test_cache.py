"""Tests for the CT.gov client's in-process TTL cache and concurrency limit."""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app import ctgov
from app.ctgov import CTGovClient
from app.schemas import Filters


@pytest.fixture(autouse=True)
def clear_cache():
    ctgov._CACHE.clear()
    yield
    ctgov._CACHE.clear()


@pytest.mark.asyncio
async def test_cache_dedupes_repeat_requests():
    call_count = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(
            200,
            json={"totalCount": 42, "studies": []},
            headers={"content-type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(
        base_url="https://clinicaltrials.gov/api/v2", transport=transport,
        headers={"User-Agent": "test"},
    )
    async with CTGovClient(client=http) as c:
        await c.count_for_filters(Filters(drug_name="Pembrolizumab"))
        await c.count_for_filters(Filters(drug_name="Pembrolizumab"))
        await c.count_for_filters(Filters(drug_name="Pembrolizumab"))

    assert call_count["n"] == 1, "second + third hit should come from cache"


@pytest.mark.asyncio
async def test_cache_distinguishes_distinct_queries():
    seen_urls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_urls.append(str(req.url))
        return httpx.Response(
            200, json={"totalCount": 1, "studies": []},
            headers={"content-type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(
        base_url="https://clinicaltrials.gov/api/v2", transport=transport,
        headers={"User-Agent": "test"},
    )
    async with CTGovClient(client=http) as c:
        await c.count_for_filters(Filters(drug_name="Pembrolizumab"))
        await c.count_for_filters(Filters(drug_name="Nivolumab"))

    assert len(seen_urls) == 2


@pytest.mark.asyncio
async def test_cache_ttl_expires(monkeypatch):
    monkeypatch.setattr(ctgov, "_CACHE_TTL", 0.0)
    call_count = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(
            200, json={"totalCount": 1, "studies": []},
            headers={"content-type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(
        base_url="https://clinicaltrials.gov/api/v2", transport=transport,
        headers={"User-Agent": "test"},
    )
    async with CTGovClient(client=http) as c:
        await c.count_for_filters(Filters(drug_name="Pembrolizumab"))
        await asyncio.sleep(0.01)
        await c.count_for_filters(Filters(drug_name="Pembrolizumab"))
    assert call_count["n"] == 2
