"""Unit tests for the search API endpoint."""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import create_app
from src.models.api_key import APIKeyInfo
from src.models.search import SearchResponse, SearchResult
from src.services.auth import (
    ResolvedAuth,
    get_api_key_info,
    get_search_permission,
    resolve_workspace_search,
)
from src.services.search import get_search_service


@pytest.fixture
def mock_api_key_info():
    """API key with read + search permissions."""
    return APIKeyInfo(
        key_id="test-key-id",
        user_id="test-user-id",
        workspace_id="test-workspace-id",
        permissions=["read", "search"],
        rate_limit=100,
        expires_at=None,
        status="active",
    )


@pytest.fixture
def mock_api_key_read_only():
    """API key with only read permission (no search)."""
    return APIKeyInfo(
        key_id="test-key-read",
        user_id="test-user-id",
        workspace_id="test-workspace-id",
        permissions=["read"],
        rate_limit=100,
        expires_at=None,
        status="active",
    )


@pytest.fixture
def sample_search_results():
    """Create sample search results."""
    return [
        SearchResult(
            chunk_id="chunk-001",
            document_id="doc-001",
            document_name="test-document.pdf",
            content="This is a relevant chunk about machine learning.",
            score=0.95,
        ),
        SearchResult(
            chunk_id="chunk-002",
            document_id="doc-002",
            document_name="another-doc.txt",
            content="Another relevant result about AI systems.",
            score=0.87,
        ),
    ]


@pytest.fixture
def mock_search_svc(sample_search_results):
    """Create a mock search service."""
    mock = AsyncMock()
    mock.search = AsyncMock(
        return_value=SearchResponse(
            results=sample_search_results,
            query="machine learning",
            total_results=2,
            processing_time_ms=42.5,
            search_mode="semantic",
        )
    )
    return mock


@pytest.fixture
def mock_resolved_auth(mock_api_key_info):
    """Create a ResolvedAuth with workspace from the API key."""
    return ResolvedAuth(key_info=mock_api_key_info, workspace_id=mock_api_key_info.workspace_id)


