"""FastAPI app: POST /analyze, GET /healthz, GET / (demo UI)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .ctgov import CTGovClient, CTGovError
from .paths import PathOutcome, _finalize_plan, _select_path
from .plan_verifier import PlannerError
from .planner import plan_query
from .responses import build_analyze_response
from .schemas import AnalyzeRequest, AnalyzeResponse, QueryPlan

load_dotenv()

app = FastAPI(title="ClinicalTrials Query → Visualization", version="0.1.0")

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.exception_handler(CTGovError)
async def ctgov_error_handler(_: Any, exc: CTGovError) -> JSONResponse:
    upstream = exc.status_code or 0
    status = 400 if 400 <= upstream < 500 else 502
    return JSONResponse(
        status_code=status,
        content={
            "error": "ClinicalTrials.gov upstream error",
            "detail": str(exc),
            "upstream_status": upstream or None,
        },
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def root() -> Any:
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "POST /analyze to use the API."}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    try:
        plan: QueryPlan = plan_query(req)
    except PlannerError as e:  # planner failure (very rare; planner has its own fallback)
        raise HTTPException(502, f"Query planning failed: {e}") from e

    plan, warnings = _finalize_plan(plan)
    if plan.notes and plan.notes.startswith("fallback:"):
        warnings.insert(
            0,
            "Query understanding fell back to a safe default. " + plan.notes,
        )

    async with CTGovClient() as client:
        handler, extras = _select_path(plan)
        outcome: PathOutcome = await handler(client, plan, req, **extras)

    return build_analyze_response(
        req=req, plan=plan, outcome=outcome, warnings=warnings,
    )
