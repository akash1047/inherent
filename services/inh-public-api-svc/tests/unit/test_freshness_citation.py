"""Unit tests for freshness (#42) and claim-level citations (#39).

Offline: no DB / MQ / Weaviate. Exercises the SearchResult freshness fields,
the freshness staleness computation, and citation population from a result.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.config import settings
from src.models.citation import Citation
from src.models.search import SearchResult
from src.services.search import SearchService


class TestSearchResultFreshnessFields:
    def test_freshness_fields_default(self) -> None:
        r = SearchResult(
            chunk_id="c1",
            document_id="d1",
            document_name="x.md",
            content="text",
            score=0.5,
        )
        assert r.ingested_at is None
        assert r.is_stale is False
        assert r.citation is None

    def test_accepts_freshness_and_citation(self) -> None:
        ingested = datetime.now(UTC)
        cit = Citation(
            chunk_id="c1",
            document_id="d1",
            document_name="x.md",
            content="text",
            score=0.5,
            ingested_at=ingested,
            is_stale=False,
        )
        r = SearchResult(
            chunk_id="c1",
            document_id="d1",
            document_name="x.md",
            content="text",
            score=0.5,
            ingested_at=ingested,
            is_stale=False,
            citation=cit,
        )
        assert r.ingested_at == ingested
        assert r.citation is not None
        assert r.citation.chunk_id == "c1"


class TestComputeIsStale:
    def test_fresh_within_window_is_not_stale(self) -> None:
        recent = datetime.now(UTC) - timedelta(days=settings.freshness_max_age_days - 1)
        assert SearchService._compute_is_stale(recent) is False

    def test_old_beyond_window_is_stale(self) -> None:
        old = datetime.now(UTC) - timedelta(days=settings.freshness_max_age_days + 1)
        assert SearchService._compute_is_stale(old) is True

    def test_exactly_at_boundary_is_not_stale(self) -> None:
        # ingested_at == cutoff is not strictly less-than, so not stale.
        now = datetime.now(UTC)
        boundary = now - timedelta(days=settings.freshness_max_age_days)
        assert SearchService._compute_is_stale(boundary, now=now) is False

    def test_unknown_ingested_at_is_not_stale(self) -> None:
        assert SearchService._compute_is_stale(None) is False


class TestParseIngestedAt:
    def test_parses_rfc3339_z(self) -> None:
        parsed = SearchService._parse_ingested_at("2024-01-01T00:00:00Z")
        assert parsed is not None
        assert parsed.tzinfo is not None
        assert parsed.year == 2024

    def test_naive_datetime_gets_utc(self) -> None:
        naive = datetime(2024, 1, 1, 0, 0, 0)  # noqa: DTZ001
        parsed = SearchService._parse_ingested_at(naive)
        assert parsed is not None
        assert parsed.tzinfo is UTC

    def test_unparseable_returns_none(self) -> None:
        assert SearchService._parse_ingested_at("not-a-date") is None
        assert SearchService._parse_ingested_at(None) is None
        assert SearchService._parse_ingested_at(12345) is None


class TestCitationFromResultShape:
    """Citation carries the result's stable, auditable fields (#39)."""

    def test_citation_mirrors_result_fields(self) -> None:
        ingested = datetime.now(UTC) - timedelta(days=settings.freshness_max_age_days + 5)
        is_stale = SearchService._compute_is_stale(ingested)
        cit = Citation(
            chunk_id="chunk-7",
            document_id="doc-3",
            document_name="report.pdf",
            content="The revenue grew 20%.",
            start_char=10,
            end_char=31,
            score=0.87,
            score_source="hybrid",
            source_uri="s3://bucket/report.pdf",
            ingested_at=ingested,
            is_stale=is_stale,
        )
        assert cit.is_stale is True
        assert cit.score_source == "hybrid"
        assert cit.start_char == 10
        assert cit.end_char == 31
        assert cit.source_uri == "s3://bucket/report.pdf"
