"""Unit tests for the POST /v1/documents upload endpoint."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import create_app
from src.models.api_key import APIKeyInfo
from src.services.auth import (
    ResolvedAuth,
    get_api_key_info,
    get_write_permission,
    resolve_workspace_write,
)
from src.services.database import get_database

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def write_key():
    """API key with write permission."""
    return APIKeyInfo(
        key_id="test-key-write",
        user_id="test-user-id",
        workspace_id="test-workspace-id",
        permissions=["read", "search", "write"],
        rate_limit=100,
        expires_at=None,
        status="active",
    )


@pytest.fixture
def read_only_key():
    """API key without write permission."""
    return APIKeyInfo(
        key_id="test-key-readonly",
        user_id="test-user-id",
        workspace_id="test-workspace-id",
        permissions=["read", "search"],
        rate_limit=100,
        expires_at=None,
        status="active",
    )


@pytest.fixture
def user_scoped_key():
    """API key without a workspace_id (user-scoped)."""
    return APIKeyInfo(
        key_id="test-key-user",
        user_id="test-user-id",
        workspace_id=None,
        permissions=["read", "search", "write"],
        rate_limit=100,
        expires_at=None,
        status="active",
    )


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def mock_storage():
    storage = MagicMock()
    storage.generate_key.return_value = "test-workspace-id/fake-uuid/test.pdf"
    storage.upload_file = AsyncMock(return_value="test-workspace-id/fake-uuid/test.pdf")
    storage.build_storage_url.return_value = (
        "s3://inherent-documents/test-workspace-id/fake-uuid/test.pdf"
    )
    storage._bucket = "inherent-documents"
    return storage


@pytest.fixture
def mock_mq():
    mq = AsyncMock()
    mq.publish = AsyncMock(return_value="1234567890-0")
    return mq


@pytest.fixture
def mock_resolved_auth_write(write_key):
    """Create a ResolvedAuth with workspace from the write key."""
    return ResolvedAuth(key_info=write_key, workspace_id=write_key.workspace_id)


@pytest.fixture
def app(write_key, mock_db, mock_storage, mock_mq, mock_resolved_auth_write):
    """Create app with dependency overrides and patched singletons."""
    application = create_app()
    application.dependency_overrides[get_api_key_info] = lambda: write_key
    application.dependency_overrides[get_write_permission] = lambda: write_key
    application.dependency_overrides[resolve_workspace_write] = lambda: mock_resolved_auth_write
    application.dependency_overrides[get_database] = lambda: mock_db

    with (
        patch("src.api.v1.documents.get_storage_service", return_value=mock_storage),
        patch("src.api.v1.documents.get_mq_service", new_callable=AsyncMock, return_value=mock_mq),
    ):
        yield application

    application.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Helper to build multipart file payload
# ---------------------------------------------------------------------------


def _file_payload(
    content: bytes = b"hello world",
    filename: str = "test.pdf",
    content_type: str = "application/pdf",
):
    return {"file": (filename, io.BytesIO(content), content_type)}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUploadDocumentSuccess:
    """Happy-path tests for POST /v1/documents."""

    async def test_upload_returns_201(self, client):
        response = await client.post(
            "/v1/documents",
            files=_file_payload(),
            headers={"X-API-Key": "ink_test_key"},
        )
        assert response.status_code == 201

    async def test_upload_response_shape(self, client):
        response = await client.post(
            "/v1/documents",
            files=_file_payload(),
            headers={"X-API-Key": "ink_test_key"},
        )
        data = response.json()
        assert data["name"] == "test.pdf"
        assert data["workspace_id"] == "test-workspace-id"
        assert data["mime_type"] == "application/pdf"
        assert data["size_bytes"] == len(b"hello world")
        assert data["status"] == "pending"
        assert "document_id" in data
        assert "storage_url" in data
        assert "message" in data

    async def test_upload_calls_storage(self, mock_storage, write_key, mock_db, mock_mq):
        """Verify that the storage service is called with expected arguments."""
        application = create_app()
        application.dependency_overrides[get_api_key_info] = lambda: write_key
        application.dependency_overrides[get_write_permission] = lambda: write_key
        application.dependency_overrides[resolve_workspace_write] = lambda: ResolvedAuth(
            key_info=write_key, workspace_id=write_key.workspace_id
        )
        application.dependency_overrides[get_database] = lambda: mock_db

        with (
            patch("src.api.v1.documents.get_storage_service", return_value=mock_storage),
            patch(
                "src.api.v1.documents.get_mq_service",
                new_callable=AsyncMock,
                return_value=mock_mq,
            ),
        ):
            transport = ASGITransport(app=application)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                await ac.post(
                    "/v1/documents",
                    files=_file_payload(),
                    headers={"X-API-Key": "ink_test_key"},
                )

        mock_storage.generate_key.assert_called_once_with("test-workspace-id", "test.pdf")
        mock_storage.upload_file.assert_awaited_once()

        application.dependency_overrides.clear()

    async def test_upload_publishes_mq_message(self, write_key, mock_db, mock_storage, mock_mq):
        """Verify that the MQ publish is called with the correct topic."""
        application = create_app()
        application.dependency_overrides[get_api_key_info] = lambda: write_key
        application.dependency_overrides[get_write_permission] = lambda: write_key
        application.dependency_overrides[resolve_workspace_write] = lambda: ResolvedAuth(
            key_info=write_key, workspace_id=write_key.workspace_id
        )
        application.dependency_overrides[get_database] = lambda: mock_db

        with (
            patch("src.api.v1.documents.get_storage_service", return_value=mock_storage),
            patch(
                "src.api.v1.documents.get_mq_service",
                new_callable=AsyncMock,
                return_value=mock_mq,
            ),
        ):
            transport = ASGITransport(app=application)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                await ac.post(
                    "/v1/documents",
                    files=_file_payload(),
                    headers={"X-API-Key": "ink_test_key"},
                )

        mock_mq.publish.assert_awaited_once()
        call_args = mock_mq.publish.call_args
        assert call_args[0][0] == "core.document.uploaded.v1"

        msg = call_args[0][1]
        assert msg["event_type"] == "document.uploaded"
        assert msg["workspace_id"] == "test-workspace-id"
        assert msg["user_id"] == "test-user-id"
        assert msg["original_filename"] == "test.pdf"
        assert msg["content_type"] == "application/pdf"
        assert msg["storage_backend"] == "s3"

        application.dependency_overrides.clear()


class TestUploadDocumentValidation:
    """Validation and error-path tests."""

    async def test_unsupported_mime_type(self, write_key, mock_db, mock_storage, mock_mq):
        application = create_app()
        application.dependency_overrides[get_api_key_info] = lambda: write_key
        application.dependency_overrides[get_write_permission] = lambda: write_key
        application.dependency_overrides[resolve_workspace_write] = lambda: ResolvedAuth(
            key_info=write_key, workspace_id=write_key.workspace_id
        )
        application.dependency_overrides[get_database] = lambda: mock_db

        with (
            patch("src.api.v1.documents.get_storage_service", return_value=mock_storage),
            patch(
                "src.api.v1.documents.get_mq_service",
                new_callable=AsyncMock,
                return_value=mock_mq,
            ),
        ):
            transport = ASGITransport(app=application)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.post(
                    "/v1/documents",
                    files=_file_payload(content_type="image/png"),
                    headers={"X-API-Key": "ink_test_key"},
                )

        assert response.status_code == 400
        application.dependency_overrides.clear()

    async def test_empty_file(self, write_key, mock_db, mock_storage, mock_mq):
        application = create_app()
        application.dependency_overrides[get_api_key_info] = lambda: write_key
        application.dependency_overrides[get_write_permission] = lambda: write_key
        application.dependency_overrides[resolve_workspace_write] = lambda: ResolvedAuth(
            key_info=write_key, workspace_id=write_key.workspace_id
        )
        application.dependency_overrides[get_database] = lambda: mock_db

        with (
            patch("src.api.v1.documents.get_storage_service", return_value=mock_storage),
            patch(
                "src.api.v1.documents.get_mq_service",
                new_callable=AsyncMock,
                return_value=mock_mq,
            ),
        ):
            transport = ASGITransport(app=application)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.post(
                    "/v1/documents",
                    files=_file_payload(content=b""),
                    headers={"X-API-Key": "ink_test_key"},
                )

        assert response.status_code == 400
        application.dependency_overrides.clear()

    async def test_file_too_large(self, write_key, mock_db, mock_storage, mock_mq):
        big_content = b"x" * (50 * 1024 * 1024 + 1)  # 50 MB + 1 byte

        application = create_app()
        application.dependency_overrides[get_api_key_info] = lambda: write_key
        application.dependency_overrides[get_write_permission] = lambda: write_key
        application.dependency_overrides[resolve_workspace_write] = lambda: ResolvedAuth(
            key_info=write_key, workspace_id=write_key.workspace_id
        )
        application.dependency_overrides[get_database] = lambda: mock_db

        with (
            patch("src.api.v1.documents.get_storage_service", return_value=mock_storage),
            patch(
                "src.api.v1.documents.get_mq_service",
                new_callable=AsyncMock,
                return_value=mock_mq,
            ),
        ):
            transport = ASGITransport(app=application)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.post(
                    "/v1/documents",
                    files=_file_payload(content=big_content),
                    headers={"X-API-Key": "ink_test_key"},
                )

        assert response.status_code == 400
        application.dependency_overrides.clear()

    async def test_user_scoped_key_no_workspace_header(
        self, user_scoped_key, mock_db, mock_storage, mock_mq
    ):
        """User-scoped key without X-Workspace-Id header and no workspaces returns 400."""
        mock_db.get_user_workspace_ids = AsyncMock(return_value=[])

        application = create_app()
        application.dependency_overrides[get_api_key_info] = lambda: user_scoped_key
        application.dependency_overrides[get_write_permission] = lambda: user_scoped_key
        application.dependency_overrides[get_database] = lambda: mock_db

        with (
            patch("src.services.auth.get_database", new_callable=AsyncMock, return_value=mock_db),
            patch("src.api.v1.documents.get_storage_service", return_value=mock_storage),
            patch(
                "src.api.v1.documents.get_mq_service",
                new_callable=AsyncMock,
                return_value=mock_mq,
            ),
        ):
            transport = ASGITransport(app=application)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.post(
                    "/v1/documents",
                    files=_file_payload(),
                    headers={"X-API-Key": "ink_test_key"},
                )

        assert response.status_code == 400
        application.dependency_overrides.clear()


class TestUploadDocumentAuth:
    """Auth-related tests for upload endpoint."""

    async def test_requires_write_permission(self, read_only_key, mock_db):
        """Should return 403 when API key lacks write permission."""
        application = create_app()
        application.dependency_overrides[get_api_key_info] = lambda: read_only_key
        # Do NOT override get_write_permission — let real dependency run
        application.dependency_overrides[get_database] = lambda: mock_db

        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/v1/documents",
                files=_file_payload(),
                headers={"X-API-Key": "ink_test_key"},
            )
        assert response.status_code == 403
        application.dependency_overrides.clear()

    async def test_no_api_key(self, mock_db):
        """Should return 401 when no API key is provided."""
        application = create_app()
        application.dependency_overrides[get_database] = lambda: mock_db

        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/v1/documents",
                files=_file_payload(),
            )
        assert response.status_code == 401
        application.dependency_overrides.clear()


class TestUploadDocumentServiceFailures:
    """Tests for graceful degradation when downstream services fail."""

    async def test_storage_failure_returns_503(self, write_key, mock_db, mock_mq):
        """S3 failure should return 503."""
        failing_storage = MagicMock()
        failing_storage.generate_key.return_value = "ws/uuid/file.pdf"
        failing_storage.upload_file = AsyncMock(side_effect=Exception("S3 unreachable"))

        application = create_app()
        application.dependency_overrides[get_api_key_info] = lambda: write_key
        application.dependency_overrides[get_write_permission] = lambda: write_key
        application.dependency_overrides[resolve_workspace_write] = lambda: ResolvedAuth(
            key_info=write_key, workspace_id=write_key.workspace_id
        )
        application.dependency_overrides[get_database] = lambda: mock_db

        with (
            patch("src.api.v1.documents.get_storage_service", return_value=failing_storage),
            patch(
                "src.api.v1.documents.get_mq_service",
                new_callable=AsyncMock,
                return_value=mock_mq,
            ),
        ):
            transport = ASGITransport(app=application)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.post(
                    "/v1/documents",
                    files=_file_payload(),
                    headers={"X-API-Key": "ink_test_key"},
                )

        assert response.status_code == 503
        application.dependency_overrides.clear()

    async def test_mq_failure_still_returns_201(self, write_key, mock_db, mock_storage):
        """MQ failure should NOT fail the request — file is already in S3."""
        failing_mq = AsyncMock()
        failing_mq.publish = AsyncMock(side_effect=Exception("Redis down"))

        application = create_app()
        application.dependency_overrides[get_api_key_info] = lambda: write_key
        application.dependency_overrides[get_write_permission] = lambda: write_key
        application.dependency_overrides[resolve_workspace_write] = lambda: ResolvedAuth(
            key_info=write_key, workspace_id=write_key.workspace_id
        )
        application.dependency_overrides[get_database] = lambda: mock_db

        with (
            patch("src.api.v1.documents.get_storage_service", return_value=mock_storage),
            patch(
                "src.api.v1.documents.get_mq_service",
                new_callable=AsyncMock,
                return_value=failing_mq,
            ),
        ):
            transport = ASGITransport(app=application)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.post(
                    "/v1/documents",
                    files=_file_payload(),
                    headers={"X-API-Key": "ink_test_key"},
                )

        assert response.status_code == 201
        application.dependency_overrides.clear()


class TestUploadAllowedMimeTypes:
    """Verify each allowed MIME type is accepted."""

    @pytest.mark.parametrize(
        "mime",
        [
            "text/plain",
            "text/markdown",
            "text/csv",
            "text/html",
            "application/pdf",
            "application/json",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ],
    )
    async def test_allowed_mime_types_accepted(
        self, mime, write_key, mock_db, mock_storage, mock_mq
    ):
        application = create_app()
        application.dependency_overrides[get_api_key_info] = lambda: write_key
        application.dependency_overrides[get_write_permission] = lambda: write_key
        application.dependency_overrides[resolve_workspace_write] = lambda: ResolvedAuth(
            key_info=write_key, workspace_id=write_key.workspace_id
        )
        application.dependency_overrides[get_database] = lambda: mock_db

        with (
            patch("src.api.v1.documents.get_storage_service", return_value=mock_storage),
            patch(
                "src.api.v1.documents.get_mq_service",
                new_callable=AsyncMock,
                return_value=mock_mq,
            ),
        ):
            transport = ASGITransport(app=application)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.post(
                    "/v1/documents",
                    files=_file_payload(content_type=mime),
                    headers={"X-API-Key": "ink_test_key"},
                )

        assert (
            response.status_code == 201
        ), f"MIME {mime} should be accepted but got {response.status_code}"
        application.dependency_overrides.clear()

    async def test_xlsx_rejected_until_extraction_is_supported(
        self, write_key, mock_db, mock_storage, mock_mq
    ):
        """Do not accept spreadsheet uploads until ingestion has an XLSX extractor."""
        application = create_app()
        application.dependency_overrides[get_api_key_info] = lambda: write_key
        application.dependency_overrides[get_write_permission] = lambda: write_key
        application.dependency_overrides[resolve_workspace_write] = lambda: ResolvedAuth(
            key_info=write_key, workspace_id=write_key.workspace_id
        )
        application.dependency_overrides[get_database] = lambda: mock_db

        with (
            patch("src.api.v1.documents.get_storage_service", return_value=mock_storage),
            patch(
                "src.api.v1.documents.get_mq_service",
                new_callable=AsyncMock,
                return_value=mock_mq,
            ),
        ):
            transport = ASGITransport(app=application)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.post(
                    "/v1/documents",
                    files=_file_payload(
                        filename="sheet.xlsx",
                        content_type=(
                            "application/vnd.openxmlformats-officedocument." "spreadsheetml.sheet"
                        ),
                    ),
                    headers={"X-API-Key": "ink_test_key"},
                )

        assert response.status_code == 400
        application.dependency_overrides.clear()
