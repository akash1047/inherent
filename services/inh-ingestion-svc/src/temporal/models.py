"""Data models for Temporal workflow inputs and outputs.

These dataclasses are used for type-safe communication between
workflow steps and activities. All models are serializable
for Temporal's workflow history.

IMPORTANT: No model should carry large payloads (file bytes, full text,
chunk lists). Large data is staged in PostgreSQL (ingestion_staging table)
and referenced by workflow_run_id. This keeps every gRPC payload < 1KB
and avoids the 4MB Temporal limit.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass
class DocumentIngestionInput:
    """Input for the document ingestion workflow.

    Maps directly from DocumentUploadMessage Pub/Sub schema.
    """

    document_id: str
    workspace_id: str
    user_id: str
    filename: str
    original_filename: str
    content_type: str
    size_bytes: int
    storage_backend: Literal["local", "s3", "gcs", "azure"]
    storage_path: str
    storage_bucket: str | None = None
    storage_url: str | None = None
    timestamp: str = ""


@dataclass
class WorkflowResult:
    """Result of the document ingestion workflow."""

    document_id: str
    success: bool
    chunks_created: int = 0
    error: str | None = None
    processing_time_ms: int = 0


# =============================================================================
# Activity Input/Output Models
# =============================================================================


@dataclass
class EnsureTenantInput:
    """Input for ensure_tenant_ready activity."""

    workspace_id: str
    user_id: str
    workflow_run_id: str | None = None
    document_id: str | None = None


@dataclass
class EnsureTenantOutput:
    """Output from ensure_tenant_ready activity."""

    tenant_id: int | None
    workspace_ready: bool


@dataclass
class FetchDocumentInput:
    """Input for fetch_document activity."""

    document_id: str
    storage_backend: Literal["local", "s3", "gcs", "azure"]
    storage_path: str
    storage_bucket: str | None = None
    storage_url: str | None = None
    workflow_run_id: str | None = None
    workspace_id: str | None = None


@dataclass
class FetchDocumentOutput:
    """Output from fetch_document activity.

    No content bytes — the file stays in storage and is read
    directly by extract_text.
    """

    size_bytes: int


@dataclass
class ExtractTextInput:
    """Input for extract_text activity.

    Instead of receiving raw bytes via gRPC, the activity fetches
    the file directly from storage using these refs.
    """

    workflow_run_id: str
    storage_backend: Literal["local", "s3", "gcs", "azure"]
    storage_path: str
    content_type: str
    original_filename: str
    storage_bucket: str | None = None
    storage_url: str | None = None
    document_id: str | None = None
    workspace_id: str | None = None


@dataclass
class ExtractTextOutput:
    """Output from extract_text activity.

    Text is written to staging, only the length passes through gRPC.
    """

    text_length: int


@dataclass
class ChunkData:
    """Individual chunk data for serialization."""

    document_id: str
    content: str
    chunk_index: int
    start_char: int
    end_char: int


@dataclass
class ChunkTextInput:
    """Input for chunk_text activity.

    Reads text from staging instead of receiving it via gRPC.
    """

    workflow_run_id: str
    document_id: str
    strategy: Literal["tokens", "sentences", "paragraphs"]
    max_chunk_size: int
    chunk_overlap: int
    workspace_id: str | None = None


@dataclass
class ChunkTextOutput:
    """Output from chunk_text activity.

    Chunks are written to staging, only the count passes through gRPC.
    """

    chunk_count: int = 0


@dataclass
class StoreDocumentInput:
    """Input for store_document activities (PostgreSQL and Weaviate).

    Reads chunks from staging instead of receiving them via gRPC.
    """

    workflow_run_id: str
    document_id: str
    workspace_id: str
    user_id: str
    filename: str
    original_filename: str
    content_type: str
    size_bytes: int
    storage_backend: str
    storage_path: str
    text_length: int
    processing_time_ms: int
    tenant_id: int | None = None


@dataclass
class StoreDocumentOutput:
    """Output from store_document activities."""

    success: bool
    chunks_stored: int
    error: str | None = None


@dataclass
class UpdateStatsInput:
    """Input for update_workspace_stats activity.

    workflow_run_id is included for future idempotency (ledger-based
    dedup to prevent double-counting on Temporal retries).
    """

    workspace_id: str
    document_delta: int
    chunk_delta: int
    size_delta: int
    workflow_run_id: str | None = None
    document_id: str | None = None


# =============================================================================
# Staging Cleanup Models
# =============================================================================


@dataclass
class CleanupStagingInput:
    """Input for cleanup_staging activity."""

    workflow_run_id: str


# =============================================================================
# Chunk Edit Models
# =============================================================================


@dataclass
class ChunkEditInput:
    """Input for the chunk edit workflow."""

    document_id: str
    chunk_index: int
    content: str
    workspace_id: str = ""
    user_id: str = ""


@dataclass
class ChunkEditResult:
    """Result of the chunk edit workflow."""

    document_id: str
    chunk_index: int
    success: bool
    error: str | None = None
