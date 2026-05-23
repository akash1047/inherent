"""Unit tests for StagingService.

Tests mock the DatabaseService / session layer so no real PostgreSQL is needed.
All 8 tests cover: write_text, read_text, write_chunks, read_chunks, cleanup,
and cleanup_stale.
"""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from src.services.staging import StagingService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(database_url: str = "postgresql://test:test@localhost/test") -> MagicMock:
    """Return a minimal Settings mock."""
    settings = MagicMock()
    settings.database_url = database_url
    return settings


def _make_service_with_mock_db() -> tuple[StagingService, MagicMock, MagicMock]:
    """Build a StagingService whose internal _db is a fully mocked DatabaseService.

    Returns:
        (service, mock_db, mock_session) — service under test, mock _db, mock session.
    """
    settings = _make_settings()

    with patch("src.services.staging.DatabaseService") as MockDatabaseService:  # noqa: N806
        mock_db = MagicMock()
        MockDatabaseService.return_value = mock_db

        service = StagingService(settings)

    mock_session = MagicMock()

    @contextmanager
    def _session_ctx():
        yield mock_session

    mock_db.get_session.side_effect = _session_ctx

    return service, mock_db, mock_session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWriteText:
    """write_text should execute an UPSERT with the correct parameters."""

    def test_write_text_calls_execute_with_correct_params(self):
        service, mock_db, mock_session = _make_service_with_mock_db()

        service.write_text("wf-001", "Hello, world!")

        # get_session must have been called once
        mock_db.get_session.assert_called_once()

        # session.execute must have been called once
        mock_session.execute.assert_called_once()
        call_args = mock_session.execute.call_args

        # Second positional arg is the params dict
        params = call_args[0][1]
        assert params["wf_id"] == "wf-001"
        assert params["data"] == "Hello, world!"

        # commit must have been called
        mock_session.commit.assert_called_once()


class TestReadText:
    """read_text should return stored text or raise RuntimeError."""

    def test_read_text_returns_stored_value(self):
        service, mock_db, mock_session = _make_service_with_mock_db()

        # fetchone() returns a row-like tuple
        mock_session.execute.return_value.fetchone.return_value = ("extracted text",)

        result = service.read_text("wf-001")

        assert result == "extracted text"

    def test_read_text_raises_when_row_is_none(self):
        service, mock_db, mock_session = _make_service_with_mock_db()

        mock_session.execute.return_value.fetchone.return_value = None

        with pytest.raises(RuntimeError, match="No extracted text found"):
            service.read_text("wf-missing")

    def test_read_text_raises_when_text_data_is_null(self):
        service, mock_db, mock_session = _make_service_with_mock_db()

        # Row exists but text_data column is NULL
        mock_session.execute.return_value.fetchone.return_value = (None,)

        with pytest.raises(RuntimeError, match="null extracted text"):
            service.read_text("wf-null-text")


class TestWriteChunks:
    """write_chunks should serialize list to JSON and UPSERT."""

    def test_write_chunks_stores_json(self):
        service, mock_db, mock_session = _make_service_with_mock_db()

        chunks = [{"id": "c1", "text": "chunk one"}, {"id": "c2", "text": "chunk two"}]
        service.write_chunks("wf-002", chunks)

        mock_db.get_session.assert_called_once()
        mock_session.execute.assert_called_once()

        call_args = mock_session.execute.call_args
        params = call_args[0][1]

        assert params["wf_id"] == "wf-002"
        # data should be the JSON-serialised form of chunks
        assert json.loads(params["data"]) == chunks

        mock_session.commit.assert_called_once()


class TestReadChunks:
    """read_chunks should deserialize JSON and raise RuntimeError when missing."""

    def test_read_chunks_returns_deserialized_list(self):
        service, mock_db, mock_session = _make_service_with_mock_db()

        chunks = [{"id": "c1", "text": "chunk one"}]

        # Simulate JSONB already deserialized by the driver (returns a Python list)
        mock_session.execute.return_value.fetchone.return_value = (chunks,)

        result = service.read_chunks("wf-002")

        assert result == chunks

    def test_read_chunks_deserializes_json_string(self):
        service, mock_db, mock_session = _make_service_with_mock_db()

        chunks = [{"id": "c1", "text": "chunk one"}]

        # Simulate the column returned as a raw JSON string
        mock_session.execute.return_value.fetchone.return_value = (json.dumps(chunks),)

        result = service.read_chunks("wf-002")

        assert result == chunks

    def test_read_chunks_raises_when_missing(self):
        service, mock_db, mock_session = _make_service_with_mock_db()

        mock_session.execute.return_value.fetchone.return_value = None

        with pytest.raises(RuntimeError, match="No chunks found"):
            service.read_chunks("wf-missing")


class TestCleanup:
    """cleanup should issue a DELETE for the given workflow_run_id."""

    def test_cleanup_calls_delete_with_workflow_run_id(self):
        service, mock_db, mock_session = _make_service_with_mock_db()

        service.cleanup("wf-003")

        mock_db.get_session.assert_called_once()
        mock_session.execute.assert_called_once()

        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["wf_id"] == "wf-003"

        mock_session.commit.assert_called_once()


class TestCleanupStale:
    """cleanup_stale should DELETE old rows and return the deleted count."""

    def test_cleanup_stale_returns_count_of_deleted_rows(self):
        service, mock_db, mock_session = _make_service_with_mock_db()

        # result.rowcount = 5 means 5 rows were deleted
        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_session.execute.return_value = mock_result

        deleted = service.cleanup_stale(max_age_hours=1)

        assert deleted == 5
        mock_db.get_session.assert_called_once()
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_cleanup_stale_returns_zero_when_rowcount_none(self):
        service, mock_db, mock_session = _make_service_with_mock_db()

        mock_result = MagicMock()
        mock_result.rowcount = None
        mock_session.execute.return_value = mock_result

        deleted = service.cleanup_stale()

        assert deleted == 0
