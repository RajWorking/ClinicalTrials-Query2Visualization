"""ClinicalTrials.gov v2 API client: filters → params, paginate, normalize."""
from __future__ import annotations

import asyncio
import gzip
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Any, Iterable, Optional

import httpx

from .aliases import normalize_condition, normalize_drug
from .schemas import Filters

BASE = "https://clinicaltrials.gov/api/v2"
logger = logging.getLogger(__name__)

# Curl-equivalent headers; some CDN edges 403 on httpx's bare default UA.
DEFAULT_HEADERS = {
    "User-Agent": "cheiron-clinical-trials/0.1 (+https://clinicaltrials.gov/data-api/api; httpx)",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

DEFAULT_FIELDS = [
    "NCTId", "BriefTitle", "BriefSummary", "Phase", "OverallStatus",
    "StartDate", "CompletionDate", "EnrollmentCount", "LeadSponsorName",
    "LeadSponsorClass", "LocationCountry", "Condition", "InterventionName",
    "InterventionType", "StudyType", "Sex", "InterventionMeshTerm",
]

# In-process TTL cache, keyed by sorted (path, params).
_CACHE_TTL = float(os.environ.get("CTGOV_CACHE_TTL", "300"))
_CACHE_MAX_ENTRIES = int(os.environ.get("CTGOV_CACHE_MAX", "256"))
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

# Per-event-loop semaphore caps in-flight requests on fan-out paths.
_CONCURRENCY = int(os.environ.get("CTGOV_CONCURRENCY", "8"))
_SEM_BY_LOOP: dict[int, asyncio.Semaphore] = {}


def _get_semaphore() -> asyncio.Semaphore:
    loop_id = id(asyncio.get_running_loop())
    sem = _SEM_BY_LOOP.get(loop_id)
    if sem is None:
        sem = _SEM_BY_LOOP[loop_id] = asyncio.Semaphore(_CONCURRENCY)
    return sem


def _cache_key(path: str, params: dict[str, Any]) -> str:
    items = sorted((k, str(v)) for k, v in params.items())
    return path + "?" + "&".join(f"{k}={v}" for k, v in items)


def _cache_get(key: str) -> Optional[dict[str, Any]]:
    entry = _CACHE.get(key)
    if not entry:
        return None
    expires_at, value = entry
    if time.monotonic() > expires_at:
        _CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: dict[str, Any]) -> None:
    if len(_CACHE) >= _CACHE_MAX_ENTRIES:
        for k in list(_CACHE.keys())[: _CACHE_MAX_ENTRIES // 4]:
            _CACHE.pop(k, None)
    _CACHE[key] = (time.monotonic() + _CACHE_TTL, value)


class CTGovError(RuntimeError):
    """Raised when ClinicalTrials.gov returns a non-recoverable error."""

    def __init__(self, message: str, *, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def filters_to_params(f: Filters) -> dict[str, str]:
    """Map Filters to v2 query/filter params (with brand/abbrev alias normalization)."""
    p: dict[str, str] = {}
    if (cond := normalize_condition(f.condition)):
        p["query.cond"] = cond
    if (drug := normalize_drug(f.drug_name)):
        p["query.intr"] = drug
    if f.sponsor:
        p["query.spons"] = f.sponsor
    if f.country:
        p["query.locn"] = f.country
    if f.free_text:
        p["query.term"] = f.free_text
    if f.status:
        p["filter.overallStatus"] = f.status.upper()
    advanced: list[str] = []
    if f.phase:
        advanced.append(f"AREA[Phase]{f.phase.upper()}")
    if f.start_year and f.end_year:
        advanced.append(f"AREA[StartDate]RANGE[{f.start_year}-01-01,{f.end_year}-12-31]")
    elif f.start_year:
        advanced.append(f"AREA[StartDate]RANGE[{f.start_year}-01-01,MAX]")
    elif f.end_year:
        advanced.append(f"AREA[StartDate]RANGE[MIN,{f.end_year}-12-31]")
    if advanced:
        p["filter.advanced"] = " AND ".join(advanced)
    return p


def normalize(study: dict[str, Any]) -> dict[str, Any]:
    """Flatten a v2 study record for the aggregator."""
    ps = study.get("protocolSection") or {}
    ds = study.get("derivedSection") or {}
    ident = ps.get("identificationModule") or {}
    status = ps.get("statusModule") or {}
    desc = ps.get("descriptionModule") or {}
    cond_mod = ps.get("conditionsModule") or {}
    design = ps.get("designModule") or {}
    sponsors = ps.get("sponsorCollaboratorsModule") or {}
    arms = ps.get("armsInterventionsModule") or {}
    locs = ps.get("contactsLocationsModule") or {}
    elig = ps.get("eligibilityModule") or {}
    intr_browse = ds.get("interventionBrowseModule") or {}

    intervention_pairs = [
        {"name": i.get("name"), "type": i.get("type")}
        for i in (arms.get("interventions") or [])
        if i.get("name")
    ]
    return {
        "nct_id": ident.get("nctId"),
        "brief_title": ident.get("briefTitle"),
        "brief_summary": desc.get("briefSummary"),
        "phases": design.get("phases") or [],
        "study_type": design.get("studyType"),
        "sex": elig.get("sex"),
        "overall_status": status.get("overallStatus"),
        "start_date": (status.get("startDateStruct") or {}).get("date"),
        "completion_date": (status.get("completionDateStruct") or {}).get("date"),
        "enrollment_count": (design.get("enrollmentInfo") or {}).get("count"),
        "lead_sponsor": (sponsors.get("leadSponsor") or {}).get("name"),
        "sponsor_class": (sponsors.get("leadSponsor") or {}).get("class"),
        "conditions": cond_mod.get("conditions") or [],
        "interventions": intervention_pairs,
        "intervention_names": [i["name"] for i in intervention_pairs],
        "intervention_types": [i["type"] for i in intervention_pairs if i.get("type")],
        "intervention_mesh": [
            m.get("term") for m in (intr_browse.get("meshes") or []) if m.get("term")
        ],
        "countries": sorted({
            loc.get("country") for loc in (locs.get("locations") or []) if loc.get("country")
        }),
    }


class CTGovClient:
    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "CTGovClient":
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0, base_url=BASE, headers=DEFAULT_HEADERS,
                follow_redirects=True,
            )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        key = _cache_key(path, params)
        cached = _cache_get(key)
        if cached is not None:
            return cached
        async with _get_semaphore():
            result = await self._do_get(path, params)
        _cache_put(key, result)
        return result

    async def _do_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        assert self._client is not None
        last_err: Optional[Exception] = None
        last_status: Optional[int] = None
        for attempt in range(3):
            try:
                r = await self._client.get(path, params=params)
                if r.status_code in (429, 502, 503, 504):
                    last_status = r.status_code
                    last_err = httpx.HTTPStatusError(
                        f"transient {r.status_code}", request=r.request, response=r,
                    )
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                if r.status_code == 403:
                    # Some CDN edges block httpx specifically; fall back to urllib.
                    logger.warning("httpx got 403 from %s — using urllib fallback.", path)
                    return await asyncio.to_thread(_get_via_urllib, path, params)
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                raise CTGovError(
                    f"ClinicalTrials.gov returned {e.response.status_code} "
                    f"for {path}: {e.response.text[:200]}",
                    status_code=e.response.status_code,
                ) from e
            except httpx.HTTPError as e:
                last_err = e
                await asyncio.sleep(0.5 * (2 ** attempt))
        raise CTGovError(
            f"ClinicalTrials.gov request failed after retries: {last_err}",
            status_code=last_status,
        )

    async def _paginate(
        self,
        params: dict[str, Any],
        consume: Any,  # callable(study_dict) -> bool  (return True to stop)
    ) -> int:
        """Drive paginated /studies fetch, calling `consume(study)` for each.

        Returns the API's reported totalCount. Stops when `consume` returns True
        or when nextPageToken runs out.
        """
        total = 0
        next_token: Optional[str] = None
        while True:
            page_params = dict(params)
            if next_token:
                page_params["pageToken"] = next_token
            data = await self._get("/studies", page_params)
            if not total:
                total = int(data.get("totalCount", 0) or 0)
            for s in data.get("studies") or []:
                if consume(s):
                    return total
            next_token = data.get("nextPageToken")
            if not next_token:
                return total

    async def search_studies(
        self,
        filters: Filters,
        max_studies: int = 500,
        fields: Optional[Iterable[str]] = None,
        page_size: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        """Returns (normalized_studies, total_matched)."""
        params = filters_to_params(filters)
        params["pageSize"] = str(min(page_size, max_studies))
        params["countTotal"] = "true"
        params["fields"] = ",".join(fields or DEFAULT_FIELDS)

        out: list[dict[str, Any]] = []

        def consume(s: dict) -> bool:
            out.append(normalize(s))
            return len(out) >= max_studies

        total = await self._paginate(params, consume)
        return out, total or len(out)

    async def count_for_filters(self, filters: Filters) -> int:
        """totalCount only — no studies fetched."""
        params = filters_to_params(filters)
        params.update(pageSize="1", countTotal="true", fields="NCTId")
        data = await self._get("/studies", params)
        return int(data.get("totalCount", 0) or 0)

    async def ids_for_filters(
        self, filters: Filters, max_ids: int = 5000, page_size: int = 1000,
    ) -> tuple[set[str], int, bool]:
        """NCT-ID-only pagination. Returns (id_set, total_matched, truncated)."""
        params = filters_to_params(filters)
        params["pageSize"] = str(min(page_size, max_ids))
        params["countTotal"] = "true"
        params["fields"] = "NCTId"

        ids: set[str] = set()

        def consume(s: dict) -> bool:
            nct = (((s.get("protocolSection") or {})
                    .get("identificationModule") or {}).get("nctId"))
            if nct:
                ids.add(nct)
            return len(ids) >= max_ids

        total = await self._paginate(params, consume)
        total = total or len(ids)
        return ids, total, total > len(ids)


def _get_via_urllib(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """Stdlib transport — used when the httpx path receives 403."""
    url = BASE + path + "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            enc = resp.headers.get("Content-Encoding")
            if enc == "gzip":
                body = gzip.decompress(body)
            elif enc == "deflate":
                body = zlib.decompress(body)
            return json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise CTGovError(
            f"ClinicalTrials.gov returned {e.code} for {path} (urllib): {e.read()[:200]!r}",
            status_code=e.code,
        ) from e
    except Exception as e:  # noqa: BLE001
        raise CTGovError(f"urllib fallback failed for {path}: {e}") from e
