#!/usr/bin/env python
"""Live /analyze smoke test.

Boots the FastAPI app in-process (no uvicorn), forces STUB_LLM mode, and
sends each canonical example query against the real ClinicalTrials.gov
API. Prints the visualization type and a short result summary per query.

Run:  python -m scripts.smoke_analyze
      python -m scripts.smoke_analyze --write

Exit code 0 if all queries return 200 with the expected viz type.
"""
from __future__ import annotations

import json
import os
import sys
from argparse import ArgumentParser
from pathlib import Path

os.environ["STUB_LLM"] = "1"  # avoid OpenAI dep for the smoke

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


CASES = [
    ("01_time_trend", "time_series"),
    ("02_phases", "bar_chart"),
    ("03_compare", "grouped_bar_chart"),
    ("04_geography", "bar_chart"),
    ("05_network", "network_graph"),
    ("06_histogram", "histogram"),
    ("07_scatter", "scatter_plot"),
]
EXAMPLES = Path(__file__).parent.parent / "examples"


def run_cases(*, write: bool = False) -> int:
    client = TestClient(app)
    failed = 0
    for name, expected_type in CASES:
        req = json.loads((EXAMPLES / f"{name}.request.json").read_text())
        r = client.post("/analyze", json=req)
        if r.status_code != 200:
            print(f"[FAIL] {name}: HTTP {r.status_code} — {r.text[:200]}")
            failed += 1
            continue
        body = r.json()
        actual_type = body["visualization"]["type"]
        meta = body["meta"]
        if actual_type != expected_type:
            print(f"[FAIL] {name}: expected {expected_type}, got {actual_type}")
            failed += 1
            continue
        if actual_type == "network_graph":
            n_nodes = len(body["visualization"]["nodes"])
            n_edges = len(body["visualization"]["edges"])
            print(
                f"[OK]   {name}: {actual_type} — {n_nodes} nodes / {n_edges} edges"
            )
        else:
            n_pts = len(body["visualization"]["data"])
            print(
                f"[OK]   {name}: {actual_type} — {n_pts} pts, "
                f"total={meta['total_studies_matched']}, "
                f"truncated={meta['truncated']}"
            )
        if write:
            (EXAMPLES / f"{name}.response.json").write_text(
                json.dumps(body, separators=(",", ":"), ensure_ascii=False) + "\n"
            )
    if failed:
        print(f"\n{failed} of {len(CASES)} cases FAILED")
        return 1
    print(f"\nAll {len(CASES)} cases OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description="Run live /analyze smoke checks.")
    parser.add_argument(
        "--write",
        action="store_true",
        help="overwrite examples/*.response.json with current live responses",
    )
    args = parser.parse_args(argv)
    return run_cases(write=args.write)


if __name__ == "__main__":
    sys.exit(main())
