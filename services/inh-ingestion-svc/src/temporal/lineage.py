"""Lightweight data lineage tracker for ingestion pipeline steps.

Provides a context manager that records start/success/failure of each
pipeline step into the ingestion_events table. Lineage tracking is
non-blocking: if the DB write fails, a warning is logged but the
activity is not interrupted.
"""

import time
from contextlib import asynccontextmanager

import structlog

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def track_event(
    workflow_run_id: str,
    document_id: str,
    workspace_id: str | None,
    event_type: str,
):
    """Context manager that records start/success/failure of a pipeline step.

    Usage::

        async with track_event(workflow_run_id, document_id, workspace_id, "tenant_ready"):
            # ... activity logic ...

    On success, records a 'succeeded' event with duration_ms.
    On failure, records a 'failed' event with the error message in metadata,
    then re-raises the original exception.

    If the DB write itself fails, the error is logged as a warning and
    the activity continues unaffected.

    Args:
        workflow_run_id: The Temporal workflow run ID
        document_id: The document being processed
        workspace_id: The workspace (may be None for some activities)
        event_type: Pipeline step name (e.g. 'tenant_ready', 'document_fetched')
    """
    from src.temporal.shared_services import get_db_service

    start = time.monotonic()
    try:
        yield
        duration_ms = int((time.monotonic() - start) * 1000)
        try:
            db = get_db_service()
            await db.record_ingestion_event(
                workflow_run_id,
                document_id,
                workspace_id,
                event_type,
                "succeeded",
                duration_ms,
            )
        except Exception as rec_err:
            logger.warning(
                "Failed to record lineage event (succeeded)",
                event_type=event_type,
                document_id=document_id,
                error=str(rec_err),
            )
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        try:
            db = get_db_service()
            await db.record_ingestion_event(
                workflow_run_id,
                document_id,
                workspace_id,
                event_type,
                "failed",
                duration_ms,
                {"error": str(e)},
            )
        except Exception as rec_err:
            logger.warning(
                "Failed to record lineage event (failed)",
                event_type=event_type,
                document_id=document_id,
                error=str(rec_err),
            )
        raise
