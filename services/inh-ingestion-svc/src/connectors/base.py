"""Base connector interface."""

from abc import ABC, abstractmethod

from src.models.document import DocumentMetadata


class BaseConnector(ABC):
    """Base class for document connectors."""

    @abstractmethod
    def connect(self) -> None:
        """Connect to the data source."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the data source."""
        pass

    @abstractmethod
    def fetch_document(self, location: str) -> bytes:
        """Fetch document content from the source."""
        pass

    @abstractmethod
    def fetch_metadata(self, location: str) -> DocumentMetadata | None:
        """Fetch document metadata from the source."""
        pass
