"""Unit tests for Temporal workflow/activity dataclasses in src/temporal/models.py.

Verifies construction, optional/nullable fields, and dataclass identity for all
16 dataclasses used in the ingestion Temporal workflows.
"""

import dataclasses

from src.temporal.models import (
    ChunkData,
    ChunkEditInput,
    ChunkEditResult,
    ChunkTextInput,
    ChunkTextOutput,
    CleanupStagingInput,
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STORAGE_BACKENDS = ("local", "s3", "gcs", "azure")


def _make_document_ingestion_input(**overrides) -> DocumentIngestionInput:
    defaults = dict(
        document_id="doc-001",
        workspace_id="ws-001",
        user_id="user-001",
        filename="report.pdf",
        original_filename="My Report.pdf",
        content_type="application/pdf",
        size_bytes=102400,
        storage_backend="s3",
        storage_path="docs/report.pdf",
    )
    defaults.update(overrides)
    return DocumentIngestionInput(**defaults)


def _make_store_document_input(**overrides) -> StoreDocumentInput:
    defaults = dict(
        workflow_run_id="run-001",
        document_id="doc-001",
        workspace_id="ws-001",
        user_id="user-001",
        filename="report.pdf",
        original_filename="My Report.pdf",
        content_type="application/pdf",
        size_bytes=102400,
        storage_backend="s3",
        storage_path="docs/report.pdf",
        text_length=5000,
        processing_time_ms=1200,
    )
    defaults.update(overrides)
    return StoreDocumentInput(**defaults)


# ---------------------------------------------------------------------------
# DocumentIngestionInput
# ---------------------------------------------------------------------------


class TestDocumentIngestionInput:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(DocumentIngestionInput)

    def test_required_fields(self):
        obj = _make_document_ingestion_input()
        assert obj.document_id == "doc-001"
        assert obj.workspace_id == "ws-001"
        assert obj.user_id == "user-001"
        assert obj.filename == "report.pdf"
        assert obj.original_filename == "My Report.pdf"
        assert obj.content_type == "application/pdf"
        assert obj.size_bytes == 102400
        assert obj.storage_backend == "s3"
        assert obj.storage_path == "docs/report.pdf"

    def test_optional_fields_default_to_none_or_empty(self):
        obj = _make_document_ingestion_input()
        assert obj.storage_bucket is None
        assert obj.storage_url is None
        assert obj.timestamp == ""

    def test_optional_fields_can_be_set(self):
        obj = _make_document_ingestion_input(
            storage_bucket="my-bucket",
            storage_url="https://s3.example.com/my-bucket/docs/report.pdf",
            timestamp="2026-04-06T00:00:00Z",
        )
        assert obj.storage_bucket == "my-bucket"
        assert obj.storage_url == "https://s3.example.com/my-bucket/docs/report.pdf"
        assert obj.timestamp == "2026-04-06T00:00:00Z"

    def test_all_storage_backends_accepted(self):
        for backend in _STORAGE_BACKENDS:
            obj = _make_document_ingestion_input(storage_backend=backend)
            assert obj.storage_backend == backend


# ---------------------------------------------------------------------------
# WorkflowResult
# ---------------------------------------------------------------------------


class TestWorkflowResult:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(WorkflowResult)

    def test_success_variant(self):
        obj = WorkflowResult(
            document_id="doc-001", success=True, chunks_created=42, processing_time_ms=800
        )
        assert obj.success is True
        assert obj.chunks_created == 42
        assert obj.error is None
        assert obj.processing_time_ms == 800

    def test_failure_variant(self):
        obj = WorkflowResult(document_id="doc-001", success=False, error="Extraction failed")
        assert obj.success is False
        assert obj.error == "Extraction failed"
        assert obj.chunks_created == 0
        assert obj.processing_time_ms == 0

    def test_defaults(self):
        obj = WorkflowResult(document_id="doc-002", success=True)
        assert obj.chunks_created == 0
        assert obj.processing_time_ms == 0
        assert obj.error is None


# ---------------------------------------------------------------------------
# EnsureTenantInput
# ---------------------------------------------------------------------------


class TestEnsureTenantInput:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(EnsureTenantInput)

    def test_required_fields(self):
        obj = EnsureTenantInput(workspace_id="ws-001", user_id="user-001")
        assert obj.workspace_id == "ws-001"
        assert obj.user_id == "user-001"

    def test_optional_fields_default_none(self):
        obj = EnsureTenantInput(workspace_id="ws-001", user_id="user-001")
        assert obj.workflow_run_id is None
        assert obj.document_id is None

    def test_optional_fields_can_be_set(self):
        obj = EnsureTenantInput(
            workspace_id="ws-001",
            user_id="user-001",
            workflow_run_id="run-abc",
            document_id="doc-001",
        )
        assert obj.workflow_run_id == "run-abc"
        assert obj.document_id == "doc-001"


# ---------------------------------------------------------------------------
# EnsureTenantOutput
# ---------------------------------------------------------------------------


class TestEnsureTenantOutput:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(EnsureTenantOutput)

    def test_with_tenant(self):
        obj = EnsureTenantOutput(tenant_id=7, workspace_ready=True)
        assert obj.tenant_id == 7
        assert obj.workspace_ready is True

    def test_tenant_id_can_be_none(self):
        obj = EnsureTenantOutput(tenant_id=None, workspace_ready=False)
        assert obj.tenant_id is None
        assert obj.workspace_ready is False


# ---------------------------------------------------------------------------
# FetchDocumentInput
# ---------------------------------------------------------------------------


class TestFetchDocumentInput:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(FetchDocumentInput)

    def test_required_fields(self):
        obj = FetchDocumentInput(
            document_id="doc-001",
            storage_backend="local",
            storage_path="/tmp/doc.pdf",
        )
        assert obj.document_id == "doc-001"
        assert obj.storage_backend == "local"
        assert obj.storage_path == "/tmp/doc.pdf"

    def test_optional_fields_default_none(self):
        obj = FetchDocumentInput(
            document_id="doc-001",
            storage_backend="s3",
            storage_path="docs/doc.pdf",
        )
        assert obj.storage_bucket is None
        assert obj.storage_url is None
        assert obj.workflow_run_id is None
        assert obj.workspace_id is None

    def test_optional_fields_can_be_set(self):
        obj = FetchDocumentInput(
            document_id="doc-001",
            storage_backend="s3",
            storage_path="docs/doc.pdf",
            storage_bucket="bucket-x",
            storage_url="https://s3.example.com/bucket-x/docs/doc.pdf",
            workflow_run_id="run-xyz",
            workspace_id="ws-001",
        )
        assert obj.storage_bucket == "bucket-x"
        assert obj.storage_url == "https://s3.example.com/bucket-x/docs/doc.pdf"
        assert obj.workflow_run_id == "run-xyz"
        assert obj.workspace_id == "ws-001"


# ---------------------------------------------------------------------------
# FetchDocumentOutput
# ---------------------------------------------------------------------------


class TestFetchDocumentOutput:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(FetchDocumentOutput)

    def test_construction(self):
        obj = FetchDocumentOutput(size_bytes=204800)
        assert obj.size_bytes == 204800


# ---------------------------------------------------------------------------
# ExtractTextInput
# ---------------------------------------------------------------------------


class TestExtractTextInput:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(ExtractTextInput)

    def test_required_fields(self):
        obj = ExtractTextInput(
            workflow_run_id="run-001",
            storage_backend="s3",
            storage_path="docs/doc.pdf",
            content_type="application/pdf",
            original_filename="doc.pdf",
        )
        assert obj.workflow_run_id == "run-001"
        assert obj.storage_backend == "s3"
        assert obj.storage_path == "docs/doc.pdf"
        assert obj.content_type == "application/pdf"
        assert obj.original_filename == "doc.pdf"

    def test_optional_fields_default_none(self):
        obj = ExtractTextInput(
            workflow_run_id="run-001",
            storage_backend="s3",
            storage_path="docs/doc.pdf",
            content_type="application/pdf",
            original_filename="doc.pdf",
        )
        assert obj.storage_bucket is None
        assert obj.storage_url is None
        assert obj.document_id is None
        assert obj.workspace_id is None

    def test_optional_fields_can_be_set(self):
        obj = ExtractTextInput(
            workflow_run_id="run-001",
            storage_backend="s3",
            storage_path="docs/doc.pdf",
            content_type="application/pdf",
            original_filename="doc.pdf",
            storage_bucket="bkt",
            storage_url="https://example.com/bkt/doc.pdf",
            document_id="doc-001",
            workspace_id="ws-001",
        )
        assert obj.storage_bucket == "bkt"
        assert obj.storage_url == "https://example.com/bkt/doc.pdf"
        assert obj.document_id == "doc-001"
        assert obj.workspace_id == "ws-001"


# ---------------------------------------------------------------------------
# ExtractTextOutput
# ---------------------------------------------------------------------------


class TestExtractTextOutput:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(ExtractTextOutput)

    def test_construction(self):
        obj = ExtractTextOutput(text_length=3500)
        assert obj.text_length == 3500


# ---------------------------------------------------------------------------
# ChunkData
# ---------------------------------------------------------------------------


class TestChunkData:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(ChunkData)

    def test_construction(self):
        obj = ChunkData(
            document_id="doc-001",
            content="Hello world",
            chunk_index=0,
            start_char=0,
            end_char=11,
        )
        assert obj.document_id == "doc-001"
        assert obj.content == "Hello world"
        assert obj.chunk_index == 0
        assert obj.start_char == 0
        assert obj.end_char == 11

    def test_non_zero_indices(self):
        obj = ChunkData(
            document_id="doc-001",
            content="Second chunk",
            chunk_index=1,
            start_char=12,
            end_char=24,
        )
        assert obj.chunk_index == 1
        assert obj.start_char == 12
        assert obj.end_char == 24


# ---------------------------------------------------------------------------
# ChunkTextInput
# ---------------------------------------------------------------------------


class TestChunkTextInput:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(ChunkTextInput)

    def test_required_fields(self):
        obj = ChunkTextInput(
            workflow_run_id="run-001",
            document_id="doc-001",
            strategy="tokens",
            max_chunk_size=512,
            chunk_overlap=50,
        )
        assert obj.workflow_run_id == "run-001"
        assert obj.document_id == "doc-001"
        assert obj.strategy == "tokens"
        assert obj.max_chunk_size == 512
        assert obj.chunk_overlap == 50
        assert obj.workspace_id is None

    def test_all_strategies_accepted(self):
        for strategy in ("tokens", "sentences", "paragraphs"):
            obj = ChunkTextInput(
                workflow_run_id="run-001",
                document_id="doc-001",
                strategy=strategy,
                max_chunk_size=256,
                chunk_overlap=0,
            )
            assert obj.strategy == strategy

    def test_workspace_id_optional(self):
        obj = ChunkTextInput(
            workflow_run_id="run-001",
            document_id="doc-001",
            strategy="paragraphs",
            max_chunk_size=1024,
            chunk_overlap=100,
            workspace_id="ws-001",
        )
        assert obj.workspace_id == "ws-001"


# ---------------------------------------------------------------------------
# ChunkTextOutput
# ---------------------------------------------------------------------------


class TestChunkTextOutput:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(ChunkTextOutput)

    def test_default_chunk_count(self):
        obj = ChunkTextOutput()
        assert obj.chunk_count == 0

    def test_explicit_chunk_count(self):
        obj = ChunkTextOutput(chunk_count=17)
        assert obj.chunk_count == 17


# ---------------------------------------------------------------------------
# StoreDocumentInput
# ---------------------------------------------------------------------------


class TestStoreDocumentInput:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(StoreDocumentInput)

    def test_required_fields(self):
        obj = _make_store_document_input()
        assert obj.workflow_run_id == "run-001"
        assert obj.document_id == "doc-001"
        assert obj.workspace_id == "ws-001"
        assert obj.user_id == "user-001"
        assert obj.filename == "report.pdf"
        assert obj.original_filename == "My Report.pdf"
        assert obj.content_type == "application/pdf"
        assert obj.size_bytes == 102400
        assert obj.storage_backend == "s3"
        assert obj.storage_path == "docs/report.pdf"
        assert obj.text_length == 5000
        assert obj.processing_time_ms == 1200

    def test_tenant_id_defaults_to_none(self):
        obj = _make_store_document_input()
        assert obj.tenant_id is None

    def test_tenant_id_can_be_set(self):
        obj = _make_store_document_input(tenant_id=42)
        assert obj.tenant_id == 42


# ---------------------------------------------------------------------------
# StoreDocumentOutput
# ---------------------------------------------------------------------------


class TestStoreDocumentOutput:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(StoreDocumentOutput)

    def test_success_variant(self):
        obj = StoreDocumentOutput(success=True, chunks_stored=10)
        assert obj.success is True
        assert obj.chunks_stored == 10
        assert obj.error is None

    def test_failure_variant(self):
        obj = StoreDocumentOutput(success=False, chunks_stored=0, error="DB write failed")
        assert obj.success is False
        assert obj.chunks_stored == 0
        assert obj.error == "DB write failed"


# ---------------------------------------------------------------------------
# UpdateStatsInput
# ---------------------------------------------------------------------------


class TestUpdateStatsInput:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(UpdateStatsInput)

    def test_required_fields(self):
        obj = UpdateStatsInput(
            workspace_id="ws-001",
            document_delta=1,
            chunk_delta=10,
            size_delta=2048,
        )
        assert obj.workspace_id == "ws-001"
        assert obj.document_delta == 1
        assert obj.chunk_delta == 10
        assert obj.size_delta == 2048

    def test_optional_fields_default_none(self):
        obj = UpdateStatsInput(
            workspace_id="ws-001",
            document_delta=1,
            chunk_delta=10,
            size_delta=2048,
        )
        assert obj.workflow_run_id is None
        assert obj.document_id is None

    def test_optional_fields_can_be_set(self):
        obj = UpdateStatsInput(
            workspace_id="ws-001",
            document_delta=1,
            chunk_delta=10,
            size_delta=2048,
            workflow_run_id="run-001",
            document_id="doc-001",
        )
        assert obj.workflow_run_id == "run-001"
        assert obj.document_id == "doc-001"

    def test_negative_deltas_for_deletion(self):
        obj = UpdateStatsInput(
            workspace_id="ws-001",
            document_delta=-1,
            chunk_delta=-10,
            size_delta=-2048,
        )
        assert obj.document_delta == -1
        assert obj.chunk_delta == -10
        assert obj.size_delta == -2048


# ---------------------------------------------------------------------------
# CleanupStagingInput
# ---------------------------------------------------------------------------


class TestCleanupStagingInput:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(CleanupStagingInput)

    def test_construction(self):
        obj = CleanupStagingInput(workflow_run_id="run-abc-123")
        assert obj.workflow_run_id == "run-abc-123"


# ---------------------------------------------------------------------------
# ChunkEditInput
# ---------------------------------------------------------------------------


class TestChunkEditInput:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(ChunkEditInput)

    def test_required_fields(self):
        obj = ChunkEditInput(
            document_id="doc-001",
            chunk_index=3,
            content="Updated chunk text",
        )
        assert obj.document_id == "doc-001"
        assert obj.chunk_index == 3
        assert obj.content == "Updated chunk text"

    def test_optional_fields_default_empty_string(self):
        obj = ChunkEditInput(
            document_id="doc-001",
            chunk_index=3,
            content="Updated chunk text",
        )
        assert obj.workspace_id == ""
        assert obj.user_id == ""

    def test_optional_fields_can_be_set(self):
        obj = ChunkEditInput(
            document_id="doc-001",
            chunk_index=3,
            content="Updated chunk text",
            workspace_id="ws-001",
            user_id="user-001",
        )
        assert obj.workspace_id == "ws-001"
        assert obj.user_id == "user-001"


# ---------------------------------------------------------------------------
# ChunkEditResult
# ---------------------------------------------------------------------------


class TestChunkEditResult:
    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(ChunkEditResult)

    def test_success_variant(self):
        obj = ChunkEditResult(document_id="doc-001", chunk_index=3, success=True)
        assert obj.success is True
        assert obj.error is None

    def test_failure_variant(self):
        obj = ChunkEditResult(
            document_id="doc-001",
            chunk_index=3,
            success=False,
            error="Weaviate update failed",
        )
        assert obj.success is False
        assert obj.error == "Weaviate update failed"

    def test_fields(self):
        obj = ChunkEditResult(document_id="doc-002", chunk_index=7, success=True)
        assert obj.document_id == "doc-002"
        assert obj.chunk_index == 7
