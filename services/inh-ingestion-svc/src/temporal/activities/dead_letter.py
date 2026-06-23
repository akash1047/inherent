"""Activity for recording a terminally-failed ingestion job in the
dead-letter table (#8).

With non-blocking (async) workflow starts (#18), the MQ consumer no longer
observes the workflow's execution outcome, so terminal failures are recorded
from the WORKFLOW's failure path instead of the trigger. This activity writes
a ``dead_letter_jobs`` row (via DatabaseService.add_dead_letter_job) including
the reconstructed original MQ message, so the dead-letter retry API can
re-publish it faithfully.

This is a best-effort observability/recovery signal: a failure to record a
dead-letter row must NEVER mask the original workflow error. The caller in the
workflow wraps the activity call so a failure here is logged and swallowed.
"""

import structlog
from temporalio import activity

from src.temporal.models import RecordDeadLetterInput

logger = structlog.get_logger(__name__)


@activity.defn
async def record_dead_letter(input: RecordDeadLetterInput) -> bool:
    """Insert a dead-letter row for a terminally-failed ingestion job.

    Delegates to ``DatabaseService.add_dead_letter_job`` using the shared,
    already-connected database pool (same pool used by the other ingestion
    activities). Returns True on success, False if recording was skipped or
    failed (it never raises, so it cannot mask the workflow's real error).

    Args:
        input: document/workspace/user IDs, workflow run ID, the original MQ
            message dict, the error message, and the classified error type.

    Returns:
        True if a dead-letter row was written, False otherwise.
    """
    from src.temporal.shared_services import get_db_service

    db_service = get_db_service()

    job_id = await db_service.add_dead_letter_job(
        document_id=input.document_id,
        workspace_id=input.workspace_id,
        user_id=input.user_id,
        workflow_run_id=input.workflow_run_id,
        original_message=input.original_message,
        error_message=input.error_message,
        error_type=input.error_type,
    )

    logger.info(
        "Recorded dead-letter job",
        document_id=input.document_id,
        workspace_id=input.workspace_id,
        error_type=input.error_type,
        dead_letter_job_id=job_id,
    )

    return True
