"""Shared fixtures for the offline REST + MCP contract suite (M6 #30).

All fixtures here are offline: API keys are plain :class:`APIKeyInfo` objects,
the databases / search service are ``AsyncMock`` stand-ins, and nothing touches
a live stack. The REST helpers build a FastAPI app with the auth dependencies
overridden (so a test can pick the permission set it wants) and the lifespan DB
init stubbed, mirroring ``tests/integration/test_api_path.py`` and
``tests/unit/test_search_endpoint.py``. The MCP helpers patch
``get_database`` / ``get_search_service`` at the ``mcp_server.server`` boundary,
exactly like ``tests/security/test_mcp_workspace_boundaries.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from src.models.api_key import APIKeyInfo
from src.models.document import Document
from src.models.search import SearchResponse, SearchResult

# Every test in this package belongs to the contract surface.
pytestmark = [pytest.mark.contract]


# --------------------------------------------------------------------------- #
# API keys with the various permission sets the contract distinguishes.
# --------------------------------------------------------------------------- #
def _make_key(
    *,
    permissions: list[str],
    workspace_id: str | None = "ws-1",
    expires_at: datetime | None = None,
    key_id: str = "key-1",
    user_id: str = "user-1",
) -> APIKeyInfo:
    return APIKeyInfo(
        key_id=key_id,
        user_id=user_id,
        workspace_id=workspace_id,
        permissions=permissions,  # type: ignore[arg-type]
        rate_limit=100,
        expires_at=expires_at,
        status="active",
    )


@pytest.fixture
def search_only_key() -> APIKeyInfo:
    """Key that can search but cannot read documents or write."""
    return _make_key(permissions=["search"], key_id="key-search")


@pytest.fixture
def read_key() -> APIKeyInfo:
    """Key with read permission only (no search, no write)."""
    return _make_key(permissions=["read"], key_id="key-read")


@pytest.fixture
def write_key() -> APIKeyInfo:
    """Key with write permission only (no read/search)."""
    return _make_key(permissions=["write"], key_id="key-write")


@pytest.fixture
def read_write_key() -> APIKeyInfo:
    """Key with read + write (the typical ingest/manage key)."""
    return _make_key(permissions=["read", "write"], key_id="key-rw")


@pytest.fixture
def full_key() -> APIKeyInfo:
    """Key with read + search + write — the union used for happy-path shapes."""
    return _make_key(permissions=["read", "search", "write"], key_id="key-full")


@pytest.fixture
def expired_key() -> APIKeyInfo:
    """A key whose expiry is in the past (rejected at validation, 401)."""
    return _make_key(
        permissions=["read", "search", "write"],
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        key_id="key-expired",
    )


# --------------------------------------------------------------------------- #
# Sample domain objects used to populate mocked responses.
# --------------------------------------------------------------------------- #
@pytest.fixture
def sample_document() -> Document:
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return Document(
        id="doc-1",
        name="report.pdf",
        workspace_id="ws-1",
        source_type="upload",
        mime_type="application/pdf",
        size_bytes=2048,
        chunk_count=3,
        status="processed",
        created_at=now,
        updated_at=now,
        metadata={"ingested_at": now.isoformat(), "source_uri": "s3://b/report.pdf"},
    )


@pytest.fixture
def minimal_search_result() -> SearchResult:
    """A SearchResult built with ONLY the core required fields.

    Proves the provenance / freshness / risk / citation optionals are omittable
    and stay backward-compatible.
    """
    return SearchResult(
        chunk_id="chunk-1",
        document_id="doc-1",
        document_name="report.pdf",
        content="the relevant passage",
        score=0.91,
    )


@pytest.fixture
def search_response(minimal_search_result: SearchResult) -> SearchResponse:
    return SearchResponse(
        results=[minimal_search_result],
        query="quarterly revenue",
        total_results=1,
        processing_time_ms=12.5,
        search_mode="semantic",
    )


# --------------------------------------------------------------------------- #
# Mocked databases (single- and multi-workspace) and search service.
# --------------------------------------------------------------------------- #
@pytest.fixture
def single_workspace_db(sample_document: Document) -> AsyncMock:
    """A mock DB whose user owns exactly one workspace (``ws-1``)."""
    db = AsyncMock()
    db.get_user_workspace_ids = AsyncMock(return_value=["ws-1"])
    db.get_document = AsyncMock(return_value=sample_document)
    db.get_document_by_id = AsyncMock(return_value=sample_document)
    db.get_documents = AsyncMock(return_value=([sample_document], 1))
    db.get_documents_multi_workspace = AsyncMock(return_value=([sample_document], 1))
    db.get_document_chunks = AsyncMock(return_value=[])
    db.get_document_chunks_by_doc_id = AsyncMock(return_value=[])
    db.get_document_upload_fields = AsyncMock(
        return_value={
            "document_id": "doc-1",
            "workspace_id": "ws-1",
            "user_id": "user-1",
            "filename": "report.pdf",
            "original_filename": "report.pdf",
            "content_type": "application/pdf",
            "size_bytes": 2048,
            "storage_backend": "s3",
            "storage_path": "ws-1/report.pdf",
            "storage_bucket": "bucket",
            "storage_url": "s3://bucket/ws-1/report.pdf",
        }
    )
    db.create_or_reset_pending_document = AsyncMock(return_value=None)
    return db


@pytest.fixture
def multi_workspace_db(sample_document: Document) -> AsyncMock:
    """A mock DB whose user owns two workspaces (``ws-1`` and ``ws-2``)."""
    db = AsyncMock()
    db.get_user_workspace_ids = AsyncMock(return_value=["ws-1", "ws-2"])
    db.get_document = AsyncMock(return_value=sample_document)
    db.get_document_by_id = AsyncMock(return_value=sample_document)
    db.get_documents_multi_workspace = AsyncMock(return_value=([sample_document], 1))
    db.get_document_chunks_by_doc_id = AsyncMock(return_value=[])
    return db


@pytest.fixture
def mock_search_service(search_response: SearchResponse) -> AsyncMock:
    svc = AsyncMock()
    svc.search = AsyncMock(return_value=search_response)
    return svc
