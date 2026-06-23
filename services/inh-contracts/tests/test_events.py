"""Event round-trip / contract tests for the shared event schemas (#17)."""

from inh_contracts.events import (
    CONTRACT_VERSION,
    DocumentCompletionMessage,
    DocumentUploadMessage,
)

CANONICAL_UPLOAD_KEYS_V1 = {
    "event_type",
    "document_id",
    "workspace_id",
    "user_id",
    "filename",
    "original_filename",
    "content_type",
    "size_bytes",
    "storage_backend",
    "storage_path",
    "storage_bucket",
    "storage_url",
    "timestamp",
    "contract_version",
}


def _canonical_upload_event() -> dict:
    return {
        "event_type": "document.uploaded",
        "document_id": "507f1f77bcf86cd799439011",
        "workspace_id": "507f1f77bcf86cd799439012",
        "user_id": "507f1f77bcf86cd799439013",
        "filename": "1234567890-abc12345-document.pdf",
        "original_filename": "document.pdf",
        "content_type": "application/pdf",
        "size_bytes": 102400,
        "storage_backend": "gcs",
        "storage_path": "workspaces/507f1f77bcf86cd799439012/doc.pdf",
        "storage_bucket": "documents",
        "storage_url": "https://storage.googleapis.com/documents/workspaces/doc.pdf",
        "timestamp": "2024-01-15T10:30:00Z",
        "contract_version": CONTRACT_VERSION,
    }


def test_canonical_key_set_matches_model_fields() -> None:
    assert set(DocumentUploadMessage.model_fields.keys()) == CANONICAL_UPLOAD_KEYS_V1


def test_upload_event_round_trip_lossless() -> None:
    event = _canonical_upload_event()
    msg = DocumentUploadMessage(**event)
    dumped = msg.model_dump()

    assert set(dumped.keys()) == CANONICAL_UPLOAD_KEYS_V1
    assert dumped == event
    assert dumped["contract_version"] == "1.0.0"


def test_upload_event_without_contract_version_defaults() -> None:
    event = _canonical_upload_event()
    del event["contract_version"]

    msg = DocumentUploadMessage(**event)
    assert msg.contract_version == "1.0.0"


def test_upload_event_unwraps_avro_union() -> None:
    event = _canonical_upload_event()
    event["storage_bucket"] = {"string": "documents"}
    event["storage_url"] = None

    msg = DocumentUploadMessage(**event)
    assert msg.storage_bucket == "documents"
    assert msg.storage_url is None


def test_completion_message_round_trip() -> None:
    msg = DocumentCompletionMessage(
        event_type="document.processed",
        document_id="d",
        workspace_id="w",
        user_id="u",
        original_filename="f.pdf",
        success=True,
        status="ready",
        timestamp="2024-01-15T10:30:00Z",
    )
    assert msg.contract_version == "1.0.0"

    dumped = msg.model_dump()
    restored = DocumentCompletionMessage(**dumped)
    assert restored.model_dump() == dumped
