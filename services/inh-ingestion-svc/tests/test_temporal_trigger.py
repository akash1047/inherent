"""Unit tests for TemporalWorkflowTrigger and get_workflow_trigger factory."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.temporal.trigger as trigger_mod
from src.temporal.trigger import TemporalWorkflowTrigger, get_workflow_trigger

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
# Workflow-id-collision supersession tests (#110)
# ---------------------------------------------------------------------------
#
# Both start_workflow call sites use a *fixed* id (f"ingest-{document_id}").
# Before this fix, a re-index enqueued while the prior run for that
# document_id was still open raised WorkflowAlreadyStartedError with the
# default id_conflict_policy (UNSPECIFIED). On the async (MQ) path that
# exception propagates out of trigger_workflow_async, so the message is never
# ACKed; RedisMQService only retries it once XAUTOCLAIM reclaims it (idle >=
# 30s, see src/services/mq/redis_mq.py:46) — and only after a *new* message
# also arrives, since the reclaim call is skipped whenever a poll iteration
# reads no fresh entries (redis_mq.py:216-233). Every retry collides with the
# same still-open run and fails again, so the caller effectively waits out
# however long the stale run takes to close on its own — the ~10min observed
# in CI run 29222060795, not a fixed timeout constant.
#
# Fix: pass id_conflict_policy=TERMINATE_EXISTING so Temporal supersedes the
# stale run with the fresh one at start time instead of raising. This is the
# right call for an AI-agent caller that will retry: re-index/refresh always
# means "the current content should win", so terminating a stale run in
# favor of a fresh one is correct, not a race to avoid — and it turns the
# ~10 minute stall into a normal, fast run.


class TestWorkflowIdConflictPolicySupersedesStaleRun:
    """A re-index/refresh under an open prior run must supersede it, not
    collide and stall (#110)."""

    def _ready_trigger(self):
        """Trigger with a mocked Temporal client whose start_workflow succeeds
        and whose handle resolves to a completed WorkflowResult."""
        settings = _make_settings()
        trigger = TemporalWorkflowTrigger(settings)
        trigger._initialized = True
        trigger._client = MagicMock()

        handle = MagicMock()
        handle.result = AsyncMock(
            return_value=MagicMock(
                document_id="test_doc_12345",
                success=True,
                chunks_created=1,
                error=None,
                processing_time_ms=1,
            )
        )
        trigger._client.start_workflow = AsyncMock(return_value=handle)
        return trigger

    @pytest.mark.asyncio
    async def test_async_trigger_passes_terminate_existing_conflict_policy(
        self, sample_upload_message
    ):
        """trigger_workflow_async (the MQ-driven re-index/refresh path) must
        ask Temporal to terminate-and-supersede a same-id run in flight,
        instead of relying on the default (raise) behavior."""
        from temporalio.common import WorkflowIDConflictPolicy

        trigger = self._ready_trigger()

        await trigger.trigger_workflow_async(sample_upload_message)

        _, kwargs = trigger._client.start_workflow.call_args
        assert kwargs.get("id_conflict_policy") == WorkflowIDConflictPolicy.TERMINATE_EXISTING

    @pytest.mark.asyncio
    async def test_sync_trigger_passes_terminate_existing_conflict_policy(
        self, sample_upload_message
    ):
        """trigger_workflow (the blocking twin) carries the same fixed-id
        exposure and must use the same supersession policy."""
        from temporalio.common import WorkflowIDConflictPolicy

        trigger = self._ready_trigger()

        await trigger.trigger_workflow(sample_upload_message)

        _, kwargs = trigger._client.start_workflow.call_args
        assert kwargs.get("id_conflict_policy") == WorkflowIDConflictPolicy.TERMINATE_EXISTING

    @pytest.mark.asyncio
    async def test_async_trigger_supersedes_a_still_open_prior_run(
        self, sample_upload_message
    ):
        """Behavioral regression guard for the actual stall (#110).

        Fakes the real Temporal server contract: a start_workflow call for an
        id with an open run raises WorkflowAlreadyStartedError *unless* the
        caller opted into conflict resolution via
        id_conflict_policy=TERMINATE_EXISTING, in which case the server
        terminates the stale run and starts the new one instead of raising.
        This fails against the pre-fix code (no id_conflict_policy kwarg ->
        the fake raises, same as the real server) and passes once the fix
        sets it -- unlike a mock that always succeeds, this actually exercises
        the collision branch that caused the MQ redelivery stall."""
        from temporalio.common import WorkflowIDConflictPolicy
        from temporalio.exceptions import WorkflowAlreadyStartedError

        trigger = self._ready_trigger()

        async def fake_start_workflow(*args, **kwargs):
            if kwargs.get("id_conflict_policy") != WorkflowIDConflictPolicy.TERMINATE_EXISTING:
                raise WorkflowAlreadyStartedError(kwargs["id"], "test-run-id")
            return MagicMock()

        trigger._client.start_workflow = AsyncMock(side_effect=fake_start_workflow)

        # Must resolve fast with the new run's id, not raise and leave the
        # MQ message unacked for redelivery.
        workflow_id = await trigger.trigger_workflow_async(sample_upload_message)

        assert workflow_id == "ingest-test_doc_12345"
