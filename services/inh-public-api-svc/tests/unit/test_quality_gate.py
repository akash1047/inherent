"""Tests for the adaptive retrieval quality gate + bounded fallback (#43).

The gate (``services/quality_gate.py``) is pure/offline. The fallback wiring
(``api/v1/search.py:_apply_quality_gate_and_fallback``) is tested with a fake
retrieve callable so we can assert it fires exactly once and never loops.
"""

from __future__ import annotations

import pytest

from src.api.v1.search import _apply_quality_gate_and_fallback, _build_fallback_request
from src.models.search import QualityVerdict, SearchRequest, SearchResponse, SearchResult
from src.services.quality_gate import (
    MIN_SUFFICIENT_RESULTS,
    TOP_SCORE_THRESHOLD,
    evaluate,
)


def _result(score: float, chunk_id: str = "c") -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        document_id="d",
        document_name="d.txt",
        content="x",
        score=score,
    )


# --- evaluate() verdict scenarios -----------------------------------------


def test_empty_results_is_insufficient_no_results():
    verdict = evaluate([], SearchRequest(query="q"))
    assert verdict.verdict == "insufficient_evidence"
    assert verdict.reason_code == "no_results"
    assert verdict.confidence == 0.0


def test_low_top_score_is_low_confidence():
    # Several results but all weak.
    results = [_result(0.3, "a"), _result(0.2, "b"), _result(0.1, "c")]
    verdict = evaluate(results, SearchRequest(query="q"))
    assert verdict.verdict == "low_confidence"
    assert verdict.reason_code == "top_score_below_threshold"
    assert verdict.confidence == pytest.approx(0.3)


def test_low_result_count_is_insufficient():
    # Strong top score but too few results.
    assert MIN_SUFFICIENT_RESULTS >= 2
    results = [_result(0.9, "a")]
    verdict = evaluate(results, SearchRequest(query="q"))
    assert verdict.verdict == "insufficient_evidence"
    assert verdict.reason_code == "low_result_count"


def test_strong_and_enough_is_sufficient():
    results = [_result(0.9, "a"), _result(0.8, "b"), _result(0.7, "c")]
    verdict = evaluate(results, SearchRequest(query="q"))
    assert verdict.verdict == "sufficient"
    assert verdict.reason_code == "ok"
    assert verdict.confidence == pytest.approx(0.9)


def test_threshold_boundary_is_sufficient():
    # Exactly at the threshold counts as not-below (>=).
    results = [_result(TOP_SCORE_THRESHOLD, "a"), _result(TOP_SCORE_THRESHOLD, "b")]
    verdict = evaluate(results, SearchRequest(query="q"))
    assert verdict.verdict == "sufficient"


# --- _build_fallback_request ----------------------------------------------


def test_low_confidence_builds_keyword_retry():
    req = SearchRequest(query="q", search_mode="semantic")
    verdict = QualityVerdict(
        verdict="low_confidence", reason_code="top_score_below_threshold", confidence=0.2
    )
    fb = _build_fallback_request(req, verdict)
    assert fb is not None
    assert fb.search_mode == "keyword"


def test_low_confidence_in_keyword_has_no_fallback():
    req = SearchRequest(query="q", search_mode="keyword")
    verdict = QualityVerdict(
        verdict="low_confidence", reason_code="top_score_below_threshold", confidence=0.2
    )
    assert _build_fallback_request(req, verdict) is None


def test_insufficient_evidence_broadens_query():
    req = SearchRequest(query="q", search_mode="semantic", min_score=0.4, limit=10)
    verdict = QualityVerdict(
        verdict="insufficient_evidence", reason_code="low_result_count", confidence=0.6
    )
    fb = _build_fallback_request(req, verdict)
    assert fb is not None
    assert fb.min_score == 0.0
    assert fb.limit == 20


# --- _apply_quality_gate_and_fallback: fallback fires once, no loop --------


@pytest.mark.asyncio
async def test_low_confidence_triggers_exactly_one_keyword_retry():
    request = SearchRequest(query="q", search_mode="semantic")
    # Initial response is weak (low confidence).
    response = SearchResponse(
        results=[_result(0.3, "a"), _result(0.2, "b")],
        query="q",
        total_results=2,
        processing_time_ms=5.0,
        search_mode="semantic",
    )

    calls: list[SearchRequest] = []

    async def fake_retrieve(req: SearchRequest):
        calls.append(req)
        # The retry returns strong results so the FINAL verdict is sufficient.
        return [_result(0.9, "a"), _result(0.8, "b")], 7.0

    await _apply_quality_gate_and_fallback(response, request, fake_retrieve)

    # Exactly ONE fallback retrieve, and it was a keyword retry.
    assert len(calls) == 1
    assert calls[0].search_mode == "keyword"
    assert response.performed_fallback is True
    assert response.fallback_strategy == "keyword_retry"
    assert response.quality_verdict is not None
    assert response.quality_verdict.verdict == "sufficient"
    assert response.processing_time_ms == pytest.approx(12.0)


@pytest.mark.asyncio
async def test_fallback_does_not_loop_even_when_retry_still_weak():
    """A still-weak retry must NOT trigger another fallback."""
    request = SearchRequest(query="q", search_mode="semantic")
    response = SearchResponse(
        results=[_result(0.3, "a"), _result(0.2, "b")],
        query="q",
        total_results=2,
        processing_time_ms=5.0,
        search_mode="semantic",
    )

    calls: list[SearchRequest] = []

    async def fake_retrieve(req: SearchRequest):
        calls.append(req)
        # Retry is ALSO weak — must not recurse.
        return [_result(0.1, "a"), _result(0.1, "b")], 3.0

    await _apply_quality_gate_and_fallback(response, request, fake_retrieve)

    assert len(calls) == 1  # single bounded retry, no loop
    assert response.performed_fallback is True
    # Final verdict reflects the still-weak retry, but no second fallback ran.
    assert response.quality_verdict is not None
    assert response.quality_verdict.verdict == "low_confidence"


@pytest.mark.asyncio
async def test_sufficient_does_not_fallback():
    request = SearchRequest(query="q", search_mode="semantic")
    response = SearchResponse(
        results=[_result(0.9, "a"), _result(0.8, "b")],
        query="q",
        total_results=2,
        processing_time_ms=5.0,
        search_mode="semantic",
    )

    async def fake_retrieve(req: SearchRequest):  # pragma: no cover - must not run
        raise AssertionError("fallback should not run for sufficient results")

    await _apply_quality_gate_and_fallback(response, request, fake_retrieve)

    assert response.performed_fallback is False
    assert response.fallback_strategy is None
    assert response.quality_verdict is not None
    assert response.quality_verdict.verdict == "sufficient"


@pytest.mark.asyncio
async def test_fallback_failure_is_swallowed():
    request = SearchRequest(query="q", search_mode="semantic")
    response = SearchResponse(
        results=[_result(0.3, "a")],
        query="q",
        total_results=1,
        processing_time_ms=5.0,
        search_mode="semantic",
    )

    async def fake_retrieve(req: SearchRequest):
        raise RuntimeError("weaviate down")

    # Must not raise; original results preserved, fallback not marked performed.
    await _apply_quality_gate_and_fallback(response, request, fake_retrieve)
    assert response.performed_fallback is False
    assert response.total_results == 1
