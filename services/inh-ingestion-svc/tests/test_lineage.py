"""Tests for data lineage tracking (DE-S020)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.temporal.lineage import track_event


@pytest.fixture(autouse=True)
async def cleanup_test_data():
    yield


@pytest.fixture()
def db_service():
    yield None


class TestTrackEventContextManager:
    """Tests for the track_event async context manager."""

    async def test_records_success_event(self):
        mock_db = MagicMock()
        mock_db.record_ingestion_event = AsyncMock()

        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            async with track_event("wf-1", "doc-1", "ws-1", "test_step"):
                pass

        mock_db.record_ingestion_event.assert_awaited_once()
        call_args = mock_db.record_ingestion_event.call_args
        assert call_args[0][0] == "wf-1"
        assert call_args[0][1] == "doc-1"
        assert call_args[0][3] == "test_step"
        assert call_args[0][4] == "succeeded"
        assert call_args[0][5] >= 0

    async def test_records_failure_and_reraises(self):
        mock_db = MagicMock()
        mock_db.record_ingestion_event = AsyncMock()

        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            try:
                async with track_event("wf-1", "doc-1", "ws-1", "fail_step"):
                    raise ValueError("broke")
            except ValueError:
                pass

        call_args = mock_db.record_ingestion_event.call_args
        assert call_args[0][4] == "failed"
        assert call_args[0][6]["error"] == "broke"

    async def test_exception_reraises_after_recording(self):
        import pytest

        mock_db = MagicMock()
        mock_db.record_ingestion_event = AsyncMock()

        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            with pytest.raises(RuntimeError, match="original"):
                async with track_event("wf-1", "doc-1", "ws-1", "s"):
                    raise RuntimeError("original")

    async def test_db_failure_does_not_break_activity(self):
        mock_db = MagicMock()
        mock_db.record_ingestion_event = AsyncMock(side_effect=Exception("db down"))

        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            async with track_event("wf-1", "doc-1", "ws-1", "s"):
                pass  # should not raise

    async def test_db_failure_on_error_still_reraises_original(self):
        import pytest

        mock_db = MagicMock()
        mock_db.record_ingestion_event = AsyncMock(side_effect=Exception("db down"))

        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            with pytest.raises(ValueError, match="original"):
                async with track_event("wf-1", "doc-1", "ws-1", "s"):
                    raise ValueError("original")

    async def test_workspace_id_can_be_none(self):
        mock_db = MagicMock()
        mock_db.record_ingestion_event = AsyncMock()

        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            async with track_event("wf-1", "doc-1", None, "step"):
                pass

        call_args = mock_db.record_ingestion_event.call_args
        assert call_args[0][2] is None
