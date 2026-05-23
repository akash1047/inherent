"""Document-related models."""

from datetime import datetime

from pydantic import BaseModel


class Document(BaseModel):
    """Document metadata."""

    id: str
    name: str
    workspace_id: str
    source_type: str
    mime_type: str | None = None
    size_bytes: int = 0
    chunk_count: int = 0
    status: str = "processed"
    created_at: datetime
    updated_at: datetime
    metadata: dict | None = None


class DocumentChunk(BaseModel):
    """A chunk from a document."""

    id: str
    document_id: str
    content: str
    chunk_index: int
    token_count: int = 0
    metadata: dict | None = None


class DocumentListResponse(BaseModel):
    """Response for listing documents."""

    documents: list[Document]
    total: int
    page: int
    page_size: int


class DocumentUploadResponse(BaseModel):
    """Response returned after a document is accepted for ingestion."""

    document_id: str
    name: str
    workspace_id: str
    storage_url: str
    mime_type: str
    size_bytes: int
    status: str = "pending"
    message: str = "Document uploaded successfully. Processing will begin shortly."


class DocumentContextResponse(BaseModel):
    """Response for getting full document context."""

    document: Document
    chunks: list[DocumentChunk]
    full_text: str
