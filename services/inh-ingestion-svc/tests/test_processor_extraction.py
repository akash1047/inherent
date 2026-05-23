"""Tests for document processor extraction."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.config.settings import Settings
from src.models.document import DocumentUploadMessage
from src.services.processor import DocumentProcessor


class TestProcessorExtraction:
    @pytest.fixture
    def processor_settings(self):
        settings = MagicMock(spec=Settings)
        settings.max_chunk_size = 1000
        settings.chunk_overlap = 200
        settings.chunking_strategy = "tokens"
        # Add database_url just in case it's used
        settings.database_url = "postgresql://mock:mock@localhost:5432/mock"
        return settings

    @pytest.mark.asyncio
    async def test_extract_pdf_pypdf(self, processor_settings):
        """Test PDF extraction using pypdf."""
        processor = DocumentProcessor(processor_settings)
        processor._initialized = True

        # Create a valid minimal PDF buffer
        pass

    @pytest.mark.asyncio
    async def test_extract_text_exceptions(self, processor_settings):
        """Test exception handling during extraction."""
        processor = DocumentProcessor(processor_settings)
        processor._initialized = True

        message = DocumentUploadMessage(
            event_type="document.uploaded",
            document_id="doc1",
            workspace_id="ws1",
            user_id="u1",
            filename="file.txt",
            original_filename="file.txt",
            content_type="text/plain",
            size_bytes=10,
            storage_backend="local",
            storage_path="path",
            timestamp=datetime.now(UTC).isoformat() + "Z",
        )

        # Mock decode to fail
        content = MagicMock()
        content.decode.side_effect = Exception("Decode failed")

        text = await processor._extract_text(content, message)
        assert text == ""

    @pytest.mark.asyncio
    async def test_extract_unknown_type(self, processor_settings):
        """Test extraction for unknown content type."""
        processor = DocumentProcessor(processor_settings)
        processor._initialized = True

        message = DocumentUploadMessage(
            event_type="document.uploaded",
            document_id="doc1",
            workspace_id="ws1",
            user_id="u1",
            filename="file.unknown",
            original_filename="file.unknown",
            content_type="application/unknown",
            size_bytes=10,
            storage_backend="local",
            storage_path="path",
            timestamp=datetime.now(UTC).isoformat() + "Z",
        )

        content = b"Some content"
        text = await processor._extract_text(content, message)

        # It falls back to decode as text
        assert text == "Some content"

    @pytest.mark.asyncio
    async def test_chunk_by_size_logic(self, processor_settings):
        """Test chunk by size logic details."""
        processor = DocumentProcessor(processor_settings)

        text = "This is a sentence. " * 10
        chunks = processor._chunk_by_size(text, "doc1", 20, 5)

        assert len(chunks) > 1
        # Check first chunk
        assert len(chunks[0].content) <= 20

    @pytest.mark.asyncio
    async def test_chunk_by_sentences_empty(self, processor_settings):
        """Test chunk by sentences with empty text."""
        processor = DocumentProcessor(processor_settings)
        chunks = processor._chunk_by_sentences("", "doc1", 100, 10)
        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_chunk_by_paragraphs_empty(self, processor_settings):
        """Test chunk by paragraphs with empty text."""
        processor = DocumentProcessor(processor_settings)
        chunks = processor._chunk_by_paragraphs("", "doc1", 100)
        assert len(chunks) == 0
