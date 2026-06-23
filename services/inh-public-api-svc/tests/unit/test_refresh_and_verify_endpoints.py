"""Unit tests for POST /v1/documents/{id}/refresh (#42) and POST /v1/verify-claim (#39).

Offline: DB and MQ are mocked; no real services are touched.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

import src.api.v1.documents as documents_module
from src.main import create_app
from src.models.api_key import APIKeyInfo
from src.services.auth import (
    ResolvedAuth,
    get_api_key_info,
    get_read_permission,
    get_write_permission,
    resolve_workspace_write,
)
from src.services.database import get_database


@pytest.fixture
def rw_key() -> APIKeyInfo:
    return APIKeyInfo(
        key_id="rw-key",
        user_id="user-1",
        workspace_id="ws-1",
        permissions=["read", "write", "search"],
        rate_limit=100,
        expires_at=None,
        status="active",
    )


@pytest.fixture
def stored_fields() -> dict:
    return {
        "document_id": "doc-1",
        "workspace_id": "ws-1",
        "user_id": "user-1",
        "filename": "ws-1/abc.pdf",
        "original_filename": "abc.pdf",
        "content_type": "application/pdf",
        "size_bytes": 2048,
        "storage_backend": "s3",
        "storage_path": "ws-1/abc.pdf",
        "storage_bucket": "inherent-documents",
        "storage_url": "https://example/abc.pdf",
    }


@pytest.fixture
def mock_db(stored_fields) -> AsyncMock:
    mock = AsyncMock()
    mock.get_document_upload_fields = AsyncMock(return_value=stored_fields)
    mock.create_or_reset_pending_document = AsyncMock(return_value=None)
    mock.mark_document_failed = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def mock_mq() -> AsyncMock:
    mq = AsyncMock()
    mq.publish = AsyncMock(return_value="1-0")
    return mq


@pytest.fixture
def app(rw_key, mock_db, mock_mq, monkeypatch):
    application = create_app()
    application.dependency_overrides[get_api_key_info] = lambda: rw_key
    application.dependency_overrides[get_write_permission] = lambda: rw_key
    application.dependency_overrides[get_read_permission] = lambda: rw_key
    application.dependency_overrides[resolve_workspace_write] = lambda: ResolvedAuth(
        key_info=rw_key, workspace_id="ws-1"
    )
    application.dependency_overrides[get_database] = lambda: mock_db

    async def _get_mq():
        return mock_mq

    monkeypatch.setattr(documents_module, "get_mq_service", _get_mq)
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestRefreshEndpoint:
    async def test_refresh_republishes_event(self, client, mock_db, mock_mq, stored_fields):
        resp = await client.post("/v1/documents/doc-1/refresh", headers={"X-API-Key": "k"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["document_id"] == "doc-1"
        assert body["status"] == "pending"

        # Row reset to pending and MQ event re-published from the stored row.
        mock_db.create_or_reset_pending_document.assert_awaited_once()
        mock_mq.publish.assert_awaited_once()
        topic, message = mock_mq.publish.await_args.args
        assert message["event_type"] == "document.uploaded"
        assert message["document_id"] == "doc-1"
        assert message["storage_path"] == stored_fields["storage_path"]
        assert message["user_id"] == "user-1"

    async def test_refresh_404_when_document_missing(self, client, mock_db, mock_mq):
        mock_db.get_document_upload_fields = AsyncMock(return_value=None)
        resp = await client.post("/v1/documents/missing/refresh", headers={"X-API-Key": "k"})
        assert resp.status_code == 404
        mock_mq.publish.assert_not_awaited()

    async def test_refresh_marks_failed_on_publish_error(self, client, mock_db, mock_mq):
        mock_mq.publish = AsyncMock(side_effect=RuntimeError("redis down"))
        resp = await client.post("/v1/documents/doc-1/refresh", headers={"X-API-Key": "k"})
        assert resp.status_code == 503
        mock_db.mark_document_failed.assert_awaited_once()


# --- verify endpoint ------------------------------------------------------


@pytest.fixture
def read_key() -> APIKeyInfo:
    return APIKeyInfo(
        key_id="r-key",
        user_id="user-1",
        workspace_id="ws-1",
        permissions=["read"],
        rate_limit=100,
        expires_at=None,
        status="active",
    )


@pytest.fixture
def verify_app(read_key):
    application = create_app()
    application.dependency_overrides[get_api_key_info] = lambda: read_key
    application.dependency_overrides[get_read_permission] = lambda: read_key
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
async def verify_client(verify_app):
    transport = ASGITransport(app=verify_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestVerifyEndpoint:
    async def test_verify_strong(self, verify_client):
        resp = await verify_client.post(
            "/v1/verify-claim",
            json={
                "claim": "The capital of France is Paris",
                "evidence": ["Paris is the capital of France."],
            },
            headers={"X-API-Key": "k"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["support_level"] == "strong"
        assert 0.0 <= body["score"] <= 1.0
        assert body["reason"]

    async def test_verify_none_no_evidence(self, verify_client):
        resp = await verify_client.post(
            "/v1/verify-claim",
            json={"claim": "Some claim", "evidence": []},
            headers={"X-API-Key": "k"},
        )
        assert resp.status_code == 200
        assert resp.json()["support_level"] == "none"

    async def test_verify_rejects_empty_claim(self, verify_client):
        resp = await verify_client.post(
            "/v1/verify-claim",
            json={"claim": "", "evidence": ["x"]},
            headers={"X-API-Key": "k"},
        )
        assert resp.status_code == 422
