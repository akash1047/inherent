"""Unit tests for TemporalWorkflowTrigger and get_workflow_trigger factory."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.temporal.trigger as trigger_mod
from src.models.document import DocumentUploadMessage
from src.temporal.trigger import TemporalWorkflowTrigger, get_workflow_trigger


# Override the package-level DB-dependent autouse fixture (tests/conftest.py)
# with a no-op. This module's tests are pure/mocked (no real DatabaseService
# interaction), so they must not skip when PostgreSQL is unavailable -- same
# pattern as tests/test_contracts.py and tests/test_temporal_activities.py.
@pytest.fixture(autouse=True)
def cleanup_test_data():
    """No-op override so this module's tests run without a live database."""
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings():
    """Return a minimal mock Settings object."""
    settings = MagicMock()
    settings.temporal_host = "localhost:7233"
    settings.temporal_namespace = "default"
    settings.temporal_task_queue = "ingestion"
    return settings


def _make_upload_message(**overrides) -> DocumentUploadMessage:
    """Build a minimal valid DocumentUploadMessage, with overrides for the
    ingestion-source fields under test (#187)."""
    base = {
        "event_type": "document.uploaded",
        "document_id": "doc-1",
        "workspace_id": "ws-1",
        "user_id": "user-1",
        "filename": "stored.txt",
        "original_filename": "original.txt",
        "content_type": "text/plain",
        "size_bytes": 10,
        "storage_backend": "local",
        "storage_path": "workspaces/ws-1/stored.txt",
        "timestamp": "2024-01-15T10:30:00Z",
    }
    base.update(overrides)
    return DocumentUploadMessage(**base)


# ---------------------------------------------------------------------------
# _classify_error tests
# ---------------------------------------------------------------------------


class TestClassifyError:
    """Tests for TemporalWorkflowTrigger._classify_error (static method)."""

    def test_extract_keyword_returns_extraction_failed(self):
        result = TemporalWorkflowTrigger._classify_error("Failed to extract text from PDF")
        assert result == "extraction_failed"

    def test_storage_keyword_returns_storage_failed(self):
        result = TemporalWorkflowTrigger._classify_error("Storage write failed")
        assert result == "storage_failed"

    def test_timeout_keyword_returns_timeout(self):
        result = TemporalWorkflowTrigger._classify_error("Connection timeout")
        assert result == "timeout"

    def test_timed_out_keyword_returns_timeout(self):
        result = TemporalWorkflowTrigger._classify_error("Request timed out after 30s")
        assert result == "timeout"

    def test_validation_keyword_returns_validation_failed(self):
        result = TemporalWorkflowTrigger._classify_error("Validation error in schema")
        assert result == "validation_failed"

    def test_invalid_keyword_returns_validation_failed(self):
        result = TemporalWorkflowTrigger._classify_error("Invalid document format")
        assert result == "validation_failed"

    def test_fetch_keyword_returns_fetch_failed(self):
        result = TemporalWorkflowTrigger._classify_error("Could not fetch document from bucket")
        assert result == "fetch_failed"

    def test_unknown_string_returns_unknown(self):
        result = TemporalWorkflowTrigger._classify_error("Something completely unexpected happened")
        assert result == "unknown"


# ---------------------------------------------------------------------------
# Initial state tests
# ---------------------------------------------------------------------------


class TestInitialState:
    """Tests for TemporalWorkflowTrigger constructor and initial internal state."""

    def test_client_is_none_initially(self):
        settings = _make_settings()
        trigger = TemporalWorkflowTrigger(settings)
        assert trigger._client is None

    def test_initialized_is_false_initially(self):
        settings = _make_settings()
        trigger = TemporalWorkflowTrigger(settings)
        assert trigger._initialized is False


# ---------------------------------------------------------------------------
# shutdown() tests
# ---------------------------------------------------------------------------


class TestShutdown:
    """Tests for TemporalWorkflowTrigger.shutdown()."""

    def test_shutdown_resets_client_and_initialized_flag(self):
        settings = _make_settings()
        trigger = TemporalWorkflowTrigger(settings)

        # Simulate an initialized state
        trigger._client = MagicMock()
        trigger._initialized = True

        trigger.shutdown()

        assert trigger._client is None
        assert trigger._initialized is False


# ---------------------------------------------------------------------------
# get_workflow_trigger singleton tests
# ---------------------------------------------------------------------------


