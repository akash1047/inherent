"""Unit tests for TemporalWorkflowTrigger and get_workflow_trigger factory."""

from unittest.mock import MagicMock

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
