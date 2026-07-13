"""Unit tests for the compensating mark-failed retry helper (#99).

The helper is the single allowed way to run a compensating
``mark_document_failed`` write: it retries transient failures with backoff
and, when retries are exhausted, makes the orphaned-'pending' row loud
(CRITICAL log + Prometheus counter) instead of swallowing it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.services.compensation import mark_document_failed_with_retry
from src.services.metrics import document_compensation_exhausted_total

pytestmark = pytest.mark.asyncio


def _exhausted_count(operation: str) -> float:
    """Current value of the exhaustion counter for one operation label."""
    return document_compensation_exhausted_total.labels(operation=operation)._value.get()


class TestMarkDocumentFailedWithRetry:
    async def test_first_attempt_success_marks_once(self):
        db = AsyncMock()
        db.mark_document_failed = AsyncMock(return_value=None)

        ok = await mark_document_failed_with_retry(
            db, "doc-1", "ws-1", "enqueue failed", operation="upload_enqueue"
        )

        assert ok is True
        db.mark_document_failed.assert_awaited_once_with("doc-1", "ws-1", "enqueue failed")

    async def test_transient_failure_is_retried_then_succeeds(self):
        db = AsyncMock()
        db.mark_document_failed = AsyncMock(side_effect=[RuntimeError("db blip"), None])

        ok = await mark_document_failed_with_retry(
            db,
            "doc-1",
            "ws-1",
            "enqueue failed",
            operation="upload_enqueue",
            backoff_seconds=0,
        )

        assert ok is True
        assert db.mark_document_failed.await_count == 2

    async def test_exhaustion_returns_false_and_bumps_metric(self):
        db = AsyncMock()
        db.mark_document_failed = AsyncMock(side_effect=RuntimeError("db degraded"))
        before = _exhausted_count("upload_enqueue")

        ok = await mark_document_failed_with_retry(
            db,
            "doc-1",
            "ws-1",
            "enqueue failed",
            operation="upload_enqueue",
            attempts=3,
            backoff_seconds=0,
        )

        assert ok is False
        # Every configured attempt is used before giving up.
        assert db.mark_document_failed.await_count == 3
        # Exhaustion is observable: operators can alert on this counter to
        # find rows orphaned as 'pending' (#99).
        assert _exhausted_count("upload_enqueue") == before + 1

    async def test_success_does_not_bump_exhaustion_metric(self):
        db = AsyncMock()
        db.mark_document_failed = AsyncMock(side_effect=[RuntimeError("db blip"), None])
        before = _exhausted_count("refresh_enqueue")

        ok = await mark_document_failed_with_retry(
            db,
            "doc-1",
            "ws-1",
            "refresh enqueue failed",
            operation="refresh_enqueue",
            backoff_seconds=0,
        )

        assert ok is True
        assert _exhausted_count("refresh_enqueue") == before
