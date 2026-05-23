"""Tests for document processor backend selection and lifecycle."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.settings import Settings
from src.models.document import DocumentUploadMessage
from src.services.processor import DocumentProcessor


class TestProcessorBackend:
    @pytest.fixture
    def processor_settings(self):
        settings = MagicMock(spec=Settings)
        settings.max_chunk_size = 1000
        settings.chunk_overlap = 200
        settings.chunking_strategy = "tokens"
        return settings

    @pytest.mark.asyncio
    async def test_fetch_s3_backend(self, processor_settings):
        """Test fetching S3 document (not implemented)."""
        processor = DocumentProcessor(processor_settings)
        processor._initialized = True
        processor.storage_service = MagicMock()

        message = DocumentUploadMessage(
            event_type="document.uploaded",
            document_id="doc1",
            workspace_id="ws1",
            user_id="u1",
            filename="file.txt",
            original_filename="file.txt",
            content_type="text/plain",
            size_bytes=10,
            storage_backend="s3",
            storage_path="path",
            timestamp=datetime.now(UTC).isoformat() + "Z",
        )

        content = await processor._fetch_document(message)
        assert content is None

    @pytest.mark.asyncio
    async def test_fetch_s3_backend_with_url(self, processor_settings):
        """Test fetching S3 document with URL."""
        processor = DocumentProcessor(processor_settings)
        processor._initialized = True

        mock_storage = MagicMock()
        mock_storage.read_file_from_url = MagicMock(return_value=b"content")
        processor.storage_service = mock_storage

        message = DocumentUploadMessage(
            event_type="document.uploaded",
            document_id="doc1",
            workspace_id="ws1",
            user_id="u1",
            filename="file.txt",
            original_filename="file.txt",
            content_type="text/plain",
            size_bytes=10,
            storage_backend="s3",
            storage_path="path",
            storage_url="http://url",
            timestamp=datetime.now(UTC).isoformat() + "Z",
        )

        content = await processor._fetch_document(message)
        assert content == b"content"

    @pytest.mark.asyncio
    async def test_fetch_azure_backend(self, processor_settings):
        """Test fetching Azure document (not implemented)."""
        processor = DocumentProcessor(processor_settings)
        processor._initialized = True
        processor.storage_service = MagicMock()

        message = DocumentUploadMessage(
            event_type="document.uploaded",
            document_id="doc1",
            workspace_id="ws1",
            user_id="u1",
            filename="file.txt",
            original_filename="file.txt",
            content_type="text/plain",
            size_bytes=10,
            storage_backend="azure",
            storage_path="path",
            timestamp=datetime.now(UTC).isoformat() + "Z",
        )

        content = await processor._fetch_document(message)
        assert content is None

    @pytest.mark.asyncio
    async def test_fetch_azure_backend_with_url(self, processor_settings):
        """Test fetching Azure document with URL."""
        processor = DocumentProcessor(processor_settings)
        processor._initialized = True

        mock_storage = MagicMock()
        mock_storage.read_file_from_url = MagicMock(return_value=b"content")
        processor.storage_service = mock_storage

        message = DocumentUploadMessage(
            event_type="document.uploaded",
            document_id="doc1",
            workspace_id="ws1",
            user_id="u1",
            filename="file.txt",
            original_filename="file.txt",
            content_type="text/plain",
            size_bytes=10,
            storage_backend="azure",
            storage_path="path",
            storage_url="http://url",
            timestamp=datetime.now(UTC).isoformat() + "Z",
        )

        content = await processor._fetch_document(message)
        assert content == b"content"

    def test_shutdown(self, processor_settings):
        """Test shutdown."""
        processor = DocumentProcessor(processor_settings)
        processor.tenant_manager = MagicMock()
        processor.storage_service = MagicMock()
        processor.weaviate_service = MagicMock()
        processor.db_service = MagicMock()
        processor._initialized = True

        processor.shutdown()

        processor.tenant_manager.clear_cache.assert_called_once()
        processor.storage_service.disconnect.assert_called_once()
        processor.weaviate_service.disconnect.assert_called_once()
        processor.db_service.disconnect.assert_called_once()
        assert processor._initialized is False

    @pytest.mark.asyncio
    async def test_process_message_tenant_error(self, processor_settings):
        """Test processing continues on tenant setup error."""
        processor = DocumentProcessor(processor_settings)
        processor.initialize = MagicMock()
        processor._initialized = True

        mock_tenant_manager = MagicMock()
        mock_tenant_manager.ensure_workspace_ready = AsyncMock(
            side_effect=Exception("Tenant Error")
        )
        processor.tenant_manager = mock_tenant_manager

        processor._fetch_document = AsyncMock(return_value=b"content")
        processor._extract_text = AsyncMock(return_value="text")
        processor._chunk_text = MagicMock(return_value=[])
        processor._store_document = AsyncMock()

        message = {
            "event_type": "document.uploaded",
            "document_id": "doc1",
            "workspace_id": "ws1",
            "user_id": "u1",
            "filename": "file.txt",
            "original_filename": "file.txt",
            "content_type": "text/plain",
            "size_bytes": 10,
            "storage_backend": "local",
            "storage_path": "path",
            "timestamp": datetime.now(UTC).isoformat() + "Z",
        }

        result = await processor.process_message(message)

        assert result.success is True
        mock_tenant_manager.ensure_workspace_ready.assert_called_once()
