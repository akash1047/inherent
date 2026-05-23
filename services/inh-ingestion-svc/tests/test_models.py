"""Tests for document models and validation."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.models.document import (
    DocumentChunk,
    DocumentMetadata,
    DocumentUploadMessage,
    ProcessingResult,
)


class TestDocumentUploadMessage:
    """Tests for DocumentUploadMessage model."""

    def test_valid_message_creation(self, sample_upload_message: dict):
        """Test creating a valid message."""
        message = DocumentUploadMessage(**sample_upload_message)

        assert message.event_type == "document.uploaded"
        assert message.document_id == "test_doc_12345"
        assert message.workspace_id == "test_workspace_001"
        assert message.user_id == "test_user_001"
        assert message.content_type == "text/plain"
        assert message.size_bytes == 1024
        assert message.storage_backend == "local"

    def test_avro_union_unwrapping(self, sample_upload_message_avro_wrapped: dict):
        """Test that Avro union types are properly unwrapped."""
        message = DocumentUploadMessage(**sample_upload_message_avro_wrapped)

        # Avro wraps strings as {"string": "value"}
        assert message.storage_bucket == "test-bucket"
        assert "localhost:4000" in message.storage_url

    def test_avro_null_handling(self):
        """Test that null values are handled correctly."""
        message_data = {
            "event_type": "document.uploaded",
            "document_id": "test_doc_null",
            "workspace_id": "test_workspace",
            "user_id": "test_user",
            "filename": "test.pdf",
            "original_filename": "test.pdf",
            "content_type": "application/pdf",
            "size_bytes": 100,
            "storage_backend": "local",
            "storage_path": "/path/to/file",
            "storage_bucket": None,
            "storage_url": None,
            "timestamp": datetime.now(UTC).isoformat() + "Z",
        }

        message = DocumentUploadMessage(**message_data)
        assert message.storage_bucket is None
        assert message.storage_url is None

    def test_invalid_event_type_rejected(self, sample_upload_message: dict):
        """Test that invalid event type is rejected."""
        sample_upload_message["event_type"] = "invalid.event"

        with pytest.raises(ValidationError) as exc_info:
            DocumentUploadMessage(**sample_upload_message)

        assert "event_type" in str(exc_info.value)

    def test_invalid_storage_backend_rejected(self, sample_upload_message: dict):
        """Test that invalid storage backend is rejected."""
        sample_upload_message["storage_backend"] = "invalid_backend"

        with pytest.raises(ValidationError) as exc_info:
            DocumentUploadMessage(**sample_upload_message)

        assert "storage_backend" in str(exc_info.value)

    def test_zero_size_bytes_rejected(self, sample_upload_message: dict):
        """Test that zero size_bytes is rejected."""
        sample_upload_message["size_bytes"] = 0

        with pytest.raises(ValidationError) as exc_info:
            DocumentUploadMessage(**sample_upload_message)

        assert "size_bytes" in str(exc_info.value)

    def test_negative_size_bytes_rejected(self, sample_upload_message: dict):
        """Test that negative size_bytes is rejected."""
        sample_upload_message["size_bytes"] = -100

        with pytest.raises(ValidationError):
            DocumentUploadMessage(**sample_upload_message)

    def test_missing_required_field_rejected(self, sample_upload_message: dict):
        """Test that missing required field is rejected."""
        del sample_upload_message["document_id"]

        with pytest.raises(ValidationError) as exc_info:
            DocumentUploadMessage(**sample_upload_message)

        assert "document_id" in str(exc_info.value)

    def test_all_storage_backends_accepted(self, sample_upload_message: dict):
        """Test that all valid storage backends are accepted."""
        valid_backends = ["local", "s3"]

        for backend in valid_backends:
            sample_upload_message["storage_backend"] = backend
            message = DocumentUploadMessage(**sample_upload_message)
            assert message.storage_backend == backend


class TestDocumentChunk:
    """Tests for DocumentChunk model."""

    def test_valid_chunk_creation(self):
        """Test creating a valid chunk."""
        chunk = DocumentChunk(
            document_id="doc_123",
            content="This is test content.",
            chunk_index=0,
            start_char=0,
            end_char=21,
        )

        assert chunk.document_id == "doc_123"
        assert chunk.content == "This is test content."
        assert chunk.chunk_index == 0
        assert chunk.start_char == 0
        assert chunk.end_char == 21
        assert chunk.embedding is None
        assert chunk.metadata is None

    def test_chunk_with_metadata(self):
        """Test chunk with metadata."""
        chunk = DocumentChunk(
            document_id="doc_123",
            content="Content with metadata.",
            chunk_index=1,
            metadata={"page": 5, "section": "Introduction"},
        )

        assert chunk.metadata["page"] == 5
        assert chunk.metadata["section"] == "Introduction"

    def test_chunk_with_embedding(self):
        """Test chunk with embedding vector."""
        embedding = [0.1, 0.2, 0.3, 0.4, 0.5]
        chunk = DocumentChunk(
            document_id="doc_123",
            content="Content with embedding.",
            chunk_index=0,
            embedding=embedding,
        )

        assert chunk.embedding == embedding
        assert len(chunk.embedding) == 5


class TestProcessingResult:
    """Tests for ProcessingResult model."""

    def test_successful_result(self):
        """Test successful processing result."""
        result = ProcessingResult(
            document_id="doc_123",
            success=True,
            chunks_created=10,
            processing_time_ms=1500,
        )

        assert result.success is True
        assert result.chunks_created == 10
        assert result.error is None
        assert result.processing_time_ms == 1500

    def test_failed_result(self):
        """Test failed processing result."""
        result = ProcessingResult(
            document_id="doc_123",
            success=False,
            error="Failed to extract text",
        )

        assert result.success is False
        assert result.error == "Failed to extract text"
        assert result.chunks_created == 0


class TestDocumentMetadata:
    """Tests for DocumentMetadata model."""

    def test_valid_metadata_creation(self):
        """Test creating valid metadata."""
        metadata = DocumentMetadata(
            filename="test.pdf",
            file_type="application/pdf",
            file_size=1024,
            file_location="/path/to/file",
            workspace_id="ws_123",
        )

        assert metadata.filename == "test.pdf"
        assert metadata.file_size == 1024
        assert metadata.workspace_id == "ws_123"
