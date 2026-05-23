"""Chunks endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.models.document import DocumentChunk, DocumentContextResponse
from src.services.auth import ResolvedAuth, resolve_workspace_read
from src.services.database import DatabaseService, get_database

router = APIRouter()


@router.get("/chunks/{document_id}", response_model=list[DocumentChunk])
async def get_document_chunks(
    document_id: str,
    auth: Annotated[ResolvedAuth, Depends(resolve_workspace_read)],
    database: Annotated[DatabaseService, Depends(get_database)],
) -> list[DocumentChunk]:
    """
    Get all chunks for a document.

    Requires an API key with 'read' permission.
    Workspace can be specified via ``X-Workspace-Id`` header.
    """
    # Resolve document across workspaces if needed
    document = None
    workspace_id = auth.workspace_id

    if workspace_id:
        document = await database.get_document(
            document_id=document_id,
            workspace_id=workspace_id,
        )
    else:
        user_workspaces = await database.get_user_workspace_ids(auth.key_info.user_id)
        for ws_id in user_workspaces:
            document = await database.get_document(
                document_id=document_id,
                workspace_id=ws_id,
            )
            if document:
                workspace_id = ws_id
                break

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    chunks = await database.get_document_chunks(
        document_id=document_id,
        workspace_id=workspace_id,
    )

    return chunks


@router.get("/chunks/{document_id}/context", response_model=DocumentContextResponse)
async def get_document_context(
    document_id: str,
    auth: Annotated[ResolvedAuth, Depends(resolve_workspace_read)],
    database: Annotated[DatabaseService, Depends(get_database)],
) -> DocumentContextResponse:
    """
    Get full document context (document metadata + all chunks combined).

    Useful for retrieving complete document content for AI context.
    Requires an API key with 'read' permission.
    Workspace can be specified via ``X-Workspace-Id`` header.
    """
    document = None
    workspace_id = auth.workspace_id

    if workspace_id:
        document = await database.get_document(
            document_id=document_id,
            workspace_id=workspace_id,
        )
    else:
        user_workspaces = await database.get_user_workspace_ids(auth.key_info.user_id)
        for ws_id in user_workspaces:
            document = await database.get_document(
                document_id=document_id,
                workspace_id=ws_id,
            )
            if document:
                workspace_id = ws_id
                break

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    chunks = await database.get_document_chunks(
        document_id=document_id,
        workspace_id=workspace_id,
    )

    # Combine all chunk content into full text
    full_text = "\n\n".join(chunk.content for chunk in chunks)

    return DocumentContextResponse(
        document=document,
        chunks=chunks,
        full_text=full_text,
    )
