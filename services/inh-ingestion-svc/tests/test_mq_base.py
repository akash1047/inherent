"""Unit tests for BaseMQService.publish_completion via MemoryMQService.

Tests cover:
1. publishes success notification with correct fields
2. publishes failure notification with error
3. publish_completion does not raise on error (catches internally)
4. backend property returns "memory"
5. is_connected returns False before connect
6. is_connected returns True after connect
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.settings import Settings
from src.services.mq.memory_mq import MemoryMQService

COMPLETION_TOPIC = "core.document.processed.v1"


def make_mock_settings(**overrides: object) -> MagicMock:
    """Return a MagicMock that quacks like Settings."""
    settings = MagicMock(spec=Settings)
    settings.mq_completion_topic = COMPLETION_TOPIC
    for k, v in overrides.items():
        setattr(settings, k, v)
    return settings


def make_result(
    *,
    document_id: str = "doc-123",
    success: bool = True,
    chunks_created: int = 5,
    processing_time_ms: int = 200,
    error: str | None = None,
) -> MagicMock:
    """Build a MagicMock shaped like ProcessingResult."""
    result = MagicMock()
    result.document_id = document_id
    result.success = success
    result.chunks_created = chunks_created
    result.processing_time_ms = processing_time_ms
    result.error = error
    return result


def make_upload_message(
    *,
    workspace_id: str = "ws-456",
    user_id: str = "user-789",
    original_filename: str = "report.pdf",
    content_type: str = "application/pdf",
    size_bytes: int = 1024,
    storage_backend: str = "s3",
    storage_path: str = "workspaces/ws-456/report.pdf",
    storage_bucket: str | None = "inherent-documents",
    storage_url: str | None = "https://example.com/report.pdf",
    filename: str = "report.pdf",
) -> MagicMock:
    """Build a MagicMock shaped like DocumentUploadMessage."""
    msg = MagicMock()
    msg.workspace_id = workspace_id
    msg.user_id = user_id
    msg.original_filename = original_filename
    msg.content_type = content_type
    msg.size_bytes = size_bytes
    msg.storage_backend = storage_backend
    msg.storage_path = storage_path
    msg.storage_bucket = storage_bucket
    msg.storage_url = storage_url
    msg.filename = filename
    return msg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_completion_success_fields() -> None:
    """publish_completion publishes a success notification with correct fields."""
    settings = make_mock_settings()
    svc = MemoryMQService(settings)
    await svc.connect()

    result = make_result(success=True, chunks_created=7, processing_time_ms=350)
    upload = make_upload_message()

    await svc.publish_completion(result, upload)

    history = svc.get_history(COMPLETION_TOPIC)
    assert len(history) == 1

    msg = history[0]
    assert msg["event_type"] == "document.processed"
    assert msg["document_id"] == "doc-123"
    assert msg["workspace_id"] == "ws-456"
    assert msg["user_id"] == "user-789"
    assert msg["original_filename"] == "report.pdf"
    assert msg["success"] is True
    assert msg["status"] == "ready"
    assert msg["chunks_created"] == 7
    assert msg["processing_time_ms"] == 350
    assert msg["error"] is None
    assert msg["content_type"] == "application/pdf"
    assert msg["size_bytes"] == 1024
    assert msg["storage_backend"] == "s3"
    assert msg["storage_bucket"] == "inherent-documents"
    assert msg["storage_url"] == "https://example.com/report.pdf"
    assert "timestamp" in msg


@pytest.mark.asyncio
async def test_publish_completion_failure_fields() -> None:
    """publish_completion publishes a failure notification with error info."""
    settings = make_mock_settings()
    svc = MemoryMQService(settings)
    await svc.connect()

    result = make_result(success=False, chunks_created=0, error="Parser crashed")
    upload = make_upload_message()

    await svc.publish_completion(result, upload)

    history = svc.get_history(COMPLETION_TOPIC)
    assert len(history) == 1

    msg = history[0]
    assert msg["event_type"] == "document.failed"
    assert msg["success"] is False
    assert msg["status"] == "failed"
    assert msg["error"] == "Parser crashed"
    assert msg["chunks_created"] == 0


@pytest.mark.asyncio
async def test_publish_completion_does_not_raise_on_publish_error() -> None:
    """publish_completion swallows exceptions from the underlying publish call."""
    settings = make_mock_settings()
    svc = MemoryMQService(settings)
    await svc.connect()

    # Patch publish to raise so we exercise the exception-swallowing branch
    svc.publish = AsyncMock(side_effect=RuntimeError("broker unavailable"))

    result = make_result()
    upload = make_upload_message()

    # Must not raise
    await svc.publish_completion(result, upload)


@pytest.mark.asyncio
async def test_publish_completion_skips_when_no_topic() -> None:
    """publish_completion does nothing (and does not raise) when topic is falsy."""
    settings = make_mock_settings(mq_completion_topic=None)
    svc = MemoryMQService(settings)
    await svc.connect()

    result = make_result()
    upload = make_upload_message()

    await svc.publish_completion(result, upload)

    # Nothing published
    assert svc.get_history(COMPLETION_TOPIC) == []


def test_backend_property_returns_memory() -> None:
    """MemoryMQService.backend == 'memory'."""
    settings = make_mock_settings()
    svc = MemoryMQService(settings)
    assert svc.backend == "memory"


@pytest.mark.asyncio
async def test_is_connected_false_before_connect() -> None:
    """is_connected() returns False before connect() is called."""
    settings = make_mock_settings()
    svc = MemoryMQService(settings)
    assert svc.is_connected() is False


@pytest.mark.asyncio
async def test_is_connected_true_after_connect() -> None:
    """is_connected() returns True after connect() is called."""
    settings = make_mock_settings()
    svc = MemoryMQService(settings)
    await svc.connect()
    assert svc.is_connected() is True
