"""#219: get_document_context MCP tool must be bounded by the SAME default
as REST GET /v1/chunks/{document_id}/context.

Before this fix, the MCP tool concatenated every chunk with no limit at
all -- the surface the issue calls out as most at risk, since an agent can
blow its own context window with a single tool call and had no parameter to
ask for less. These tests drive `_handle_get_context` directly (same
pattern as tests/security/test_mcp_workspace_boundaries.py) and cross-check
against the shared `windowed_document_context` helper REST also calls, to
pin REST/MCP parity rather than asserting two independently-chosen numbers.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.mcp_server import server as mcp_server
from src.models.api_key import APIKeyInfo
from src.models.document import DEFAULT_MAX_CHARS, Document, DocumentChunk

pytestmark = [pytest.mark.asyncio]


def _key() -> APIKeyInfo:
    return APIKeyInfo(
        key_id="key-1",
        user_id="user-1",
        workspace_id=None,
        permissions=["read"],
        rate_limit=100,
        expires_at=None,
        status="active",
    )


def _document() -> Document:
    now = datetime.now(timezone.utc)
    return Document(
        id="doc-1",
        name="report.pdf",
        workspace_id="ws-1",
        source_type="s3",
        mime_type="application/pdf",
        size_bytes=1000,
        chunk_count=5,
        status="processed",
        created_at=now,
        updated_at=now,
    )


def _long_chunks() -> list[DocumentChunk]:
    """5 chunks of 6,000 chars each -> 30,008 chars joined, over the
    20,000-char default bound -- same fixture shape as the REST tests."""
    return [
        DocumentChunk(
            id=f"chunk-{i}",
            document_id="doc-1",
            content="x" * 6000,
            chunk_index=i,
            token_count=6000,
            metadata=None,
        )
        for i in range(5)
    ]


def _structured_payload(text: str) -> dict:
    """Pull the trailing ```json ...``` block _structured() appends."""
    block = text.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    return json.loads(block)["structured"]


def _patch_db(mock_db: AsyncMock):
    return patch.object(mcp_server, "get_database", AsyncMock(return_value=mock_db))


def _mock_db(document: Document, chunks: list[DocumentChunk]) -> AsyncMock:
    db = AsyncMock()
    db.get_document_by_id = AsyncMock(return_value=document)
    db.get_user_workspace_ids = AsyncMock(return_value=[document.workspace_id])
    db.get_document_chunks_by_doc_id = AsyncMock(return_value=chunks)
    return db


class TestGetDocumentContextToolBounds:
    async def test_default_call_is_bounded_by_the_same_default_as_rest(self):
        """No max_chars/offset supplied -> the tool truncates at
        DEFAULT_MAX_CHARS, the exact constant REST's Query default uses."""
        db = _mock_db(_document(), _long_chunks())
        with _patch_db(db):
            result = await mcp_server._handle_get_context(_key(), {"document_id": "doc-1"})

        payload = _structured_payload(result[0].text)
        assert payload["truncated"] is True
        assert payload["total_chars"] == 6000 * 5 + 2 * 4
        assert payload["next_offset"] == DEFAULT_MAX_CHARS
        assert payload["offset"] == 0

    async def test_short_document_is_not_truncated(self):
        chunks = [
            DocumentChunk(
                id="c1", document_id="doc-1", content="short", chunk_index=0, token_count=1
            )
        ]
        db = _mock_db(_document(), chunks)
        with _patch_db(db):
            result = await mcp_server._handle_get_context(_key(), {"document_id": "doc-1"})

        payload = _structured_payload(result[0].text)
        assert payload["truncated"] is False
        assert payload["next_offset"] is None

    async def test_max_chars_argument_overrides_the_default(self):
        db = _mock_db(_document(), _long_chunks())
        with _patch_db(db):
            result = await mcp_server._handle_get_context(
                _key(), {"document_id": "doc-1", "max_chars": 100}
            )

        payload = _structured_payload(result[0].text)
        assert payload["truncated"] is True
        assert payload["next_offset"] == 100

    async def test_offset_argument_pages_through_the_remainder(self):
        db = _mock_db(_document(), _long_chunks())
        with _patch_db(db):
            first = await mcp_server._handle_get_context(_key(), {"document_id": "doc-1"})
        next_offset = _structured_payload(first[0].text)["next_offset"]

        with _patch_db(db):
            second = await mcp_server._handle_get_context(
                _key(), {"document_id": "doc-1", "offset": next_offset}
            )
        payload = _structured_payload(second[0].text)
        assert payload["truncated"] is False
        assert payload["offset"] == next_offset

    async def test_invalid_max_chars_falls_back_to_the_default_rather_than_erroring(self):
        """A malformed argument (agents pass free-form values) degrades to
        the safe default instead of raising -- mirrors list_documents'
        page/page_size clamping in the same module."""
        db = _mock_db(_document(), _long_chunks())
        with _patch_db(db):
            result = await mcp_server._handle_get_context(
                _key(), {"document_id": "doc-1", "max_chars": "not-a-number"}
            )

        payload = _structured_payload(result[0].text)
        assert payload["next_offset"] == DEFAULT_MAX_CHARS


class TestRestMcpParity:
    """The two surfaces must agree on where they cut a document -- not just
    that they both truncate 'somewhere'."""

    async def test_mcp_and_rest_truncate_at_the_same_boundary(self):
        from src.models.document import windowed_document_context

        chunks = _long_chunks()
        db = _mock_db(_document(), chunks)
        with _patch_db(db):
            result = await mcp_server._handle_get_context(_key(), {"document_id": "doc-1"})
        mcp_payload = _structured_payload(result[0].text)

        rest_window = windowed_document_context(chunks, offset=0, max_chars=DEFAULT_MAX_CHARS)

        assert mcp_payload["truncated"] == rest_window.truncated
        assert mcp_payload["total_chars"] == rest_window.total_chars
        assert mcp_payload["next_offset"] == rest_window.next_offset