class TestGetWorkflowTriggerSingleton:
    """Tests for the get_workflow_trigger() module-level singleton factory."""

    def setup_method(self):
        """Reset the global singleton before each test."""
        trigger_mod._workflow_trigger = None

    def teardown_method(self):
        """Clean up the global singleton after each test."""
        trigger_mod._workflow_trigger = None

    def test_returns_same_instance_on_repeated_calls(self):
        settings = _make_settings()

        first = get_workflow_trigger(settings)
        second = get_workflow_trigger(settings)

        assert first is second

    def test_returns_temporal_workflow_trigger_instance(self):
        settings = _make_settings()
        result = get_workflow_trigger(settings)
        assert isinstance(result, TemporalWorkflowTrigger)

    def test_backfills_db_service_on_existing_singleton(self):
        """A later caller providing db_service must backfill it onto the
        already-created singleton (worker mode creates the trigger before the
        api layer wires db_service), so dead-letter recording is not a no-op (#6)."""
        settings = _make_settings()
        first = get_workflow_trigger(settings)  # created without db_service
        assert first._db_service is None

        db = MagicMock()
        second = get_workflow_trigger(settings, db_service=db)

        assert second is first
        assert first._db_service is db


# ---------------------------------------------------------------------------
# async poison-message handling tests (Fix #6)
# ---------------------------------------------------------------------------


class TestTriggerFailurePathRobustness:
    """A non-validation error before upload_message is bound must not raise an
    UnboundLocalError in the failure path that masks the real error (#39)."""

    @pytest.mark.asyncio
    async def test_non_validation_error_does_not_mask_with_nameerror(self):
        trigger = TemporalWorkflowTrigger(_make_settings())
        trigger._initialized = True
        trigger._mq_service = AsyncMock()

        with patch("src.temporal.trigger.DocumentUploadMessage", side_effect=TypeError("boom")):
            result = await trigger.trigger_workflow({"document_id": "d1"})

        # Clean failure result carrying the real error, not an UnboundLocalError.
        assert result.success is False
        assert "boom" in (result.error or "")
        # No completion publish attempted with an unbound message.
        trigger._mq_service.publish_completion.assert_not_awaited()


class TestAsyncTriggerPoisonHandling:
    """``trigger_workflow_async`` must dead-letter a malformed (poison) message
    and return normally so the MQ consumer ACKs it — never re-raise into an
    infinite redelivery loop. Transient Temporal errors must still raise so the
    message is redelivered (#6)."""

    def _ready_trigger(self, db_service):
        settings = _make_settings()
        trigger = TemporalWorkflowTrigger(settings, db_service=db_service)
        trigger._initialized = True
        trigger._client = MagicMock()
        trigger._client.start_workflow = AsyncMock(return_value=MagicMock())
        return trigger

    @pytest.mark.asyncio
    async def test_poison_message_is_dead_lettered_and_not_raised(self):
        db = MagicMock()
        db.add_dead_letter_job = AsyncMock()
        trigger = self._ready_trigger(db)

        # Malformed message: missing required fields -> validation error.
        result = await trigger.trigger_workflow_async({"document_id": "d1"})

        # Returns normally (no raise) so the consumer ACKs and stops redelivering.
        assert result == ""
        db.add_dead_letter_job.assert_awaited_once()
        # No workflow is started for a poison message.
        trigger._client.start_workflow.assert_not_called()

    @pytest.mark.asyncio
    async def test_transient_temporal_error_still_raises(self, sample_upload_message):
        db = MagicMock()
        db.add_dead_letter_job = AsyncMock()
        trigger = self._ready_trigger(db)
        # Valid message, but Temporal is transiently unavailable.
        trigger._client.start_workflow = AsyncMock(side_effect=RuntimeError("temporal unavailable"))

        with pytest.raises(RuntimeError, match="temporal unavailable"):
            await trigger.trigger_workflow_async(sample_upload_message)

        # Transient errors must NOT be dead-lettered — the message must redeliver.
        db.add_dead_letter_job.assert_not_awaited()


# ---------------------------------------------------------------------------
# Ingestion-source Temporal memo tests (#187)
# ---------------------------------------------------------------------------


