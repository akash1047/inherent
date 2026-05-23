"""Tests for WriteAuditLogWorkflow using Temporal's time-skipping test env."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from src.temporal.activities.audit_activities import validate_audit_event
from src.temporal.workflows.audit_log import WriteAuditLogWorkflow

TASK_QUEUE = "audit-test-queue"


def _valid_event() -> dict[str, Any]:
    return {
        "audit_id": "test-audit-001",
        "workspace_id": "ws-1",
        "user_id": "usr-1",
        "api_key_id": "key-1",
        "source": "api_key",
        "query_type": "semantic",
        "query_text": "test query",
        "query_filters": {},
        "result_count": 3,
        "result_snippets": [],
        "llm_response": None,
        "response_time_ms": 42.0,
        "request_id": "req-1",
        "query_timestamp": datetime.now(UTC).isoformat(),
    }


# Mock activities that don't need real infra
@activity.defn(name="write_audit_log_to_mongo")
async def mock_write_audit_log_to_mongo(event: dict[str, Any]) -> bool:
    """Mock write that always succeeds."""
    return True


@activity.defn(name="write_audit_log_to_mongo")
async def mock_write_audit_log_duplicate(event: dict[str, Any]) -> bool:
    """Mock write that returns duplicate."""
    return False


@activity.defn(name="emit_audit_metric")
async def mock_emit_audit_metric(event: dict[str, Any]) -> None:
    """Mock metric emit that does nothing."""
    pass


@pytest.mark.asyncio
async def test_valid_event_writes_successfully():
    """A valid event should go through all 3 activities and return status 'written'."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[WriteAuditLogWorkflow],
            activities=[
                validate_audit_event,
                mock_write_audit_log_to_mongo,
                mock_emit_audit_metric,
            ],
        ):
            result = await env.client.execute_workflow(
                WriteAuditLogWorkflow.run,
                _valid_event(),
                id="audit-test-valid",
                task_queue=TASK_QUEUE,
            )

            assert result["status"] == "written"
            assert result["audit_id"] == "test-audit-001"


@pytest.mark.asyncio
async def test_invalid_event_fails():
    """An event missing required fields should raise WorkflowFailureError."""
    bad_event = _valid_event()
    del bad_event["workspace_id"]

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[WriteAuditLogWorkflow],
            activities=[
                validate_audit_event,
                mock_write_audit_log_to_mongo,
                mock_emit_audit_metric,
            ],
        ):
            with pytest.raises(WorkflowFailureError):
                await env.client.execute_workflow(
                    WriteAuditLogWorkflow.run,
                    bad_event,
                    id="audit-test-invalid",
                    task_queue=TASK_QUEUE,
                )


@pytest.mark.asyncio
async def test_duplicate_returns_duplicate_status():
    """When upsert returns False (duplicate), status should be 'duplicate'."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[WriteAuditLogWorkflow],
            activities=[
                validate_audit_event,
                mock_write_audit_log_duplicate,
                mock_emit_audit_metric,
            ],
        ):
            result = await env.client.execute_workflow(
                WriteAuditLogWorkflow.run,
                _valid_event(),
                id="audit-test-dup",
                task_queue=TASK_QUEUE,
            )

            assert result["status"] == "duplicate"
