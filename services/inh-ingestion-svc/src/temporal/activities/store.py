"""Storage activities for persisting documents to PostgreSQL and Weaviate.

Reads chunks from staging (instead of receiving them via gRPC).
Uses shared connection pools from shared_services.
"""

import time

import structlog
from temporalio import activity

from src.models.document import DocumentChunk, DocumentUploadMessage
from src.temporal.models import StoreDocumentInput, StoreDocumentOutput

logger = structlog.get_logger(__name__)


@activity.defn
async def store_in_postgresql(input: StoreDocumentInput) -> StoreDocumentOutput:
    """Store processed document and chunks in PostgreSQL.

    This activity:
    1. Reads chunks from staging
    2. Stores document metadata in processed_documents table
    3. Stores all chunks in document_chunks table with FK relationship
    4. Updates document status to 'processed'

    Args:
        input: Contains document metadata and workflow_run_id to read chunks from staging

    Returns:
        StoreDocumentOutput with success status and chunks stored count
    """
    from src.temporal.shared_services import get_db_service, get_staging_service

    staging = get_staging_service()
    chunk_dicts = staging.read_chunks(input.workflow_run_id)

    db_service = get_db_service()
    start = time.monotonic()

    try:
        # Convert chunk dicts to DocumentChunk objects
        chunks = [
            DocumentChunk(
                document_id=c["document_id"],
                content=c["content"],
                chunk_index=c["chunk_index"],
                start_char=c["start_char"],
                end_char=c["end_char"],
            )
            for c in chunk_dicts
        ]

        # Create a DocumentUploadMessage-like object for the database service
        message = DocumentUploadMessage(
            event_type="document.uploaded",
            document_id=input.document_id,
            workspace_id=input.workspace_id,
            user_id=input.user_id,
            filename=input.filename,
            original_filename=input.original_filename,
            content_type=input.content_type,
            size_bytes=input.size_bytes,
            storage_backend=input.storage_backend,  # type: ignore[arg-type]
            storage_path=input.storage_path,
            storage_bucket=None,
            storage_url=None,
            timestamp="",  # Not needed for storage
        )

        await db_service.store_processed_document(
            message=message,
            chunks=chunks,
            text_length=input.text_length,
            processing_time_ms=input.processing_time_ms,
            tenant_id=input.tenant_id,
        )

        duration_ms = int((time.monotonic() - start) * 1000)

        logger.info(
            "Stored document in PostgreSQL",
            document_id=input.document_id,
            chunks_stored=len(chunks),
            tenant_id=input.tenant_id,
        )

        # Record lineage event on success
        try:
            await db_service.record_ingestion_event(
                workflow_run_id=input.workflow_run_id,
                document_id=input.document_id,
                workspace_id=input.workspace_id,
                event_type="stored_postgresql",
                status="succeeded",
                duration_ms=duration_ms,
            )
        except Exception as rec_err:
            logger.warning(
                "Failed to record lineage event",
                event_type="stored_postgresql",
                error=str(rec_err),
            )

        return StoreDocumentOutput(
            success=True,
            chunks_stored=len(chunks),
            error=None,
        )

    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)

        logger.error(
            "Failed to store document in PostgreSQL",
            document_id=input.document_id,
            error=str(e),
            exc_info=True,
        )

        # Record lineage event on failure
        try:
            await db_service.record_ingestion_event(
                workflow_run_id=input.workflow_run_id,
                document_id=input.document_id,
                workspace_id=input.workspace_id,
                event_type="stored_postgresql",
                status="failed",
                duration_ms=duration_ms,
                metadata={"error": str(e)},
            )
        except Exception as rec_err:
            logger.warning(
                "Failed to record lineage event",
                event_type="stored_postgresql",
                error=str(rec_err),
            )

        return StoreDocumentOutput(
            success=False,
            chunks_stored=0,
            error=str(e),
        )


@activity.defn
async def store_in_weaviate(input: StoreDocumentInput) -> StoreDocumentOutput:
    """Store document chunks in Weaviate for semantic search.

    This activity:
    1. Reads chunks from staging
    2. Ensures workspace collection exists
    3. Ensures user tenant exists within collection
    4. Stores all chunks with multi-tenant isolation

    Args:
        input: Contains document metadata and workflow_run_id to read chunks from staging

    Returns:
        StoreDocumentOutput with success status and chunks stored count
    """
    from src.temporal.shared_services import (
        get_db_service,
        get_staging_service,
        get_weaviate_service,
    )

    staging = get_staging_service()
    chunk_dicts = staging.read_chunks(input.workflow_run_id)

    weaviate_service = get_weaviate_service()
    start = time.monotonic()

    try:
        if weaviate_service is None or not weaviate_service.is_connected():
            logger.warning("Weaviate not connected, skipping storage")

            # Record lineage event for skipped weaviate
            duration_ms = int((time.monotonic() - start) * 1000)
            try:
                db_service = get_db_service()
                await db_service.record_ingestion_event(
                    workflow_run_id=input.workflow_run_id,
                    document_id=input.document_id,
                    workspace_id=input.workspace_id,
                    event_type="stored_weaviate",
                    status="failed",
                    duration_ms=duration_ms,
                    metadata={"error": "Weaviate not connected"},
                )
            except Exception as rec_err:
                logger.warning(
                    "Failed to record lineage event",
                    event_type="stored_weaviate",
                    error=str(rec_err),
                )

            return StoreDocumentOutput(
                success=False,
                chunks_stored=0,
                error="Weaviate not connected",
            )

        # Convert chunk dicts to DocumentChunk objects
        chunks = [
            DocumentChunk(
                document_id=c["document_id"],
                content=c["content"],
                chunk_index=c["chunk_index"],
                start_char=c["start_char"],
                end_char=c["end_char"],
            )
            for c in chunk_dicts
        ]

        await weaviate_service.store_chunks_with_tenant(
            chunks=chunks,
            document_id=input.document_id,
            workspace_id=input.workspace_id,
            user_id=input.user_id,
            original_filename=input.original_filename,
            content_type=input.content_type,
        )

        duration_ms = int((time.monotonic() - start) * 1000)

        logger.info(
            "Stored document in Weaviate",
            document_id=input.document_id,
            workspace_id=input.workspace_id,
            user_id=input.user_id,
            chunks_stored=len(chunks),
        )

        # Record lineage event on success
        try:
            db_service = get_db_service()
            await db_service.record_ingestion_event(
                workflow_run_id=input.workflow_run_id,
                document_id=input.document_id,
                workspace_id=input.workspace_id,
                event_type="stored_weaviate",
                status="succeeded",
                duration_ms=duration_ms,
            )
        except Exception as rec_err:
            logger.warning(
                "Failed to record lineage event",
                event_type="stored_weaviate",
                error=str(rec_err),
            )

        return StoreDocumentOutput(
            success=True,
            chunks_stored=len(chunks),
            error=None,
        )

    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)

        logger.error(
            "Failed to store document in Weaviate",
            document_id=input.document_id,
            error=str(e),
            exc_info=True,
        )

        # Record lineage event on failure
        try:
            db_service = get_db_service()
            await db_service.record_ingestion_event(
                workflow_run_id=input.workflow_run_id,
                document_id=input.document_id,
                workspace_id=input.workspace_id,
                event_type="stored_weaviate",
                status="failed",
                duration_ms=duration_ms,
                metadata={"error": str(e)},
            )
        except Exception as rec_err:
            logger.warning(
                "Failed to record lineage event",
                event_type="stored_weaviate",
                error=str(rec_err),
            )

        return StoreDocumentOutput(
            success=False,
            chunks_stored=0,
            error=str(e),
        )