@pytest.fixture
def app(mock_api_key_info, mock_search_svc, mock_resolved_auth):
    """Create a FastAPI app with overridden dependencies."""
    application = create_app()
    application.dependency_overrides[get_api_key_info] = lambda: mock_api_key_info
    application.dependency_overrides[get_search_permission] = lambda: mock_api_key_info
    application.dependency_overrides[resolve_workspace_search] = lambda: mock_resolved_auth
    application.dependency_overrides[get_search_service] = lambda: mock_search_svc
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestSearchDocuments:
    """Tests for POST /v1/search."""

    async def test_search_success(self, client, mock_search_svc):
        """Should return search results with metadata."""
        response = await client.post(
            "/v1/search",
            json={"query": "machine learning"},
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "machine learning"
        assert data["total_results"] == 2
        assert data["processing_time_ms"] == 42.5
        assert len(data["results"]) == 2
        assert data["results"][0]["chunk_id"] == "chunk-001"
        assert data["results"][0]["score"] == 0.95
        assert data["results"][1]["chunk_id"] == "chunk-002"

    async def test_search_empty_results(self, client, mock_search_svc):
        """Should return empty results when no matches are found."""
        mock_search_svc.search = AsyncMock(
            return_value=SearchResponse(
                results=[],
                query="nonexistent topic",
                total_results=0,
                processing_time_ms=15.3,
                search_mode="semantic",
            )
        )

        response = await client.post(
            "/v1/search",
            json={"query": "nonexistent topic"},
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_results"] == 0
        assert data["results"] == []
        assert data["query"] == "nonexistent topic"

    async def test_search_missing_query_field(self, client):
        """Should return 422 when query field is missing."""
        response = await client.post(
            "/v1/search",
            json={},
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 422

    async def test_search_empty_query_string(self, client):
        """Should return 422 when query is an empty string."""
        response = await client.post(
            "/v1/search",
            json={"query": ""},
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 422

    async def test_search_query_too_long(self, client):
        """Should return 422 when query exceeds 1000 characters."""
        long_query = "x" * 1001
        response = await client.post(
            "/v1/search",
            json={"query": long_query},
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 422

    async def test_search_query_at_max_length(self, client, mock_search_svc):
        """Should accept query of exactly 1000 characters."""
        mock_search_svc.search = AsyncMock(
            return_value=SearchResponse(
                results=[],
                query="x" * 1000,
                total_results=0,
                processing_time_ms=10.0,
                search_mode="semantic",
            )
        )

        response = await client.post(
            "/v1/search",
            json={"query": "x" * 1000},
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 200

    async def test_search_invalid_limit_zero(self, client):
        """Should return 422 when limit is 0."""
        response = await client.post(
            "/v1/search",
            json={"query": "test", "limit": 0},
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 422

    async def test_search_invalid_limit_exceeds_max(self, client):
        """Should return 422 when limit exceeds 100."""
        response = await client.post(
            "/v1/search",
            json={"query": "test", "limit": 101},
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 422

    async def test_search_invalid_min_score_negative(self, client):
        """Should return 422 when min_score is negative."""
        response = await client.post(
            "/v1/search",
            json={"query": "test", "min_score": -0.1},
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 422

    async def test_search_invalid_min_score_exceeds_one(self, client):
        """Should return 422 when min_score exceeds 1.0."""
        response = await client.post(
            "/v1/search",
            json={"query": "test", "min_score": 1.5},
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 422

    async def test_search_valid_min_score_boundary(self, client, mock_search_svc):
        """Should accept min_score at boundary values (0.0 and 1.0)."""
        mock_search_svc.search = AsyncMock(
            return_value=SearchResponse(
                results=[],
                query="test",
                total_results=0,
                processing_time_ms=5.0,
                search_mode="semantic",
            )
        )

        response = await client.post(
            "/v1/search",
            json={"query": "test", "min_score": 0.0},
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 200

        response = await client.post(
            "/v1/search",
            json={"query": "test", "min_score": 1.0},
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 200

    async def test_search_with_document_ids_filter(self, client, mock_search_svc):
        """Should pass document_ids filter to the search service."""
        mock_search_svc.search = AsyncMock(
            return_value=SearchResponse(
                results=[],
                query="test",
                total_results=0,
                processing_time_ms=5.0,
                search_mode="semantic",
            )
        )

        response = await client.post(
            "/v1/search",
            json={"query": "test", "document_ids": ["doc-001", "doc-002"]},
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 200

        # Verify the search service was called with the correct request
        call_args = mock_search_svc.search.call_args
        assert call_args.kwargs["workspace_id"] == "test-workspace-id"
        request_arg = call_args.kwargs["request"]
        assert request_arg.document_ids == ["doc-001", "doc-002"]

    async def test_search_passes_workspace_and_user_id(self, client, mock_search_svc):
        """Should scope search to the workspace and user from the API key."""
        await client.post(
            "/v1/search",
            json={"query": "test query"},
            headers={"X-API-Key": "ink_test_key"},
        )
        mock_search_svc.search.assert_awaited_once()
        call_args = mock_search_svc.search.call_args
        assert call_args.kwargs["workspace_id"] == "test-workspace-id"
        assert call_args.kwargs["user_id"] == "test-user-id"

    async def test_search_requires_search_permission(self, mock_search_svc):
        """Should return 403 when API key lacks search permission."""
        read_only_key = APIKeyInfo(
            key_id="test-key-read",
            user_id="test-user-id",
            workspace_id="test-workspace-id",
            permissions=["read"],
            rate_limit=100,
            expires_at=None,
            status="active",
        )

        application = create_app()
        application.dependency_overrides[get_api_key_info] = lambda: read_only_key
        # Do NOT override get_search_permission — let real dependency check permissions
        application.dependency_overrides[get_search_service] = lambda: mock_search_svc

        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/v1/search",
                json={"query": "test"},
                headers={"X-API-Key": "ink_test_key"},
            )
        assert response.status_code == 403
        application.dependency_overrides.clear()

    async def test_search_no_api_key(self, mock_search_svc):
        """Should return 401 when no API key is provided."""
        application = create_app()
        application.dependency_overrides[get_search_service] = lambda: mock_search_svc

        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/v1/search",
                json={"query": "test"},
            )
        assert response.status_code == 401
        application.dependency_overrides.clear()

    async def test_search_custom_limit(self, client, mock_search_svc):
        """Should pass custom limit to the search service."""
        mock_search_svc.search = AsyncMock(
            return_value=SearchResponse(
                results=[],
                query="test",
                total_results=0,
                processing_time_ms=5.0,
                search_mode="semantic",
            )
        )

        await client.post(
            "/v1/search",
            json={"query": "test", "limit": 50},
            headers={"X-API-Key": "ink_test_key"},
        )
        call_args = mock_search_svc.search.call_args
        request_arg = call_args.kwargs["request"]
        assert request_arg.limit == 50

    async def test_search_invalid_body_not_json(self, client):
        """Should return 422 when body is not valid JSON."""
        response = await client.post(
            "/v1/search",
            content="not json",
            headers={"X-API-Key": "ink_test_key", "Content-Type": "application/json"},
        )
        assert response.status_code == 422
