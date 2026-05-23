"""Documents endpoint."""

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from src.config import settings
from src.config.constants import ALLOWED_MIME_TYPES, MAX_UPLOAD_SIZE_BYTES
from src.core.exceptions import BadRequestError, ServiceUnavailableError
from src.models.document import Document, DocumentListResponse, DocumentUploadResponse
from src.services.auth import ResolvedAuth, resolve_workspace_read, resolve_workspace_write
from src.services.database import DatabaseService, get_database
from src.services.mq import get_mq_service
from src.services.storage import get_storage_service
from src.utils import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/documents", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    auth: Annotated[ResolvedAuth, Depends(resolve_workspace_write)] = ...,  # type: ignore[assignment]
) -> DocumentUploadResponse:
    """
    Upload a document for ingestion.

    The file is stored in S3 and a message is published to the ingestion
    pipeline.  Processing happens asynchronously; the returned status will
    be ``"pending"`` until the ingestion service completes.

    Requires an API key with **write** permission.
    Workspace can be specified via ``X-Workspace-Id`` header.
    """
    # --- 1. Validate content type -------------------------------------------
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_MIME_TYPES:
        raise BadRequestError(
            detail=(
                f"Unsupported file type '{content_type}'. "
                f"Allowed types: {', '.join(ALLOWED_MIME_TYPES)}"
            ),
        )

    # --- 2. Read file content & validate size --------------------------------
    file_content = await file.read()
    size_bytes = len(file_content)

    if size_bytes == 0:
        raise BadRequestError(detail="Uploaded file is empty.")

    if size_bytes > MAX_UPLOAD_SIZE_BYTES:
        max_mb = MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
        raise BadRequestError(
            detail=f"File size ({size_bytes} bytes) exceeds the {max_mb} MB limit.",
        )

    # --- 3. Determine identifiers -------------------------------------------
    workspace_id = auth.workspace_id
    # resolve_workspace_write guarantees workspace_id is set, but guard anyway
    if not workspace_id:
        raise BadRequestError(
            detail="Workspace ID required. Provide X-Workspace-Id header.",
        )

    document_id = str(uuid.uuid4())
    filename = file.filename or "unnamed"

    # --- 4. Upload to S3 ----------------------------------------------------
    try:
        storage = get_storage_service()
        s3_key = storage.generate_key(workspace_id, filename)
        await storage.upload_file(file_content, s3_key, content_type)
        storage_url = storage.build_storage_url(s3_key)
    except Exception as exc:
        logger.error("S3 upload failed", error=str(exc), document_id=document_id)
        raise ServiceUnavailableError(
            service_name="storage",
            detail="Failed to store the uploaded file. Please try again later.",
        ) from exc

    # --- 5. Publish MQ message ----------------------------------------------
    now_iso = datetime.now(timezone.utc).isoformat()
    mq_message = {
        "event_type": "document.uploaded",
        "document_id": document_id,
        "workspace_id": workspace_id,
        "user_id": auth.key_info.user_id,
        "filename": s3_key.rsplit("/", 1)[-1],
        "original_filename": filename,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "storage_backend": "s3",
        "storage_path": s3_key,
        "storage_bucket": storage._bucket,
        "storage_url": storage_url,
        "timestamp": now_iso,
    }

    try:
        mq = await get_mq_service()
        await mq.publish(settings.mq_topic_document_uploaded, mq_message)
    except Exception as exc:
        # The file is already in S3, so log but don't fail the request —
        # a retry mechanism or dead-letter queue should recover this.
        logger.error(
            "MQ publish failed — file stored but ingestion not triggered",
            error=str(exc),
            document_id=document_id,
        )

    # --- 6. Return response --------------------------------------------------
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


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    auth: Annotated[ResolvedAuth, Depends(resolve_workspace_read)],
    database: Annotated[DatabaseService, Depends(get_database)],
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
) -> DocumentListResponse:
    """
    List documents in the workspace.

    Requires an API key with 'read' permission.
    Workspace can be specified via ``X-Workspace-Id`` header.
    """
    if auth.workspace_id:
        documents, total = await database.get_documents(
            workspace_id=auth.workspace_id,
            page=page,
            page_size=page_size,
        )
    else:
        # User-scoped key with no workspace specified — list across all workspaces
        user_workspaces = await database.get_user_workspace_ids(auth.key_info.user_id)
        if user_workspaces:
            documents, total = await database.get_documents_multi_workspace(
                workspace_ids=user_workspaces,
                page=page,
                page_size=page_size,
            )
        else:
            documents, total = [], 0

    return DocumentListResponse(
        documents=documents,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/documents/{document_id}", response_model=Document)
async def get_document(
    document_id: str,
    auth: Annotated[ResolvedAuth, Depends(resolve_workspace_read)],
    database: Annotated[DatabaseService, Depends(get_database)],
) -> Document:
    """
    Get a specific document by ID.

    Requires an API key with 'read' permission.
    """
    if auth.workspace_id:
        document = await database.get_document(
            document_id=document_id,
            workspace_id=auth.workspace_id,
        )
    else:
        # User-scoped key — search across all user's workspaces
        user_workspaces = await database.get_user_workspace_ids(auth.key_info.user_id)
        document = None
        for ws_id in user_workspaces:
            document = await database.get_document(
                document_id=document_id,
                workspace_id=ws_id,
            )
            if document:
                break

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    return document
