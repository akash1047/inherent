"""Unit tests for SearchService mode routing (PM-S018, ENG-S082)."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.models.search import SearchRequest
from src.services.search import SearchService

# ---------------------------------------------------------------------------
# Fixture: patch embed_query so the ~90 MB model is never loaded in tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def stub_embed_query(monkeypatch):
    """Replace embed_query with a stub that returns 384 zeros (no model load)."""

    def _fake(text: str) -> tuple[float, ...]:
        return tuple(0.0 for _ in range(384))

    monkeypatch.setattr("src.services.embedder.embed_query", _fake, raising=False)
    # Also patch the lazy-import reference inside _build_graphql
    monkeypatch.setattr("src.services.search.embed_query", _fake, raising=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(responses: list[dict]) -> tuple[SearchService, list]:
    """Return a SearchService whose httpx client returns canned GraphQL responses.

    Returns (service, captured_calls) where captured_calls is a list of request bodies
    that were POST-ed, so tests can inspect the GraphQL query strings.
    """
    svc = SearchService(database=MagicMock(), weaviate_url="http://fake")
    client = AsyncMock(spec=httpx.AsyncClient)
    payloads = iter(responses)
    captured_calls: list[dict] = []

    async def _post(path, json=None, **_):  # noqa: ANN001
        captured_calls.append(json)
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = next(payloads)
        resp.raise_for_status = MagicMock()
        return resp

    client.post = _post
    svc._client = client
    return svc, captured_calls


def _empty_gql_response(collection_name: str = "Workspace_ws1") -> dict:
    return {"data": {"Get": {collection_name: []}}}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_mode_builds_near_vector_query() -> None:
    """Semantic (default) mode must emit nearVector with a float vector payload."""
    svc, calls = _make_service([_empty_gql_response()])
    req = SearchRequest(query="hello world")
    await svc.search(workspace_id="ws1", user_id="u1", request=req)
    assert len(calls) == 1
    q = calls[0]["query"]
    assert "nearVector" in q
    # nearVector does not echo the query text; only the vector is embedded.
    assert "nearText" not in q
    # Vector payload must be emitted as a numeric array
    assert re.search(r"vector:\s*\[", q)


@pytest.mark.asyncio
async def test_hybrid_mode_builds_hybrid_query_with_alpha() -> None:
    svc, calls = _make_service([_empty_gql_response()])
    req = SearchRequest(query="ErrNotFound", search_mode="hybrid", alpha=0.5)
    await svc.search(workspace_id="ws1", user_id="u1", request=req)
    assert len(calls) == 1
    q = calls[0]["query"]
    assert "hybrid" in q
    assert "alpha: 0.5" in q
    assert "ErrNotFound" in q
    # Hybrid must also include a vector so Weaviate doesn't need a server-side vectorizer
    assert re.search(r"vector:\s*\[", q)


@pytest.mark.asyncio
async def test_keyword_mode_builds_bm25_query() -> None:
    svc, calls = _make_service([_empty_gql_response()])
    req = SearchRequest(query="literal text", search_mode="keyword")
    await svc.search(workspace_id="ws1", user_id="u1", request=req)
    assert len(calls) == 1
    q = calls[0]["query"]
    assert "bm25" in q


@pytest.mark.asyncio
async def test_response_echoes_back_search_mode() -> None:
    svc, _ = _make_service([_empty_gql_response()])
    req = SearchRequest(query="x", search_mode="hybrid")
    resp = await svc.search(workspace_id="ws1", user_id="u1", request=req)
    assert resp.search_mode == "hybrid"


@pytest.mark.asyncio
async def test_hybrid_failure_raises_not_silent_fallback() -> None:
    """When Weaviate errors on a hybrid call, do NOT silently fall back."""
    svc = SearchService(database=MagicMock(), weaviate_url="http://fake")
    client = AsyncMock(spec=httpx.AsyncClient)

    async def _bad_post(*_a, **_kw):
        raise httpx.HTTPError("weaviate down")

    client.post = _bad_post
    svc._client = client
    req = SearchRequest(query="x", search_mode="hybrid")
    with pytest.raises(httpx.HTTPError):
        await svc.search(workspace_id="ws1", user_id="u1", request=req)


@pytest.mark.asyncio
async def test_semantic_failure_raises_not_silent_fallback() -> None:
    """Same as hybrid: semantic errors must propagate, not silently fall back."""
    svc = SearchService(database=MagicMock(), weaviate_url="http://fake")
    client = AsyncMock(spec=httpx.AsyncClient)

    async def _bad_post(*_a, **_kw):
        raise httpx.HTTPError("weaviate down")

    client.post = _bad_post
    svc._client = client
    req = SearchRequest(query="x", search_mode="semantic")
    with pytest.raises(httpx.HTTPError):
        await svc.search(workspace_id="ws1", user_id="u1", request=req)
