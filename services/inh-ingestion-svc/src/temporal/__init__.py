"""Temporal workflow orchestration for document ingestion.

This module provides durable, fault-tolerant workflow execution for the
document processing pipeline using Temporal.

Components:
- activities/: Individual processing steps as Temporal activities
- workflows/: Workflow definitions that orchestrate activities
- worker.py: Temporal worker configuration and execution
- models.py: Data models for workflow inputs/outputs
"""

from src.temporal.models import (
    ChunkTextInput,
    ChunkTextOutput,
    DocumentIngestionInput,
    EnsureTenantInput,
    EnsureTenantOutput,
    ExtractTextInput,
    ExtractTextOutput,
    FetchDocumentInput,
    FetchDocumentOutput,
    StoreDocumentInput,
    StoreDocumentOutput,
    UpdateStatsInput,
    WorkflowResult,
)

__all__ = [
    "DocumentIngestionInput",
    "WorkflowResult",
    "EnsureTenantInput",
    "EnsureTenantOutput",
    "FetchDocumentInput",
    "FetchDocumentOutput",
    "ExtractTextInput",
    "ExtractTextOutput",
    "ChunkTextInput",
    "ChunkTextOutput",
    "StoreDocumentInput",
    "StoreDocumentOutput",
    "UpdateStatsInput",
]
