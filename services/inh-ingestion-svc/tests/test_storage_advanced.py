"""Advanced tests for Storage service."""

from unittest.mock import MagicMock

import pytest

from src.config.settings import Settings
from src.services.storage import LocalStorageBackend


class TestLocalStorageBackendAdvanced:
    @pytest.fixture
    def mock_settings(self, tmp_path):
        settings = MagicMock(spec=Settings)
        settings.local_storage_path = str(tmp_path)
        return settings

    def test_read_file_directory_not_file(self, mock_settings, tmp_path):
        """Test read_file raises FileNotFoundError when path is a directory."""
        backend = LocalStorageBackend(mock_settings)
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        with pytest.raises(FileNotFoundError):
            backend.read_file("subdir")

    def test_read_file_relative_path(self, mock_settings, tmp_path):
        """Test read_file resolves relative paths within base path."""
        test_file = tmp_path / "storage" / "doc.pdf"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_bytes(b"pdf-content")

        backend = LocalStorageBackend(mock_settings)
        content = backend.read_file("storage/doc.pdf")
        assert content == b"pdf-content"

    def test_file_exists_returns_false_on_permission_error(self, mock_settings, tmp_path):
        """Test file_exists returns False when path traversal is attempted."""
        backend = LocalStorageBackend(mock_settings)
        # Traversal outside base path is caught by _resolve and returns False
        assert backend.file_exists("../../etc/passwd") is False

    def test_path_traversal_with_dot_dot(self, mock_settings, tmp_path):
        """Test that ../.. traversal is blocked."""
        backend = LocalStorageBackend(mock_settings)

        with pytest.raises(PermissionError, match="Path traversal blocked"):
            backend.read_file("../../etc/passwd")
