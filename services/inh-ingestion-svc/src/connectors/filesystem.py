"""Local filesystem connector."""

from pathlib import Path

from src.connectors.base import BaseConnector
from src.models.document import DocumentMetadata


class FilesystemConnector(BaseConnector):
    """Connector for local filesystem."""

    def __init__(self, base_path: str = "."):
        """Initialize filesystem connector."""
        self.base_path = Path(base_path)

    def connect(self) -> None:
        """Connect to filesystem (no-op)."""
        pass

    def disconnect(self) -> None:
        """Disconnect from filesystem (no-op)."""
        pass

    def fetch_document(self, location: str) -> bytes:
        """Fetch document from filesystem."""
        file_path = self.base_path / location
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        return file_path.read_bytes()

    def fetch_metadata(self, location: str) -> DocumentMetadata | None:
        """Fetch metadata from filesystem."""
        file_path = self.base_path / location
        if not file_path.exists():
            return None

        stat = file_path.stat()
        return DocumentMetadata(
            filename=file_path.name,
            file_type=file_path.suffix,
            file_size=stat.st_size,
            file_location=str(file_path),
        )
