"""Tests for hybrid retrieval scoring semantics & score provenance (#45).

Verifies that each search mode tags its results with the correct ``score_source``
and echoes the raw signals (bm25_score / vector_similarity / alpha), and that the
documented distance→similarity conversion produces the expected value. The
Weaviate client and embedder are mocked; no live stack is required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.search import SearchRequest
from src.services.search import SearchService, _get_workspace_collection_name


@pytest.fixture(autouse=True)
def stub_embed_query(monkeypatch):
    """Prevent loading the embedding model / hitting the TEI sidecar."""

    def _fake(text: str) -> tuple[float, ...]:
        return tuple(0.0 for _ in range(384))

    monkeypatch.setattr("src.services.embedder.embed_query", _fake, raising=False)
    monkeypatch.setattr("src.services.search.embed_query", _fake, raising=False)


def _service() -> SearchService:
    return SearchService(database=MagicMock(), weaviate_url="http://fake")


def _mock_client(chunks: list[dict], collection_name: str) -> AsyncMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"data": {"Get": {collection_name: chunks}}}
    client = AsyncMock()
    client.post.return_value = resp
    return client


@pytest.mark.asyncio
async def test_keyword_mode_score_source_is_bm25() -> None:
    svc = _service()
    collection = _get_workspace_collection_name("ws1")
    svc._client = _mock_client(
        [
            {
                "document_id": "d1",
                "original_filename": "a.txt",
                "content": "hello",
                "chunk_index": 0,
                "_additional": {"id": "c1", "score": "0.73"},
            }
        ],
        collection,
    )

    req = SearchRequest(query="hello", search_mode="keyword")
    results = await svc._search_weaviate("ws1", "u1", req)

    assert len(results) == 1
    r = results[0]
    assert r.score_source == "bm25"
    assert r.bm25_score == 0.73
    assert r.vector_similarity is None
    assert r.alpha is None


@pytest.mark.asyncio
async def test_semantic_mode_score_source_is_vector() -> None:
    svc = _service()
    collection = _get_workspace_collection_name("ws1")
    svc._client = _mock_client(
        [
            {
                "document_id": "d1",
                "original_filename": "a.txt",
                "content": "x",
                "chunk_index": 0,
                "_additional": {"id": "c1", "score": None, "certainty": 0.83},
            }
        ],
        collection,
    )

    req = SearchRequest(query="x", search_mode="semantic")
    results = await svc._search_weaviate("ws1", "u1", req)

    r = results[0]
    assert r.score_source == "vector"
    assert r.vector_similarity == 0.83
    assert r.score == 0.83
    assert r.bm25_score is None
    assert r.alpha is None


@pytest.mark.asyncio
async def test_hybrid_mode_score_source_and_alpha_echoed() -> None:
    svc = _service()
    collection = _get_workspace_collection_name("ws1")
    svc._client = _mock_client(
        [
            {
                "document_id": "d1",
                "original_filename": "a.txt",
                "content": "x",
                "chunk_index": 0,
                "_additional": {"id": "c1", "score": "0.61", "certainty": 0.9},
            }
        ],
        collection,
    )

    req = SearchRequest(query="x", search_mode="hybrid", alpha=0.4)
    results = await svc._search_weaviate("ws1", "u1", req)

    r = results[0]
    assert r.score_source == "hybrid"
    assert r.alpha == 0.4  # echoed back exactly
    assert r.bm25_score == 0.61
    assert r.score == 0.61  # fused score from Weaviate wins for ranking
    # Raw vector signal still surfaced for transparency.
    assert r.vector_similarity == 0.9


@pytest.mark.asyncio
async def test_distance_to_similarity_conversion_documented_value() -> None:
    """distance 0.5 → similarity 1 - 0.5/2 = 0.75 (documented formula)."""
    svc = _service()
    collection = _get_workspace_collection_name("ws1")
    svc._client = _mock_client(
        [
            {
                "document_id": "d1",
                "original_filename": "a.txt",
                "content": "x",
                "chunk_index": 0,
                "_additional": {
                    "id": "c1",
                    "score": None,
                    "certainty": None,
                    "distance": 0.5,
                },
            }
        ],
        collection,
    )

    req = SearchRequest(query="x", search_mode="semantic")
    results = await svc._search_weaviate("ws1", "u1", req)

    r = results[0]
    assert r.score == 0.75
    assert r.vector_similarity == 0.75
    assert r.score_source == "vector"


@pytest.mark.asyncio
async def test_freshness_metadata_passes_through_unchanged() -> None:
    """Extra chunk fields (e.g. freshness) survive into result.metadata (#45)."""
    svc = _service()
    collection = _get_workspace_collection_name("ws1")
    svc._client = _mock_client(
        [
            {
                "document_id": "d1",
                "original_filename": "a.txt",
                "content": "x",
                "chunk_index": 3,
                "ingested_at": "2026-01-01T00:00:00Z",
                "freshness_score": 0.42,
                "_additional": {"id": "c1", "score": "0.5"},
            }
        ],
        collection,
    )

    req = SearchRequest(query="x", search_mode="keyword")
    results = await svc._search_weaviate("ws1", "u1", req)

    md = results[0].metadata
    assert md is not None
    assert md["chunk_index"] == 3
    # Non-core fields are preserved verbatim, not stripped.
    assert md["ingested_at"] == "2026-01-01T00:00:00Z"
    assert md["freshness_score"] == 0.42


@pytest.mark.asyncio
async def test_precomputed_vector_is_reused_not_reembedded(monkeypatch) -> None:
    """When query_vector is supplied, embed_query is not called again (#13)."""
    calls = {"n": 0}

    def _counting_embed(text: str) -> tuple[float, ...]:
        calls["n"] += 1
        return tuple(0.0 for _ in range(384))

    monkeypatch.setattr("src.services.search.embed_query", _counting_embed, raising=False)

    svc = _service()
    collection = _get_workspace_collection_name("ws1")
    svc._client = _mock_client([], collection)

    req = SearchRequest(query="x", search_mode="semantic")
    await svc._search_weaviate("ws1", "u1", req, query_vector=[0.2] * 384)

    # Precomputed vector reused — embedder never invoked inside the query build.
    assert calls["n"] == 0
    # And the supplied vector reached the GraphQL body.
    body = svc._client.post.call_args[1]["json"]["query"]
    assert "0.200000" in body