class TestBuildSourceMemo:
    """Unit tests for TemporalWorkflowTrigger._build_source_memo (#187).

    Memo needs no namespace search-attribute registration and surfaces
    directly in the Temporal UI workflow summary panel.
    """

    def test_connector_sourced_message_includes_connection_and_sync_id(self):
        upload_message = _make_upload_message(
            source="connector:notion", connection_id="conn_123", sync_id="sync_456"
        )

        memo = TemporalWorkflowTrigger._build_source_memo(upload_message)

        assert memo == {
            "source": "connector:notion",
            "connection_id": "conn_123",
            "sync_id": "sync_456",
        }

    def test_source_only_message_omits_absent_connector_ids(self):
        upload_message = _make_upload_message(source="public-api")

        memo = TemporalWorkflowTrigger._build_source_memo(upload_message)

        assert memo == {"source": "public-api"}
        assert "connection_id" not in memo
        assert "sync_id" not in memo

    def test_legacy_message_without_source_defaults_to_unknown(self):
        # Legacy/in-flight messages produced before #187 have no source field
        # at all, which Pydantic leaves as None.
        upload_message = _make_upload_message()
        assert upload_message.source is None

        memo = TemporalWorkflowTrigger._build_source_memo(upload_message)

        assert memo == {"source": "unknown"}

    def test_oversized_source_is_truncated_not_passed_through(self):
        """A pathologically large `source` (no max_length on the wire contract,
        see inh_contracts.events.DocumentUploadMessage) must not reach Temporal
        unbounded -- start_workflow would reject an oversized memo, and that
        rejection is NOT classified as poison by trigger_workflow_async (only
        PydanticValidationError is), so it would redeliver forever (#141
        adversarial pass). Truncating client-side avoids that failure mode."""
        huge_source = "connector:" + ("x" * 10_000)
        upload_message = _make_upload_message(source=huge_source)

        memo = TemporalWorkflowTrigger._build_source_memo(upload_message)

        assert len(memo["source"]) == TemporalWorkflowTrigger._MEMO_VALUE_MAX_LEN
        assert memo["source"] == huge_source[: TemporalWorkflowTrigger._MEMO_VALUE_MAX_LEN]

    def test_oversized_connector_ids_are_truncated(self):
        upload_message = _make_upload_message(
            source="connector:notion",
            connection_id="c" * 5_000,
            sync_id="s" * 5_000,
        )

        memo = TemporalWorkflowTrigger._build_source_memo(upload_message)

        assert len(memo["connection_id"]) == TemporalWorkflowTrigger._MEMO_VALUE_MAX_LEN
        assert len(memo["sync_id"]) == TemporalWorkflowTrigger._MEMO_VALUE_MAX_LEN


class TestTriggerWorkflowAsyncMemoIntegration:
    """Verify trigger_workflow_async threads the memo through to the actual
    Temporal client.start_workflow call (not just the helper in isolation)."""

    def _ready_trigger(self) -> TemporalWorkflowTrigger:
        trigger = TemporalWorkflowTrigger(_make_settings())
        trigger._initialized = True
        trigger._client = MagicMock()
        trigger._client.start_workflow = AsyncMock(return_value=MagicMock())
        return trigger

    @pytest.mark.asyncio
    async def test_connector_sourced_message_passes_full_memo(
        self, sample_upload_message_connector_sourced
    ):
        trigger = self._ready_trigger()

        await trigger.trigger_workflow_async(sample_upload_message_connector_sourced)

        _, kwargs = trigger._client.start_workflow.call_args
        assert kwargs["memo"] == {
            "source": "connector:notion",
            "connection_id": "conn_123",
            "sync_id": "sync_456",
        }

    @pytest.mark.asyncio
    async def test_public_api_message_passes_source_only_memo(
        self, sample_upload_message_public_api
    ):
        trigger = self._ready_trigger()

        await trigger.trigger_workflow_async(sample_upload_message_public_api)

        _, kwargs = trigger._client.start_workflow.call_args
        assert kwargs["memo"] == {"source": "public-api"}

    @pytest.mark.asyncio
    async def test_legacy_message_without_source_passes_unknown_memo(self, sample_upload_message):
        # sample_upload_message has no "source" key at all — simulates an
        # in-flight message produced before #187 shipped on the intg-svc side.
        trigger = self._ready_trigger()

        await trigger.trigger_workflow_async(sample_upload_message)

        _, kwargs = trigger._client.start_workflow.call_args
        assert kwargs["memo"] == {"source": "unknown"}
