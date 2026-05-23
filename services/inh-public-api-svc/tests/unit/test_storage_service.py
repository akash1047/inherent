"""Unit tests for src.services.storage."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.services.storage import StorageService, close_storage_service, get_storage_service


class TestStorageService:
    """Tests for StorageService."""

    def test_generate_key_format(self):
        """Key should be workspace_id/uuid/sanitized_filename."""
        with patch("src.services.storage.boto3"):
            svc = StorageService.__new__(StorageService)
            svc._client = MagicMock()
            svc._bucket = "test-bucket"

        key = svc.generate_key("ws-123", "my document (1).pdf")
        parts = key.split("/")
        assert parts[0] == "ws-123"
        assert len(parts) == 3
        # UUID segment
        assert len(parts[1]) == 36
        # Filename is sanitized
        assert " " not in parts[2]
        assert "(" not in parts[2]
        assert parts[2].endswith(".pdf")

    def test_sanitize_filename(self):
        assert StorageService._sanitize_filename("hello world.pdf") == "hello_world.pdf"
        # Truncates entire sanitized string to 255 chars (no extension preservation)
        assert StorageService._sanitize_filename("a" * 300 + ".txt") == ("a" * 255)
        assert StorageService._sanitize_filename("safe-file_v2.csv") == "safe-file_v2.csv"

    def test_build_storage_url(self):
        with patch("src.services.storage.boto3"):
            svc = StorageService.__new__(StorageService)
            svc._bucket = "inherent-documents"
        url = svc.build_storage_url("ws/uuid/file.pdf")
        assert url == "s3://inherent-documents/ws/uuid/file.pdf"

    async def test_upload_file(self):
        with patch("src.services.storage.boto3") as mock_boto:
            mock_client = MagicMock()
            mock_boto.client.return_value = mock_client

            svc = StorageService.__new__(StorageService)
            svc._client = mock_client
            svc._bucket = "test-bucket"

            key = await svc.upload_file(b"content", "ws/uuid/f.pdf", "application/pdf")

            assert key == "ws/uuid/f.pdf"
            mock_client.put_object.assert_called_once_with(
                Bucket="test-bucket",
                Key="ws/uuid/f.pdf",
                Body=b"content",
                ContentType="application/pdf",
            )


class TestStorageSingleton:
    """Tests for singleton management functions."""

    async def test_get_and_close(self):
        with patch("src.services.storage.boto3"):
            # Reset global state
            import src.services.storage as mod

            mod._storage_service = None

            svc = get_storage_service()
            assert svc is not None
            assert get_storage_service() is svc  # same instance

            await close_storage_service()
            assert mod._storage_service is None
