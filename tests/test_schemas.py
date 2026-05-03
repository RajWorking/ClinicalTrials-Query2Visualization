import pytest
from pydantic import ValidationError

from app.schemas import AnalyzeRequest


def test_phase_canonical_passes():
    r = AnalyzeRequest(query="x", phase="PHASE3")
    assert r.phase == "PHASE3"


def test_phase_synonyms_normalized():
    assert AnalyzeRequest(query="x", phase="Phase 3").phase == "PHASE3"
    assert AnalyzeRequest(query="x", phase="3").phase == "PHASE3"
    assert AnalyzeRequest(query="x", phase="III").phase == "PHASE3"
    assert AnalyzeRequest(query="x", phase="early phase 1").phase == "EARLY_PHASE1"


def test_phase_invalid_rejected():
    with pytest.raises(ValidationError):
        AnalyzeRequest(query="x", phase="not-a-phase")


def test_status_synonyms():
    assert AnalyzeRequest(query="x", status="recruiting").status == "RECRUITING"
    assert (
        AnalyzeRequest(query="x", status="Active, not recruiting").status
        == "ACTIVE_NOT_RECRUITING"
    )


def test_status_invalid_rejected():
    with pytest.raises(ValidationError):
        AnalyzeRequest(query="x", status="bogus")


def test_empty_query_rejected():
    with pytest.raises(ValidationError):
        AnalyzeRequest(query="")


def test_max_studies_bounds():
    with pytest.raises(ValidationError):
        AnalyzeRequest(query="x", max_studies=0)
    with pytest.raises(ValidationError):
        AnalyzeRequest(query="x", max_studies=10000)


def test_year_bounds():
    with pytest.raises(ValidationError):
        AnalyzeRequest(query="x", start_year=1800)


def test_year_range_inverted_rejected():
    with pytest.raises(ValidationError) as exc:
        AnalyzeRequest(query="x", start_year=2025, end_year=2020)
    assert "start_year" in str(exc.value)


def test_year_range_equal_ok():
    r = AnalyzeRequest(query="x", start_year=2020, end_year=2020)
    assert r.start_year == r.end_year == 2020


def test_filters_year_range_auto_repaired():
    """If the planner emits inverted years, Filters silently repairs them."""
    from app.schemas import Filters
    f = Filters(start_year=2025, end_year=2020)
    assert (f.start_year, f.end_year) == (2020, 2025)
