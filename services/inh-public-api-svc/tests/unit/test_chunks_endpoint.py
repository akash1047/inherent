"""Unit tests for the chunks API endpoints."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import create_app
from src.models.api_key import APIKeyInfo
from src.models.document import Document, DocumentChunk
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
def sample_document():
    """Create a sample Document object."""
    now = datetime.now(timezone.utc)
    return Document(
        id="doc-001",
        name="test-document.pdf",
        workspace_id="test-workspace-id",
        source_type="s3",
        mime_type="application/pdf",
        size_bytes=2048,
        chunk_count=3,
        status="processed",
        created_at=now,
        updated_at=now,
        metadata=None,
    )


@pytest.fixture
def sample_chunks():
    """Create sample DocumentChunk objects."""
    return [
        DocumentChunk(
            id="chunk-001",
            document_id="doc-001",
            content="This is the first chunk of the document.",
            chunk_index=0,
            token_count=10,
            metadata={"heading": "Introduction"},
        ),
        DocumentChunk(
            id="chunk-002",
            document_id="doc-001",
            content="This is the second chunk with more details.",
            chunk_index=1,
            token_count=12,
            metadata={"heading": "Details"},
        ),
        DocumentChunk(
            id="chunk-003",
            document_id="doc-001",
            content="The final chunk with a conclusion.",
            chunk_index=2,
            token_count=8,
            metadata={"heading": "Conclusion"},
        ),
    ]


@pytest.fixture
def mock_db_service(sample_document, sample_chunks):
    """Create a mock database service."""
    mock = AsyncMock()
    mock.get_document = AsyncMock(return_value=sample_document)
    mock.get_document_chunks = AsyncMock(return_value=sample_chunks)
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


class TestGetDocumentChunks:
    """Tests for GET /v1/chunks/{document_id}."""

    async def test_get_chunks_success(self, client, sample_chunks):
        """Should return all chunks for a document."""
        response = await client.get("/v1/chunks/doc-001", headers={"X-API-Key": "ink_test_key"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        assert data[0]["id"] == "chunk-001"
        assert data[0]["document_id"] == "doc-001"
        assert data[0]["content"] == "This is the first chunk of the document."
        assert data[0]["chunk_index"] == 0
        assert data[0]["token_count"] == 10
        assert data[0]["metadata"] == {"heading": "Introduction"}
        assert data[1]["chunk_index"] == 1
        assert data[2]["chunk_index"] == 2

    async def test_get_chunks_empty(self, client, mock_db_service, sample_document):
        """Should return empty list when document exists but has no chunks."""
        mock_db_service.get_document = AsyncMock(return_value=sample_document)
        mock_db_service.get_document_chunks = AsyncMock(return_value=[])

        response = await client.get("/v1/chunks/doc-001", headers={"X-API-Key": "ink_test_key"})
        assert response.status_code == 200
        data = response.json()
        assert data == []

    async def test_get_chunks_document_not_found(self, client, mock_db_service):
        """Should return 404 when document does not exist."""
        mock_db_service.get_document = AsyncMock(return_value=None)

        response = await client.get(
            "/v1/chunks/nonexistent-doc",
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Document not found"

    async def test_get_chunks_passes_workspace_id(self, client, mock_db_service):
        """Should scope the document lookup to the workspace from the API key."""
        mock_db_service.get_document = AsyncMock(return_value=None)

        await client.get("/v1/chunks/doc-xyz", headers={"X-API-Key": "ink_test_key"})
        mock_db_service.get_document.assert_awaited_once_with(
            document_id="doc-xyz",
            workspace_id="test-workspace-id",
        )

    async def test_get_chunks_requires_read_permission(self, mock_db_service):
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
            response = await ac.get("/v1/chunks/doc-001", headers={"X-API-Key": "ink_test_key"})
        assert response.status_code == 403
        application.dependency_overrides.clear()

    async def test_get_chunks_calls_get_document_chunks_with_correct_args(
        self, client, mock_db_service
    ):
        """Should call get_document_chunks with the correct document_id and workspace_id."""
        await client.get("/v1/chunks/doc-001", headers={"X-API-Key": "ink_test_key"})
        mock_db_service.get_document_chunks.assert_awaited_once_with(
            document_id="doc-001",
            workspace_id="test-workspace-id",
        )


class TestGetDocumentContext:
    """Tests for GET /v1/chunks/{document_id}/context."""

    async def test_get_context_success(self, client, sample_chunks, sample_document):
        """Should return document metadata, chunks, and combined full text."""
        response = await client.get(
            "/v1/chunks/doc-001/context", headers={"X-API-Key": "ink_test_key"}
        )
        assert response.status_code == 200
        data = response.json()

        # Document metadata
        assert data["document"]["id"] == "doc-001"
        assert data["document"]["name"] == "test-document.pdf"

        # Chunks
        assert len(data["chunks"]) == 3
        assert data["chunks"][0]["chunk_index"] == 0
        assert data["chunks"][2]["chunk_index"] == 2

        # Full text is all chunk contents joined with double newline
        expected_text = (
            "This is the first chunk of the document.\n\n"
            "This is the second chunk with more details.\n\n"
            "The final chunk with a conclusion."
        )
        assert data["full_text"] == expected_text

    async def test_get_context_document_not_found(self, client, mock_db_service):
        """Should return 404 when document does not exist."""
        mock_db_service.get_document = AsyncMock(return_value=None)

        response = await client.get(
            "/v1/chunks/nonexistent-doc/context",
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Document not found"

    async def test_get_context_no_chunks(self, client, mock_db_service, sample_document):
        """Should return empty full_text when document has no chunks."""
        mock_db_service.get_document = AsyncMock(return_value=sample_document)
        mock_db_service.get_document_chunks = AsyncMock(return_value=[])

        response = await client.get(
            "/v1/chunks/doc-001/context", headers={"X-API-Key": "ink_test_key"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["document"]["id"] == "doc-001"
        assert data["chunks"] == []
        assert data["full_text"] == ""

    async def test_get_context_passes_workspace_id(self, client, mock_db_service):
        """Should scope the lookup to the workspace from the API key."""
        mock_db_service.get_document = AsyncMock(return_value=None)

        await client.get("/v1/chunks/doc-xyz/context", headers={"X-API-Key": "ink_test_key"})
        mock_db_service.get_document.assert_awaited_once_with(
            document_id="doc-xyz",
            workspace_id="test-workspace-id",
        )

    async def test_get_context_requires_read_permission(self, mock_db_service):
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
            response = await ac.get(
                "/v1/chunks/doc-001/context",
                headers={"X-API-Key": "ink_test_key"},
            )
        assert response.status_code == 403
        application.dependency_overrides.clear()

    async def test_get_context_single_chunk(self, client, mock_db_service, sample_document):
        """Should return full_text without trailing newlines for a single chunk."""
        single_chunk = DocumentChunk(
            id="chunk-only",
            document_id="doc-001",
            content="Only chunk content here.",
            chunk_index=0,
            token_count=5,
            metadata=None,
        )
        mock_db_service.get_document = AsyncMock(return_value=sample_document)
        mock_db_service.get_document_chunks = AsyncMock(return_value=[single_chunk])

        response = await client.get(
            "/v1/chunks/doc-001/context", headers={"X-API-Key": "ink_test_key"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["full_text"] == "Only chunk content here."
        assert len(data["chunks"]) == 1
