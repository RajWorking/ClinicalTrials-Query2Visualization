#!/usr/bin/env python
"""Live smoke test against ClinicalTrials.gov.

Verifies the actual transport works in this environment. Run:
    python scripts/smoke_ctgov.py

Exits 0 if both /version and a /studies query succeed.
"""
from __future__ import annotations

import asyncio
import sys

from app.ctgov import BASE, DEFAULT_HEADERS, CTGovClient, CTGovError


async def main() -> int:
    print(f"Hitting {BASE}/version ...")
    try:
        async with CTGovClient() as c:
            v = await c._get("/version", {})
            print(f"  apiVersion={v.get('apiVersion')!r}  dataTimestamp={v.get('dataTimestamp')!r}")
    except CTGovError as e:
        print(f"  FAILED: {e}", file=sys.stderr)
        return 1

    print(f"Hitting {BASE}/studies?query.intr=pembrolizumab&pageSize=1 ...")
    try:
        async with CTGovClient() as c:
            r = await c._get(
                "/studies",
                {"query.intr": "pembrolizumab", "pageSize": "1", "countTotal": "true"},
            )
            print(f"  totalCount={r.get('totalCount')}  studies returned={len(r.get('studies', []))}")
    except CTGovError as e:
        print(f"  FAILED: {e}", file=sys.stderr)
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
