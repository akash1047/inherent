"""Failure-injection: storage (S3) dependency errors must propagate.

When object storage fails mid-fetch (network blip, throttling, missing
object), the ingestion pipeline must SEE the error so the message can be
retried — the failure must not be swallowed and reported as success.

All mocking is at the boto3 client boundary; no live S3/MinIO is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from src.config.settings import Settings
from src.services.storage import S3StorageBackend, StorageService

pytestmark = pytest.mark.failure_injection


@pytest.fixture
def mock_settings():
    settings = MagicMock(spec=Settings)
    settings.storage_bucket = "test-bucket"
    settings.s3_endpoint = "https://example.invalid"
    settings.s3_access_key_id = "test-key"
    settings.s3_secret_access_key = "test-secret"
    settings.s3_region = "nbg1"
    return settings


def _client_error(op: str = "GetObject", code: str = "InternalError") -> ClientError:
    """Build a boto3-style ClientError as the real client would raise."""
    return ClientError(
        {"Error": {"Code": code, "Message": "injected failure"}},
        op,
    )


def test_read_file_propagates_client_error(mock_settings):
    """get_object raising a boto3 ClientError must propagate out of read_file."""
    backend = S3StorageBackend(mock_settings)
    backend.client = MagicMock()
    backend.client.get_object.side_effect = _client_error()

    with pytest.raises(ClientError):
        backend.read_file("docs/report.pdf")


def test_read_file_propagates_body_read_error(mock_settings):
    """A streaming-body read error (connection reset) must also propagate."""
    backend = S3StorageBackend(mock_settings)
    backend.client = MagicMock()
    body = MagicMock()
    body.read.side_effect = ConnectionError("stream interrupted")
    backend.client.get_object.return_value = {"Body": body}

    with pytest.raises(ConnectionError):
        backend.read_file("docs/report.pdf")


def test_service_read_file_propagates_client_error(mock_settings):
    """The error must survive routing through the StorageService facade too."""
    service = StorageService(mock_settings)
    backend = S3StorageBackend(mock_settings)
    backend.client = MagicMock()
    backend.client.get_object.side_effect = _client_error(code="NoSuchKey")
    service._backends["s3"] = backend
    service._connected = True

    with pytest.raises(ClientError):
        service.read_file("docs/missing.pdf", backend="s3")


def test_read_file_not_connected_raises(mock_settings):
    """A dropped connection (client is None) surfaces as RuntimeError, not silent."""
    backend = S3StorageBackend(mock_settings)
    backend.client = None

    with pytest.raises(RuntimeError, match="S3 not connected"):
        backend.read_file("docs/report.pdf")
