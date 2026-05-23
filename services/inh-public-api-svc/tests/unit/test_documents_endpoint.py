"""Unit tests for the documents API endpoints."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import create_app
from src.models.api_key import APIKeyInfo
from src.models.document import Document
from src.services.auth import (
    ResolvedAuth,
    get_api_key_info,
    get_read_permission,
    resolve_workspace_read,
)
from src.services.database import get_database


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
def mock_api_key_search_only():
    """API key with only search permission (no read)."""
    return APIKeyInfo(
        key_id="test-key-search",
        user_id="test-user-id",
        workspace_id="test-workspace-id",
        permissions=["search"],
        rate_limit=100,
        expires_at=None,
        status="active",
    )


@pytest.fixture
def sample_documents():
    """Create a list of sample Document objects."""
    now = datetime.now(timezone.utc)
    return [
        Document(
            id="doc-001",
            name="first-document.pdf",
            workspace_id="test-workspace-id",
            source_type="s3",
            mime_type="application/pdf",
            size_bytes=2048,
            chunk_count=10,
            status="processed",
            created_at=now,
            updated_at=now,
            metadata=None,
        ),
        Document(
            id="doc-002",
            name="second-document.txt",
            workspace_id="test-workspace-id",
            source_type="s3",
            mime_type="text/plain",
            size_bytes=512,
            chunk_count=3,
            status="processed",
            created_at=now,
            updated_at=now,
            metadata={"tag": "test"},
        ),
    ]


@pytest.fixture
def mock_db_service(sample_documents):
    """Create a mock database service pre-configured with sample documents."""
    mock = AsyncMock()
    mock.get_documents = AsyncMock(return_value=(sample_documents, len(sample_documents)))
    mock.get_document = AsyncMock(return_value=sample_documents[0])
    return mock


@pytest.fixture
def mock_resolved_auth(mock_api_key_info):
    """Create a ResolvedAuth with workspace from the API key."""
    return ResolvedAuth(key_info=mock_api_key_info, workspace_id=mock_api_key_info.workspace_id)


@pytest.fixture
def app(mock_api_key_info, mock_db_service, mock_resolved_auth):
    """Create a FastAPI app with overridden dependencies."""
    application = create_app()
    application.dependency_overrides[get_api_key_info] = lambda: mock_api_key_info
    application.dependency_overrides[get_read_permission] = lambda: mock_api_key_info
    application.dependency_overrides[resolve_workspace_read] = lambda: mock_resolved_auth
    application.dependency_overrides[get_database] = lambda: mock_db_service
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestListDocuments:
    """Tests for GET /v1/documents."""

    async def test_list_documents_success(self, client, mock_db_service, sample_documents):
        """Should return documents list with pagination metadata."""
        response = await client.get("/v1/documents", headers={"X-API-Key": "ink_test_key"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert len(data["documents"]) == 2
        assert data["documents"][0]["id"] == "doc-001"
        assert data["documents"][0]["name"] == "first-document.pdf"
        assert data["documents"][1]["id"] == "doc-002"

    async def test_list_documents_empty(self, client, mock_db_service):
        """Should return empty list when no documents exist."""
        mock_db_service.get_documents = AsyncMock(return_value=([], 0))

        response = await client.get("/v1/documents", headers={"X-API-Key": "ink_test_key"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["documents"] == []
        assert data["page"] == 1
        assert data["page_size"] == 20

    async def test_list_documents_custom_pagination(self, client, mock_db_service):
        """Should pass custom page and page_size to database service."""
        mock_db_service.get_documents = AsyncMock(return_value=([], 0))

        response = await client.get(
            "/v1/documents?page=3&page_size=50",
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 3
        assert data["page_size"] == 50
        mock_db_service.get_documents.assert_awaited_once_with(
            workspace_id="test-workspace-id",
            page=3,
            page_size=50,
        )

    async def test_list_documents_invalid_page_negative(self, client):
        """Should return 422 for page < 1."""
        response = await client.get("/v1/documents?page=0", headers={"X-API-Key": "ink_test_key"})
        assert response.status_code == 422

    async def test_list_documents_invalid_page_zero(self, client):
        """Should return 422 for page=0."""
        response = await client.get("/v1/documents?page=0", headers={"X-API-Key": "ink_test_key"})
        assert response.status_code == 422

    async def test_list_documents_page_size_exceeds_max(self, client):
        """Should return 422 for page_size > 100."""
        response = await client.get(
            "/v1/documents?page_size=101", headers={"X-API-Key": "ink_test_key"}
        )
        assert response.status_code == 422

    async def test_list_documents_page_size_zero(self, client):
        """Should return 422 for page_size < 1."""
        response = await client.get(
            "/v1/documents?page_size=0", headers={"X-API-Key": "ink_test_key"}
        )
        assert response.status_code == 422

    async def test_list_documents_page_size_negative(self, client):
        """Should return 422 for negative page_size."""
        response = await client.get(
            "/v1/documents?page_size=-5", headers={"X-API-Key": "ink_test_key"}
        )
        assert response.status_code == 422

    async def test_list_documents_requires_read_permission(self, mock_db_service):
        """Should return 403 when API key lacks read permission."""
        search_only_key = APIKeyInfo(
            key_id="test-key-search",
            user_id="test-user-id",
            workspace_id="test-workspace-id",
            permissions=["search"],
            rate_limit=100,
            expires_at=None,
            status="active",
        )

        application = create_app()
        application.dependency_overrides[get_api_key_info] = lambda: search_only_key
        # Do NOT override get_read_permission — let the real dependency check permissions
        application.dependency_overrides[get_database] = lambda: mock_db_service

        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/v1/documents", headers={"X-API-Key": "ink_test_key"})
        assert response.status_code == 403
        application.dependency_overrides.clear()

    async def test_list_documents_no_api_key(self, mock_db_service):
        """Should return 401 when no API key is provided."""
        application = create_app()
        # Do NOT override auth dependencies — let the real ones run
        application.dependency_overrides[get_database] = lambda: mock_db_service

        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/v1/documents")
        assert response.status_code == 401
        application.dependency_overrides.clear()


class TestGetDocument:
    """Tests for GET /v1/documents/{document_id}."""

    async def test_get_document_success(self, client, sample_documents):
        """Should return a single document by ID."""
        response = await client.get("/v1/documents/doc-001", headers={"X-API-Key": "ink_test_key"})
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "doc-001"
        assert data["name"] == "first-document.pdf"
        assert data["workspace_id"] == "test-workspace-id"
        assert data["source_type"] == "s3"
        assert data["mime_type"] == "application/pdf"
        assert data["size_bytes"] == 2048
        assert data["chunk_count"] == 10
        assert data["status"] == "processed"

    async def test_get_document_not_found(self, client, mock_db_service):
        """Should return 404 when document does not exist."""
        mock_db_service.get_document = AsyncMock(return_value=None)

        response = await client.get(
            "/v1/documents/nonexistent-doc-id",
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Document not found"

    async def test_get_document_passes_workspace_id(self, client, mock_db_service):
        """Should scope the document lookup to the workspace from the API key."""
        mock_db_service.get_document = AsyncMock(return_value=None)

        await client.get("/v1/documents/doc-xyz", headers={"X-API-Key": "ink_test_key"})
        mock_db_service.get_document.assert_awaited_once_with(
            document_id="doc-xyz",
            workspace_id="test-workspace-id",
        )

    async def test_get_document_invalid_id_format(self, client, mock_db_service):
        """Should still hit the endpoint for any string document_id and return 404 if not found."""
        mock_db_service.get_document = AsyncMock(return_value=None)

        response = await client.get(
            "/v1/documents/!!!invalid!!!",
            headers={"X-API-Key": "ink_test_key"},
        )
        # The endpoint accepts any string path param; it returns 404 if DB returns None
        assert response.status_code == 404

    async def test_get_document_requires_read_permission(self, mock_db_service):
        """Should return 403 when API key lacks read permission."""
        search_only_key = APIKeyInfo(
            key_id="test-key-search",
            user_id="test-user-id",
            workspace_id="test-workspace-id",
            permissions=["search"],
            rate_limit=100,
            expires_at=None,
            status="active",
        )

        application = create_app()
        application.dependency_overrides[get_api_key_info] = lambda: search_only_key
        application.dependency_overrides[get_database] = lambda: mock_db_service

        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/v1/documents/doc-001", headers={"X-API-Key": "ink_test_key"})
        assert response.status_code == 403
        application.dependency_overrides.clear()
