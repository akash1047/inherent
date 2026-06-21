"""Adaptive retrieval quality gate (#43).

After a search returns, this module judges whether the retrieved evidence is
good enough to answer with, using only signals already present on the results
(result count and top relevance score). The verdict lets the API decide whether
to attempt a single, bounded fallback retry (see ``api/v1/search.py``).

This module is intentionally PURE and OFFLINE-testable: ``evaluate`` takes the
already-fetched results plus the request and returns a ``QualityVerdict`` with
no I/O. Thresholds are module constants so they are easy to reason about and to
tune from one place.
"""

from __future__ import annotations

from src.models.search import QualityVerdict, SearchRequest, SearchResult

# --- Gate thresholds -------------------------------------------------------
#
# TOP_SCORE_THRESHOLD: scores are normalised to ~[0, 1] (see SearchService score
# provenance). A best result below this is treated as weak/low-confidence.
#
# MIN_SUFFICIENT_RESULTS: with fewer than this many results we consider the
# evidence base too thin to answer confidently (but >0, so it is "insufficient
# evidence" rather than "no results").
TOP_SCORE_THRESHOLD = 0.5
MIN_SUFFICIENT_RESULTS = 2


def _top_score(results: list[SearchResult]) -> float:
    """Return the best (max) score across results, or 0.0 when empty.

    Results are not assumed to be pre-sorted, so we take the max defensively.
    """
    if not results:
        return 0.0
    return max((r.score for r in results), default=0.0)


def evaluate(results: list[SearchResult], request: SearchRequest) -> QualityVerdict:
    """Judge retrieval quality from existing signals (#43).

    Decision order (first match wins):
    1. 0 results                       → insufficient_evidence / "no_results"
    2. top score < TOP_SCORE_THRESHOLD → low_confidence / "top_score_below_threshold"
    3. fewer than MIN_SUFFICIENT_RESULTS results
                                       → insufficient_evidence / "low_result_count"
    4. otherwise                       → sufficient / "ok"

    ``confidence`` is a coarse proxy: the top score clamped to [0, 1] (0.0 when
    there are no results).

    Pure and offline: no network or DB access.
    """
    top = _top_score(results)
    confidence = max(0.0, min(1.0, top))

    if not results:
        return QualityVerdict(
            verdict="insufficient_evidence",
            reason_code="no_results",
            confidence=0.0,
        )

    if top < TOP_SCORE_THRESHOLD:
        return QualityVerdict(
            verdict="low_confidence",
            reason_code="top_score_below_threshold",
            confidence=confidence,
        )

    if len(results) < MIN_SUFFICIENT_RESULTS:
        return QualityVerdict(
            verdict="insufficient_evidence",
            reason_code="low_result_count",
            confidence=confidence,
        )

    return QualityVerdict(
        verdict="sufficient",
        reason_code="ok",
        confidence=confidence,
    )
