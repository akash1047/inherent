"""Tests for the standalone HTTP API (auth, routes, edge cases)."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient  # noqa: I001

# ---------------------------------------------------------------------------
# Override conftest autouse fixtures — API tests don't need PostgreSQL
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def cleanup_test_data():
    """Override global autouse cleanup — no DB needed for API tests."""
    yield


@pytest.fixture()
def db_service():
    """Override — API tests don't use PostgreSQL."""
    yield None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_API_KEY = "test-secret-key-abc123"

_INGEST_PAYLOAD = {
    "document_id": "doc_001",
    "workspace_id": "ws_001",
    "user_id": "user_001",
    "filename": "1234567890-abc-document.pdf",
    "original_filename": "document.pdf",
    "content_type": "application/pdf",
    "size_bytes": 1024,
    "storage_backend": "local",
    "storage_path": "workspaces/ws_001/document.pdf",
}


@dataclass
class _FakeWorkflowResult:
    document_id: str = "doc_001"
    success: bool = True
    chunks_created: int = 5
    processing_time_ms: int = 250
    error: str | None = None


def _make_mock_settings(**overrides):
    """Return a MagicMock that behaves like Settings for the API layer."""
    defaults = {
        "ingestion_api_key": VALID_API_KEY,
        "api_host": "127.0.0.1",
        "api_port": 8000,
        "temporal_host": "localhost:7233",
        "temporal_namespace": "default",
        "temporal_task_queue": "document-ingestion",
        "log_level": "INFO",
    }
    defaults.update(overrides)
    s = MagicMock()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


@pytest.fixture()
def client():
    """Yield a TestClient whose Temporal layer is fully mocked.

    The TemporalWorkerManager is patched so no real Temporal connection
    is attempted.  A mock Temporal client is attached to app.state.
    """
    mock_settings = _make_mock_settings()

    mock_temporal_client = AsyncMock()
    mock_handle = AsyncMock()
    mock_handle.result = AsyncMock(return_value=_FakeWorkflowResult())
    mock_handle.query = AsyncMock(
        return_value={
            "step": "chunking_text",
            "progress": 55,
            "chunks_created": 3,
        }
    )
    mock_temporal_client.start_workflow = AsyncMock(return_value=mock_handle)
    mock_temporal_client.get_workflow_handle = MagicMock(return_value=mock_handle)

    with (
        patch("src.api.app.TemporalWorkerManager") as mock_manager_cls,
        patch("src.api.auth.get_settings", return_value=mock_settings),
    ):
        instance = mock_manager_cls.return_value
        instance.start = AsyncMock()
        instance.stop = AsyncMock()
        instance.get_client = AsyncMock(return_value=mock_temporal_client)
        instance.is_running = True

        from src.api.app import create_app

        app = create_app(mock_settings)

        with TestClient(app) as tc:
            # Expose internals for test assertions
            tc._mock_temporal_client = mock_temporal_client
            tc._mock_handle = mock_handle
            yield tc


# ---------------------------------------------------------------------------
# Auth Tests
# ---------------------------------------------------------------------------


class TestAuth:
    """API key authentication."""

    def test_missing_key_returns_401(self, client: TestClient):
        resp = client.post("/ingest", json=_INGEST_PAYLOAD)
        assert resp.status_code == 401

    def test_wrong_key_returns_403(self, client: TestClient):
        resp = client.post(
            "/ingest",
            json=_INGEST_PAYLOAD,
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 403

    def test_correct_key_passes(self, client: TestClient):
        resp = client.post(
            "/ingest",
            json=_INGEST_PAYLOAD,
            headers={"X-API-Key": VALID_API_KEY},
        )
        assert resp.status_code in (200, 202)

    def test_status_endpoint_requires_key(self, client: TestClient):
        resp = client.get("/ingest/doc_001/status")
        assert resp.status_code == 401

    def test_health_does_not_require_key(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Health Tests
# ---------------------------------------------------------------------------


class TestHealth:
    def test_healthy_when_worker_running(self, client: TestClient):
        resp = client.get("/health")
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["temporal_worker"] is True
        assert "version" in data


# ---------------------------------------------------------------------------
# Ingest Trigger Tests
# ---------------------------------------------------------------------------


class TestIngestTrigger:
    """POST /ingest endpoint."""

    def test_returns_202_with_workflow_id(self, client: TestClient):
        resp = client.post(
            "/ingest",
            json=_INGEST_PAYLOAD,
            headers={"X-API-Key": VALID_API_KEY},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["workflow_id"] == "ingest-doc_001"
        assert data["document_id"] == "doc_001"
        assert data["status"] == "started"

    def test_wait_true_returns_200_with_result(self, client: TestClient):
        resp = client.post(
            "/ingest?wait=true",
            json=_INGEST_PAYLOAD,
            headers={"X-API-Key": VALID_API_KEY},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["chunks_created"] == 5

    def test_already_running_returns_409(self, client: TestClient):
        from temporalio.exceptions import WorkflowAlreadyStartedError

        client._mock_temporal_client.start_workflow = AsyncMock(
            side_effect=WorkflowAlreadyStartedError("ingest-doc_001", "test")
        )

        resp = client.post(
            "/ingest",
            json=_INGEST_PAYLOAD,
            headers={"X-API-Key": VALID_API_KEY},
        )
        assert resp.status_code == 409
        assert resp.json()["status"] == "already_running"

    def test_rejects_invalid_payload(self, client: TestClient):
        resp = client.post(
            "/ingest",
            json={"document_id": "x"},  # missing required fields
            headers={"X-API-Key": VALID_API_KEY},
        )
        assert resp.status_code == 422

    def test_rejects_zero_size_bytes(self, client: TestClient):
        payload = {**_INGEST_PAYLOAD, "size_bytes": 0}
        resp = client.post(
            "/ingest",
            json=payload,
            headers={"X-API-Key": VALID_API_KEY},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Status Tests
# ---------------------------------------------------------------------------


class TestIngestStatus:
    """GET /ingest/{document_id}/status endpoint."""

    def test_returns_workflow_status(self, client: TestClient):
        resp = client.get(
            "/ingest/doc_001/status",
            headers={"X-API-Key": VALID_API_KEY},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_id"] == "ingest-doc_001"
        assert data["step"] == "chunking_text"
        assert data["progress"] == 55

    def test_unknown_workflow_returns_404(self, client: TestClient):
        from temporalio.service import RPCError

        mock_handle = AsyncMock()
        mock_handle.query = AsyncMock(
            side_effect=RPCError(
                message="workflow not found",
                status=MagicMock(code=5),  # NOT_FOUND
                raw_grpc_status=MagicMock(),
            )
        )
        client._mock_temporal_client.get_workflow_handle = MagicMock(return_value=mock_handle)

        resp = client.get(
            "/ingest/nonexistent/status",
            headers={"X-API-Key": VALID_API_KEY},
        )
        assert resp.status_code == 404
