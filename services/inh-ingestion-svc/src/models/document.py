"""Document models for the ingestion service.

The cross-service event schemas (``DocumentUploadMessage`` /
``DocumentCompletionMessage``) and the ``StorageBackend`` type now live in the
shared ``inh_contracts`` package (single source of truth, #17). They are
re-exported here so existing imports keep working, e.g.::

    from src.models.document import DocumentUploadMessage
"""

from datetime import datetime
from typing import Any

# Re-exported from the shared contracts package (single source of truth, #17).
from inh_contracts.events import (
    DocumentCompletionMessage,
    DocumentUploadMessage,
    StorageBackend,
)
from pydantic import BaseModel

__all__ = [
    "StorageBackend",
    "DocumentMetadata",
    "DocumentChunk",
    "DocumentUploadMessage",
    "ProcessingResult",
    "DocumentCompletionMessage",
]


class DocumentMetadata(BaseModel):
    """Document metadata model used by connectors."""

    id: str | None = None
    filename: str
    file_type: str
    file_size: int
    file_location: str
    workspace_id: str | None = None
    user_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocumentChunk(BaseModel):
    """Document chunk model for storing processed text chunks."""

    id: str | None = None
    document_id: str
    content: str
    chunk_index: int
    start_char: int = 0
    end_char: int = 0
    token_count: int | None = None
    embedding: list[float] | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None


class ProcessingResult(BaseModel):
    """Result of document processing."""

    document_id: str
    success: bool
    chunks_created: int = 0
    error: str | None = None
    processing_time_ms: int = 0
