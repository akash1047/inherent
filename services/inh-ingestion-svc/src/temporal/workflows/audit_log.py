"""WriteAuditLogWorkflow — durable pipeline for persisting audit events.

Runs three activities in sequence:
1. ``validate_audit_event`` — non-retriable (1 attempt, 5s timeout)
2. ``write_audit_log_to_mongo`` — retriable (5 attempts, exp backoff 1s→30s, 15s timeout)
3. ``emit_audit_metric`` — best-effort (2 attempts, 5s timeout)
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from src.temporal.activities.audit_activities import (
        emit_audit_metric,
        validate_audit_event,
        write_audit_log_to_mongo,
    )


@workflow.defn
class WriteAuditLogWorkflow:
    """Durable workflow for writing a single audit log entry."""

    @workflow.run
    async def run(self, event: dict[str, Any]) -> dict[str, Any]:
        """Execute the validate → write → metric pipeline."""

        # 1. Validate (non-retriable)
        await workflow.execute_activity(
            validate_audit_event,
            event,
            start_to_close_timeout=timedelta(seconds=5),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        # 2. Write to MongoDB (retriable)
        written = await workflow.execute_activity(
            write_audit_log_to_mongo,
            event,
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=RetryPolicy(
                maximum_attempts=5,
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=30),
                backoff_coefficient=2.0,
            ),
        )

        # 3. Emit metric (best-effort)
        try:
            await workflow.execute_activity(
                emit_audit_metric,
                event,
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception as exc:
            workflow.logger.warning("emit_audit_metric failed: %s", exc)

        audit_id = event.get("audit_id", "unknown")
        return {
            "status": "written" if written else "duplicate",
            "audit_id": audit_id,
        }
