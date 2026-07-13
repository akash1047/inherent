"""Shared document intake pipeline (#87 API parity Task 3).

Extracted from the POST /v1/documents REST handler (src/api/v1/documents.py)
so both the REST route and the ``upload_document`` MCP tool run the exact
same validation + storage + persistence + enqueue logic — a PURE MOVE with no
behaviour change. The REST route now reads the ``UploadFile`` bytes and
delegates everything else here; the MCP tool UTF-8 encodes its text ``content``
argument and calls the same function.
"""

import hashlib
import uuid
from datetime import datetime, timezone

from src.config import settings
from src.config.constants import ALLOWED_MIME_TYPES, MAX_UPLOAD_SIZE_BYTES
from src.core.exceptions import BadRequestError, ServiceUnavailableError
from src.models.document import DocumentUploadResponse
from src.services.compensation import mark_document_failed_with_retry
from src.services.database import DatabaseService
from src.services.mq import get_mq_service
from src.services.storage import get_storage_service
from src.utils import get_logger

logger = get_logger(__name__)


async def intake_document(
    *,
    database: DatabaseService,
    workspace_id: str,
    user_id: str,
    content_bytes: bytes,
    filename: str,
    content_type: str,
) -> DocumentUploadResponse:
    """Validate, dedup, store and enqueue a document for ingestion.

    Mirrors (byte for byte) the former inline body of POST /v1/documents:

    1. Validate ``content_type`` against ``ALLOWED_MIME_TYPES``.
    2. Validate size (non-empty, under ``MAX_UPLOAD_SIZE_BYTES``).
    3. Dedup: reuse an existing ``document_id`` keyed on (workspace,
       content_hash) first, then (workspace, filename) — see #75/#60.
    4. Upload the bytes to S3.
    5. Persist a durable ``pending`` row before enqueueing (#7).
    6. Publish the ``document.uploaded`` MQ message; on publish failure mark
       the row ``failed`` and return a ``status="failed"`` response instead of
       raising (the file IS stored, so this is not a request failure).

    Raises:
        BadRequestError: unsupported content type, empty content, or content
            over ``MAX_UPLOAD_SIZE_BYTES``.
        ServiceUnavailableError: S3 upload or pending-row persistence failed.
    """
    # --- 1. Validate content type -------------------------------------------
    if content_type not in ALLOWED_MIME_TYPES:
        raise BadRequestError(
            detail=(
                f"Unsupported file type '{content_type}'. "
                f"Allowed types: {', '.join(ALLOWED_MIME_TYPES)}"
            ),
        )

    # --- 2. Validate size ----------------------------------------------------
    size_bytes = len(content_bytes)

    if size_bytes == 0:
        raise BadRequestError(detail="Uploaded file is empty.")

    if size_bytes > MAX_UPLOAD_SIZE_BYTES:
        max_mb = MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
        raise BadRequestError(
            detail=f"File size ({size_bytes} bytes) exceeds the {max_mb} MB limit.",
        )

    content_hash = hashlib.sha256(content_bytes).hexdigest()

    # --- 3. Dedup: reuse document_id rather than flood the workspace --------
    # Two re-upload shapes must collapse onto an existing document_id so
    # ingestion reindexes it instead of creating a duplicate document (with
    # duplicate chunks + embeddings) that floods top-k search results (#75):
    #   1. Same CONTENT under any filename — keyed on (workspace, content_hash).
    #      Checked first so a verbatim copy uploaded as ``guide-copy.md``
    #      collapses onto the original ``guide.md`` instead of multiplying it.
    #   2. Same FILENAME with changed content — keyed on (workspace, filename).
    #      Preserves the existing reindex-on-edit behaviour (#60) for a file
    #      whose bytes changed but whose logical identity (name) is unchanged.
    existing_document_id = await database.get_document_id_by_content_hash(
        workspace_id, content_hash
    )
    dedup_reason = "content_hash" if existing_document_id else None
    if not existing_document_id:
        existing_document_id = await database.get_document_id_by_filename(workspace_id, filename)
        dedup_reason = "filename" if existing_document_id else None

    if existing_document_id:
        document_id = existing_document_id
        logger.info(
            "Reusing existing document_id for re-upload (reindex)",
            document_id=document_id,
            workspace_id=workspace_id,
            filename=filename,
            dedup_reason=dedup_reason,
        )

        # Identical-content short-circuit (#75). A content-hash match means the
        # exact bytes are already known to this workspace, so re-running the
        # extract→chunk→embed→index pipeline would produce byte-identical chunks
        # and embeddings — pure wasted compute for the agent. It is also unsafe
        # under load: the ingestion workflow id is fixed per document
        # (`ingest-{document_id}`), so a redundant re-index serializes behind the
        # in-flight one and can leave the document stranded non-'processed' for
        # minutes. Unless the existing document actually needs recovery (status
        # 'failed'), return it as-is without re-uploading, resetting the row, or
        # re-enqueuing. Filename dedup and edited-content re-uploads (#60) have a
        # DIFFERENT content_hash, so they still fall through and re-index.
        if dedup_reason == "content_hash":
            existing = await database.get_document(document_id, workspace_id)
            if existing is not None and existing.status != "failed":
                upload_fields = await database.get_document_upload_fields(
                    document_id, workspace_id
                )
                logger.info(
                    "Identical content already ingested; skipping redundant re-index",
                    document_id=document_id,
                    workspace_id=workspace_id,
                    status=existing.status,
                )
                return DocumentUploadResponse(
                    document_id=document_id,
                    name=existing.name,
                    workspace_id=workspace_id,
                    storage_url=(upload_fields or {}).get("storage_url") or "",
                    mime_type=existing.mime_type or content_type,
                    size_bytes=existing.size_bytes or size_bytes,
                    status=existing.status,
                    message="Identical content already ingested; returning existing document.",
                )
    else:
        document_id = str(uuid.uuid4())
        logger.info(
            "Assigning new document_id for upload",
            document_id=document_id,
            workspace_id=workspace_id,
            filename=filename,
        )

    # --- 4. Upload to S3 ----------------------------------------------------
    try:
        storage = get_storage_service()
        s3_key = storage.generate_key(workspace_id, filename)
        await storage.upload_file(content_bytes, s3_key, content_type)
        storage_url = storage.build_storage_url(s3_key)
    except Exception as exc:
        logger.error("S3 upload failed", error=str(exc), document_id=document_id)
        raise ServiceUnavailableError(
            service_name="storage",
            detail="Failed to store the uploaded file. Please try again later.",
        ) from exc

    # --- 5. Persist a durable 'pending' row BEFORE enqueueing ----------------
    # This makes the upload recoverable and lets GET /v1/documents/{id} return
    # the document (status='pending') immediately, instead of 404ing until
    # ingestion finishes. On re-upload of the same document_id, this resets the
    # row to a clean pending state.
    try:
        await database.create_or_reset_pending_document(
            document_id=document_id,
            workspace_id=workspace_id,
            user_id=user_id,
            filename=s3_key.rsplit("/", 1)[-1],
            original_filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            storage_backend="s3",
            storage_path=s3_key,
            storage_bucket=storage._bucket,
            storage_url=storage_url,
            content_hash=content_hash,
        )
    except Exception as exc:
        logger.error(
            "Failed to persist pending document row",
            error=str(exc),
            document_id=document_id,
        )
        raise ServiceUnavailableError(
            service_name="database",
            detail="Failed to record the upload. Please try again later.",
        ) from exc

    # --- 6. Publish MQ message ----------------------------------------------
    now_iso = datetime.now(timezone.utc).isoformat()
    mq_message = {
        "event_type": "document.uploaded",
        "document_id": document_id,
        "workspace_id": workspace_id,
        "user_id": user_id,
        "filename": s3_key.rsplit("/", 1)[-1],
        "original_filename": filename,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "storage_backend": "s3",
        "storage_path": s3_key,
        "storage_bucket": storage._bucket,
        "storage_url": storage_url,
        "timestamp": now_iso,
        "contract_version": "1.0.0",
    }

    try:
        mq = await get_mq_service()
        await mq.publish(settings.mq_topic_document_uploaded, mq_message)
    except Exception as exc:
        # The file is in S3 and a durable 'pending' row exists, so the upload
        # is recoverable. But ingestion was NOT triggered, so we must NOT
        # report success: mark the row 'failed' and reflect that in the
        # response. We keep "stored" semantics (no raise) because the file IS
        # stored — REST maps this to 201 with status="failed" in the body.
        logger.error(
            "MQ publish failed — file stored but ingestion not enqueued",
            error=str(exc),
            document_id=document_id,
        )
        # The mark is retried with backoff; on exhaustion the helper emits the
        # CRITICAL log + metric that flag the orphaned 'pending' row (#99).
        await mark_document_failed_with_retry(
            database,
            document_id,
            workspace_id,
            "ingestion enqueue failed",
            operation="upload_enqueue",
        )

        return DocumentUploadResponse(
            document_id=document_id,
            name=filename,
            workspace_id=workspace_id,
            storage_url=storage_url,
            mime_type=content_type,
            size_bytes=size_bytes,
            status="failed",
            message=(
                "Document was stored but could not be queued for processing "
                "(ingestion enqueue failed). Please retry the upload."
            ),
        )

    # --- 7. Return response --------------------------------------------------
    logger.info(
        "Document upload accepted",
        document_id=document_id,
        workspace_id=workspace_id,
        filename=filename,
        size_bytes=size_bytes,
    )

    return DocumentUploadResponse(
        document_id=document_id,
        name=filename,
        workspace_id=workspace_id,
        storage_url=storage_url,
        mime_type=content_type,
        size_bytes=size_bytes,
        status="pending",
        message="Document uploaded successfully. Processing will begin shortly.",
    )
