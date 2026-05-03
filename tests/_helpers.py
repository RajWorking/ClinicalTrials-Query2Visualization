"""Shared test fixtures: study factory + filter-aware fake CT.gov client."""
from __future__ import annotations

from typing import Any

from app.schemas import Filters


_BASE_STUDY: dict[str, Any] = {
    "nct_id": "NCT00000001", "brief_title": "A title",
    "brief_summary": "Summary text", "phases": ["PHASE2"],
    "study_type": "INTERVENTIONAL", "sex": "ALL",
    "overall_status": "RECRUITING",
    "start_date": "2020-05-01", "completion_date": "2022-05-01",
    "enrollment_count": 100, "lead_sponsor": "Acme",
    "sponsor_class": "INDUSTRY", "conditions": ["Cancer"],
    "interventions": [{"name": "DrugA", "type": "DRUG"}],
    "intervention_names": ["DrugA"], "intervention_types": ["DRUG"],
    "locations": [{
        "facility": "Acme Research Site",
        "city": "New York",
        "state": "NY",
        "country": "United States",
    }],
    "countries": ["United States"],
}


def make_study(nct: str | None = None, **over: Any) -> dict:
    """Build a normalized study dict, with sensible defaults.

    Keeps `interventions` and `intervention_names` in sync when only one is
    supplied — many tests pass just one of the two.
    """
    s = {**_BASE_STUDY, **over}
    if nct is not None:
        s["nct_id"] = nct
    if "interventions" in over and "intervention_names" not in over:
        s["intervention_names"] = [i["name"] for i in s["interventions"]]
    if "intervention_names" in over and "interventions" not in over:
        s["interventions"] = [
            {"name": n, "type": "DRUG"} for n in s["intervention_names"]
        ]
    if "countries" in over and "locations" not in over:
        s["locations"] = [
            {"facility": None, "city": None, "state": None, "country": country}
            for country in s["countries"]
        ]
    return s


class FakeCTGovClient:
    """In-memory CT.gov client. Subclass and set `CORPUS` (or override
    `search_studies` for sampling-bias scenarios)."""

    CORPUS: list[dict] = []

    def __init__(self, *_a: Any, **_k: Any) -> None:
        pass

    async def __aenter__(self) -> "FakeCTGovClient":
        return self

    async def __aexit__(self, *_a: Any) -> bool:
        return False

    def _select(self, filters: Filters) -> list[dict]:
        sel = list(self.CORPUS)
        if filters.drug_name:
            d = filters.drug_name.lower()
            sel = [s for s in sel
                   if any(d in n.lower() for n in s["intervention_names"])]
        if filters.condition:
            c = filters.condition.lower()
            sel = [s for s in sel
                   if any(c in cd.lower() for cd in s["conditions"])]
        if filters.phase:
            sel = [s for s in sel if filters.phase in s["phases"]]
        if filters.status:
            sel = [s for s in sel if s["overall_status"] == filters.status]
        if filters.sponsor_class:
            sel = [s for s in sel if s.get("sponsor_class") == filters.sponsor_class]
        if filters.study_type:
            sel = [s for s in sel if s.get("study_type") == filters.study_type]
        if filters.sex:
            sel = [s for s in sel if s.get("sex") == filters.sex]
        if filters.intervention_type:
            sel = [s for s in sel
                   if filters.intervention_type
                   in (s.get("intervention_types") or [])]
        if filters.country:
            cn = filters.country.lower()
            sel = [s for s in sel
                   if any(cn in c.lower() for c in s["countries"])]
        if filters.start_year:
            sel = [s for s in sel
                   if s.get("start_date")
                   and int(s["start_date"][:4]) >= filters.start_year]
        if filters.end_year:
            sel = [s for s in sel
                   if s.get("start_date")
                   and int(s["start_date"][:4]) <= filters.end_year]
        return sel

    async def search_studies(
        self, filters: Filters, max_studies: int = 500, **_k: Any,
    ) -> tuple[list[dict], int]:
        sel = self._select(filters)
        return sel[:max_studies], len(sel)

    async def count_for_filters(self, filters: Filters) -> int:
        return len(self._select(filters))

    async def ids_for_filters(
        self, filters: Filters, max_ids: int = 5000, page_size: int = 1000,
    ) -> tuple[set[str], int, bool]:
        sel = self._select(filters)
        kept = sel[:max_ids]
        return {s["nct_id"] for s in kept}, len(sel), len(sel) > len(kept)


def make_fake_client_class(corpus: list[dict]) -> type[FakeCTGovClient]:
    """Subclass FakeCTGovClient with a fixed CORPUS — for monkeypatching."""
    return type("CorpusClient", (FakeCTGovClient,), {"CORPUS": corpus})


def make_fixed_corpus_client(corpus: list[dict]) -> type[FakeCTGovClient]:
    """Like `make_fake_client_class` but ignores filters and always returns
    the full corpus — for tests that exercise truncation / sampling caps."""
    class C(FakeCTGovClient):
        async def search_studies(self, _filters, max_studies=500, **_k):
            return corpus[:max_studies], len(corpus)

        async def count_for_filters(self, _filters):
            return len(corpus)

        async def ids_for_filters(self, _filters, max_ids=5000, page_size=1000):
            kept = corpus[:max_ids]
            return {s["nct_id"] for s in kept}, len(corpus), len(corpus) > len(kept)
    return C
