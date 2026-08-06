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
            tc._app = app
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

    def test_wait_true_terminated_by_newer_request_returns_409(self, client: TestClient):
        """(#110 blocker 4) A concurrent MQ refresh for the SAME document_id
        can terminate this run out from under a wait=true caller (Temporal
        workflow ids are global, not scoped to how the run was started --
        trigger_workflow_async's supersede_running=True default terminates
        any same-id run, including one a synchronous /ingest?wait=true caller
        is currently blocked on). Pre-#110 this could never happen (nothing
        superseded a running workflow); post-#110 handle.result() raises
        WorkflowFailureError(cause=TerminatedError) and the endpoint must
        report a clear 409, not crash with an unhandled 500."""
        from temporalio.client import WorkflowFailureError
        from temporalio.exceptions import TerminatedError

        client._mock_handle.result = AsyncMock(
            side_effect=WorkflowFailureError(
                cause=TerminatedError("Terminated by a newer workflow execution")
            )
        )

        resp = client.post(
            "/ingest?wait=true",
            json=_INGEST_PAYLOAD,
            headers={"X-API-Key": VALID_API_KEY},
        )
        assert resp.status_code == 409
        data = resp.json()
        assert data["status"] == "superseded_by_newer_request"
        assert data["document_id"] == "doc_001"

    def test_wait_true_other_workflow_failure_returns_500_with_body(self, client: TestClient):
        """A WorkflowFailureError whose cause is NOT a termination (e.g. an
        unexpected cancellation) is not the #110 supersession case -- it must
        still surface as a real error with a body, not silently swallowed or
        misreported as a supersession."""
        from temporalio.client import WorkflowFailureError
        from temporalio.exceptions import CancelledError

        client._mock_handle.result = AsyncMock(
            side_effect=WorkflowFailureError(cause=CancelledError("Workflow cancelled"))
        )

        resp = client.post(
            "/ingest?wait=true",
            json=_INGEST_PAYLOAD,
            headers={"X-API-Key": VALID_API_KEY},
        )
        assert resp.status_code == 500
        assert "Workflow cancelled" in resp.json()["detail"]

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


# ---------------------------------------------------------------------------
# Dead-letter retry supersede-policy tests (#110 blocker 3)
# ---------------------------------------------------------------------------

# A DocumentUploadMessage-shaped payload (all required fields present) so
# trigger_workflow_async's schema validation passes and the call actually
# reaches start_workflow instead of being dead-lettered as a poison message
# before ever getting there.
_DEAD_LETTER_ORIGINAL_MESSAGE = {
    "event_type": "document.uploaded",
    "document_id": "doc_001",
    "workspace_id": "ws_001",
    "user_id": "user_001",
    "filename": "1234567890-abc-document.pdf",
    "original_filename": "document.pdf",
    "content_type": "application/pdf",
    "size_bytes": 1024,
    "storage_backend": "local",
    "storage_path": "workspaces/ws_001/document.pdf",
    "timestamp": "2026-01-01T00:00:00Z",
}


class TestDeadLetterRetrySupersedePolicy:
    """POST /dead-letter/{id}/retry replays a POSSIBLY STALE payload -- the
    one that failed and got dead-lettered, maybe long ago. It must NOT use
    the default supersede-a-running-workflow policy trigger_workflow_async
    uses for fresh MQ upload/refresh events (#110): if a healthy, newer run
    for the same document_id is meanwhile in flight (the user re-uploaded
    corrected content after the original failure), superseding it would
    silently terminate that newer run and overwrite it with the old payload.
    """

    def test_retry_calls_trigger_with_supersede_running_false(self, client: TestClient):
        fake_trigger = AsyncMock()
        fake_trigger.trigger_workflow_async = AsyncMock(return_value="ingest-doc_001")
        # app.state.trigger is a real TemporalWorkflowTrigger wired at
        # startup (see create_app's lifespan) -- swap it for a mock so this
        # test asserts purely on how the ROUTE calls trigger_workflow_async,
        # not on Temporal/DB plumbing.
        client._app.state.trigger = fake_trigger

        with patch("src.temporal.shared_services.get_db_service") as mock_get_db:
            mock_db = MagicMock()
            mock_db.get_dead_letter_job = AsyncMock(
                return_value={
                    "id": 1,
                    "status": "pending",
                    "original_message": _DEAD_LETTER_ORIGINAL_MESSAGE,
                }
            )
            mock_db.increment_dead_letter_retry = AsyncMock()
            mock_db.update_dead_letter_status = AsyncMock()
            mock_get_db.return_value = mock_db

            resp = client.post("/dead-letter/1/retry", headers={"X-API-Key": VALID_API_KEY})

        assert resp.status_code == 200
        fake_trigger.trigger_workflow_async.assert_awaited_once()
        _, kwargs = fake_trigger.trigger_workflow_async.await_args
        assert kwargs.get("supersede_running") is False

    def test_retry_collision_with_healthy_run_resets_to_pending_and_500s(
        self, client: TestClient
    ):
        """End-to-end (real TemporalWorkflowTrigger, not a further-mocked
        fake) proof of the protection: supersede_running=False makes a
        same-id collision raise WorkflowAlreadyStartedError (the SDK default
        id_conflict_policy) instead of terminating the healthy run -- the
        route's existing except resets the job to 'pending' and returns 500.
        Also asserts the Temporal client call itself did NOT ask for
        TERMINATE_EXISTING, closing the loop from app.py's kwarg down to the
        actual start_workflow call."""
        from temporalio.exceptions import WorkflowAlreadyStartedError

        # Use the REAL trigger wired at startup, with only its Temporal
        # client swapped for a mock -- this exercises trigger.py's actual
        # supersede_running=False branch, not a re-mocked double of it.
        # get_workflow_trigger caches ONE instance per process, so restore
        # it in `finally` -- otherwise a mocked _client would leak into
        # whatever test runs next in this process.
        real_trigger = client._app.state.trigger
        try:
            real_trigger._initialized = True
            real_trigger._client = AsyncMock()
            real_trigger._client.start_workflow = AsyncMock(
                side_effect=WorkflowAlreadyStartedError("ingest-doc_001", "healthy-run")
            )

            with patch("src.temporal.shared_services.get_db_service") as mock_get_db:
                mock_db = MagicMock()
                mock_db.get_dead_letter_job = AsyncMock(
                    return_value={
                        "id": 1,
                        "status": "pending",
                        "original_message": _DEAD_LETTER_ORIGINAL_MESSAGE,
                    }
                )
                mock_db.increment_dead_letter_retry = AsyncMock()
                mock_db.update_dead_letter_status = AsyncMock()
                mock_get_db.return_value = mock_db

                resp = client.post("/dead-letter/1/retry", headers={"X-API-Key": VALID_API_KEY})

            assert resp.status_code == 500
            mock_db.update_dead_letter_status.assert_awaited_once_with(1, "pending")

            # The actual Temporal call must NOT have asked to supersede.
            from temporalio.common import WorkflowIDConflictPolicy

            _, kwargs = real_trigger._client.start_workflow.call_args
            assert kwargs.get("id_conflict_policy") != WorkflowIDConflictPolicy.TERMINATE_EXISTING
        finally:
            real_trigger._client = None
            real_trigger._initialized = False
