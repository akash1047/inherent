"""Cleanup activity for removing staging data after workflow completion."""

import structlog
from temporalio import activity

from src.temporal.models import CleanupStagingInput

logger = structlog.get_logger(__name__)


@activity.defn
async def cleanup_staging(input: CleanupStagingInput) -> None:
    """Delete all staging rows for a completed workflow run.

    Called as the final step in every workflow (in a finally block)
    to ensure staging data is cleaned up even on failure.

    Args:
        input: Contains workflow_run_id to clean up
    """
    from src.temporal.shared_services import get_staging_service

    staging = get_staging_service()

    try:
        staging.cleanup(input.workflow_run_id)
        logger.info("Cleaned up staging data", workflow_run_id=input.workflow_run_id)
    except Exception as e:
        # Cleanup failure should not fail the workflow
        logger.warning(
            "Failed to clean up staging data",
            workflow_run_id=input.workflow_run_id,
            error=str(e),
        )
