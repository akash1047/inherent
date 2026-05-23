"""Temporal workflow trigger for bridging MQ events to Temporal workflows.

This module bridges the message queue (Valkey/Redis, Pub/Sub, etc.) and
Temporal workflow execution. It receives document upload notifications
via MQ and starts corresponding Temporal workflows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError as PydanticValidationError
from temporalio.client import Client

from src.config.settings import Settings
from src.models.document import DocumentUploadMessage, ProcessingResult
from src.temporal.models import DocumentIngestionInput, WorkflowResult
from src.temporal.workflows import DocumentIngestionWorkflow

if TYPE_CHECKING:
    from src.services.database import DatabaseService
    from src.services.mq import BaseMQService

logger = structlog.get_logger(__name__)


class TemporalWorkflowTrigger:
    """Triggers Temporal workflows from MQ messages.

    This class acts as a bridge between the message queue and
    the Temporal workflow system.
    """

    def __init__(
        self,
        settings: Settings,
        mq_service: BaseMQService | None = None,
        db_service: DatabaseService | None = None,
    ):
        """Initialize workflow trigger.

        Args:
            settings: Application settings with Temporal configuration
            mq_service: Optional MQ service for publishing completion notifications
            db_service: Optional database service for dead-letter recording
        """
        self.settings = settings
        self._mq_service = mq_service
        self._db_service = db_service
        self._client: Client | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize Temporal client connection."""
        if self._initialized:
            return

        logger.info(
            "Connecting to Temporal server for workflow triggering",
            host=self.settings.temporal_host,
            namespace=self.settings.temporal_namespace,
        )

        self._client = await Client.connect(
            self.settings.temporal_host,
            namespace=self.settings.temporal_namespace,
        )

        self._initialized = True
        logger.info("Temporal client connected for workflow triggering")

    @staticmethod
    def _classify_error(error_message: str) -> str:
        """Classify an error message into an error type for dead-letter tracking.

        Args:
            error_message: The error string from the workflow

        Returns:
            A short error type classification
        """
        lower = error_message.lower()
        if "extract" in lower or "parse" in lower:
            return "extraction_failed"
        if "storage" in lower or "postgresql" in lower or "weaviate" in lower:
            return "storage_failed"
        if "timeout" in lower or "timed out" in lower:
            return "timeout"
        if "validation" in lower or "invalid" in lower:
            return "validation_failed"
        if "fetch" in lower or "not found" in lower or "download" in lower:
            return "fetch_failed"
        return "unknown"

    async def _record_dead_letter(
        self,
        document_id: str,
        workspace_id: str,
        user_id: str,
        workflow_run_id: str | None,
        original_message: dict,
        error_message: str,
    ) -> None:
        """Record a failed job in the dead-letter table (non-blocking).

        If the DB insert fails, logs a warning but never raises.
        """
        if not self._db_service:
            logger.debug(
                "No db_service configured, skipping dead-letter recording",
                document_id=document_id,
            )
            return

        try:
            error_type = self._classify_error(error_message)
            await self._db_service.add_dead_letter_job(
                document_id=document_id,
                workspace_id=workspace_id,
                user_id=user_id,
                workflow_run_id=workflow_run_id,
                original_message=original_message,
                error_message=error_message,
                error_type=error_type,
            )
        except Exception as e:
            logger.warning(
                "Failed to record dead-letter job (non-blocking)",
                document_id=document_id,
                error=str(e),
            )

    async def trigger_workflow(self, message: dict) -> ProcessingResult:
        """Trigger a document ingestion workflow from an MQ message.

        This method:
        1. Validates the incoming message
        2. Converts it to workflow input
        3. Starts a Temporal workflow
        4. Waits for completion and publishes result to MQ

        Args:
            message: Raw message dictionary from MQ

        Returns:
            ProcessingResult with success status
        """
        if not self._initialized:
            await self.initialize()

        document_id = message.get("document_id", "unknown")

        try:
            # Validate message schema
            try:
                upload_message = DocumentUploadMessage(**message)
                document_id = upload_message.document_id
            except PydanticValidationError as e:
                logger.error(
                    "Message validation failed",
                    error=str(e),
                    message=message,
                    validation_errors=e.errors(),
                )
                return ProcessingResult(
                    document_id=document_id,
                    success=False,
                    error=f"Invalid message format: {e}",
                )

            logger.info(
                "Triggering Temporal workflow",
                document_id=upload_message.document_id,
                workspace_id=upload_message.workspace_id,
                user_id=upload_message.user_id,
                filename=upload_message.original_filename,
            )

            # Create workflow input
            workflow_input = DocumentIngestionInput(
                document_id=upload_message.document_id,
                workspace_id=upload_message.workspace_id,
                user_id=upload_message.user_id,
                filename=upload_message.filename,
                original_filename=upload_message.original_filename,
                content_type=upload_message.content_type,
                size_bytes=upload_message.size_bytes,
                storage_backend=upload_message.storage_backend,
                storage_path=upload_message.storage_path,
                storage_bucket=upload_message.storage_bucket,
                storage_url=upload_message.storage_url,
                timestamp=upload_message.timestamp,
            )

            # Start the workflow
            if self._client is None:
                raise RuntimeError("Temporal client not initialized")

            workflow_id = f"ingest-{upload_message.document_id}"

            handle = await self._client.start_workflow(
                DocumentIngestionWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=self.settings.temporal_task_queue,
            )

            logger.info(
                "Temporal workflow started",
                workflow_id=workflow_id,
                document_id=upload_message.document_id,
                task_queue=self.settings.temporal_task_queue,
            )

            # Wait for workflow completion
            result: WorkflowResult = await handle.result()

            logger.info(
                "Temporal workflow completed",
                workflow_id=workflow_id,
                document_id=result.document_id,
                success=result.success,
                chunks_created=result.chunks_created,
                processing_time_ms=result.processing_time_ms,
            )

            processing_result = ProcessingResult(
                document_id=result.document_id,
                success=result.success,
                chunks_created=result.chunks_created,
                error=result.error,
                processing_time_ms=result.processing_time_ms,
            )

            # Publish completion notification
            if self._mq_service:
                try:
                    await self._mq_service.publish_completion(processing_result, upload_message)
                except Exception as e:
                    logger.error(
                        "Failed to publish completion", document_id=document_id, error=str(e)
                    )

            return processing_result

        except Exception as e:
            logger.error(
                "Failed to trigger workflow",
                document_id=document_id,
                error=str(e),
                exc_info=True,
            )

            failure_result = ProcessingResult(
                document_id=document_id,
                success=False,
                error=str(e),
            )

            # Publish completion notification for failure
            if self._mq_service:
                try:
                    await self._mq_service.publish_completion(failure_result, upload_message)
                except Exception as pub_e:
                    logger.error(
                        "Failed to publish completion", document_id=document_id, error=str(pub_e)
                    )

            return failure_result

    async def trigger_workflow_async(self, message: dict) -> str:
        """Trigger a workflow without waiting for completion.

        This method starts a workflow and returns immediately with the
        workflow ID. Useful for fire-and-forget scenarios.

        Args:
            message: Raw message dictionary from Pub/Sub

        Returns:
            Workflow ID for tracking
        """
        if not self._initialized:
            await self.initialize()

        # Validate message
        upload_message = DocumentUploadMessage(**message)

        # Create workflow input
        workflow_input = DocumentIngestionInput(
            document_id=upload_message.document_id,
            workspace_id=upload_message.workspace_id,
            user_id=upload_message.user_id,
            filename=upload_message.filename,
            original_filename=upload_message.original_filename,
            content_type=upload_message.content_type,
            size_bytes=upload_message.size_bytes,
            storage_backend=upload_message.storage_backend,
            storage_path=upload_message.storage_path,
            storage_bucket=upload_message.storage_bucket,
            storage_url=upload_message.storage_url,
            timestamp=upload_message.timestamp,
        )

        if self._client is None:
            raise RuntimeError("Temporal client not initialized")

        workflow_id = f"ingest-{upload_message.document_id}"

        await self._client.start_workflow(
            DocumentIngestionWorkflow.run,
            workflow_input,
            id=workflow_id,
            task_queue=self.settings.temporal_task_queue,
        )

        logger.info(
            "Temporal workflow started (async)",
            workflow_id=workflow_id,
            document_id=upload_message.document_id,
        )

        return workflow_id

    async def get_workflow_status(self, workflow_id: str) -> dict | None:
        """Get the status of a running workflow.

        Args:
            workflow_id: The workflow ID to query

        Returns:
            Status dict with step, progress, and chunks_created
        """
        if self._client is None:
            await self.initialize()

        try:
            if self._client is None:
                raise RuntimeError("Temporal client not initialized")

            handle = self._client.get_workflow_handle(workflow_id)
            status = await handle.query(DocumentIngestionWorkflow.get_status)
            return status
        except Exception as e:
            logger.error(
                "Failed to get workflow status",
                workflow_id=workflow_id,
                error=str(e),
            )
            return None

    def shutdown(self) -> None:
        """Shutdown the trigger (cleanup resources)."""
        # Temporal client doesn't need explicit cleanup
        self._client = None
        self._initialized = False
        logger.info("Temporal workflow trigger shut down")


# Global trigger instance
_workflow_trigger: TemporalWorkflowTrigger | None = None


def get_workflow_trigger(
    settings: Settings, mq_service: BaseMQService | None = None
) -> TemporalWorkflowTrigger:
    """Get or create the global workflow trigger.

    Args:
        settings: Application settings
        mq_service: Optional MQ service for publishing completion notifications

    Returns:
        TemporalWorkflowTrigger instance
    """
    global _workflow_trigger
    if _workflow_trigger is None:
        _workflow_trigger = TemporalWorkflowTrigger(settings, mq_service=mq_service)
    return _workflow_trigger
