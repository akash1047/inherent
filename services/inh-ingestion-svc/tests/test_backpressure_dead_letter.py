"""Unit tests for #8 (dead-letter recording) and #18 (backpressure) wiring.

These are offline/mocked. The full runtime behaviour (real Temporal async
start, redis consumer-group ACK timing, worker concurrency) can only be
exercised against the live stack / CI — see the PR notes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.settings import Settings
from src.services.mq.redis_mq import RedisMQService
from src.temporal.activities.dead_letter import record_dead_letter
from src.temporal.models import DocumentIngestionInput, RecordDeadLetterInput
from src.temporal.workflows.document_ingestion import DocumentIngestionWorkflow


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """No-op override of the package-level DB-dependent autouse fixture."""
    yield


# --------------------------------------------------------------------------- #
# #8 — dead-letter recording
# --------------------------------------------------------------------------- #


async def test_record_dead_letter_activity_writes_row(monkeypatch):
    db = MagicMock()
    db.add_dead_letter_job = AsyncMock(return_value=123)
    monkeypatch.setattr("src.temporal.shared_services.get_db_service", lambda: db, raising=True)

    out = await record_dead_letter(
        RecordDeadLetterInput(
            document_id="doc-1",
            workspace_id="ws-1",
            user_id="user-1",
            workflow_run_id="run-1",
            original_message={"event_type": "document.uploaded", "document_id": "doc-1"},
            error_message="Weaviate storage failed: boom",
            error_type="storage_failed",
        )
    )

    assert out is True
    db.add_dead_letter_job.assert_awaited_once()
    kwargs = db.add_dead_letter_job.await_args.kwargs
    assert kwargs["document_id"] == "doc-1"
    assert kwargs["error_type"] == "storage_failed"
    assert kwargs["original_message"]["document_id"] == "doc-1"


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Failed to extract text from PDF", "extraction_failed"),
        ("Weaviate storage failed", "storage_failed"),
        # storage keywords take precedence over "timeout" by design
        ("PostgreSQL connection timed out", "storage_failed"),
        ("activity timed out", "timeout"),
        ("validation error: invalid field", "validation_failed"),
        ("could not fetch document, not found", "fetch_failed"),
    ],
)
def test_workflow_classify_error(message, expected):
    assert DocumentIngestionWorkflow._classify_error(message) == expected


def test_reconstruct_original_message_matches_upload_contract():
    inp = DocumentIngestionInput(
        document_id="doc-1",
        workspace_id="ws-1",
        user_id="user-1",
        filename="stored.pdf",
        original_filename="report.pdf",
        content_type="application/pdf",
        size_bytes=10,
        storage_backend="s3",
        storage_path="ws-1/doc-1/report.pdf",
        storage_bucket="bucket",
        storage_url="http://s3/report.pdf",
        timestamp="2026-06-21T00:00:00+00:00",
    )
    msg = DocumentIngestionWorkflow._reconstruct_original_message(inp)
    # Must carry the keys the consumer (DocumentUploadMessage) requires so the
    # retry API can re-publish it faithfully.
    for key in (
        "event_type",
        "document_id",
        "workspace_id",
        "user_id",
        "filename",
        "original_filename",
        "content_type",
        "size_bytes",
        "storage_backend",
        "storage_path",
        "timestamp",
    ):
        assert key in msg
    assert msg["event_type"] == "document.uploaded"
    assert msg["document_id"] == "doc-1"


# --------------------------------------------------------------------------- #
# #18 — backpressure / bounded handler
# --------------------------------------------------------------------------- #


def _service() -> RedisMQService:
    settings = MagicMock(spec=Settings)
    settings.redis_url = "redis://localhost:6379"
    settings.max_workers = 4
    settings.resolved_mq_max_concurrent = 4
    return RedisMQService(settings)


async def test_bounded_handler_acks_on_success():
    service = _service()
    service._redis = MagicMock()
    service._redis.xack = AsyncMock(return_value=1)
    handler = AsyncMock(return_value=None)

    await service._handle_message_bounded(
        "core.document.uploaded.v1",
        "default",
        "1-0",
        {"payload": "{}"},
        handler,
    )

    handler.assert_awaited_once()
    service._redis.xack.assert_awaited_once_with("core.document.uploaded.v1", "default", "1-0")


def test_concurrency_limit_falls_back_to_max_workers():
    settings = MagicMock(spec=Settings)
    settings.redis_url = "redis://localhost:6379"
    # No resolved_mq_max_concurrent attribute -> fall back to max_workers.
    del settings.resolved_mq_max_concurrent
    settings.max_workers = 7
    service = RedisMQService(settings)
    assert service._concurrency_limit == 7
