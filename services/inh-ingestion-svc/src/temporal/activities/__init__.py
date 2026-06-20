"""Temporal activities for document ingestion pipeline.

Each activity represents a discrete, retriable step in the document
processing workflow.
"""

from src.temporal.activities.chunk import chunk_text
from src.temporal.activities.chunk_edit import update_chunk_postgresql, update_chunk_weaviate
from src.temporal.activities.cleanup import cleanup_staging
from src.temporal.activities.extract import extract_text
from src.temporal.activities.fetch import fetch_document
from src.temporal.activities.status import set_document_status
from src.temporal.activities.store import store_in_postgresql, store_in_weaviate
from src.temporal.activities.tenant import ensure_tenant_ready, update_workspace_stats

__all__ = [
    # Core activities
    "ensure_tenant_ready",
    "fetch_document",
    "extract_text",
    "chunk_text",
    "store_in_postgresql",
    "store_in_weaviate",
    "set_document_status",
    "update_workspace_stats",
    "cleanup_staging",
    # Chunk edit activities
    "update_chunk_postgresql",
    "update_chunk_weaviate",
]
