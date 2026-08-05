"""MCP workspace-boundary regression tests (#32).

The MCP server exposes ``search_documents`` and ``get_document_context``. Both
must enforce that a user can only reach workspaces / documents they are
authorised for. These tests run offline by patching ``get_database`` (and, where
needed, ``get_search_service``) at the module boundary.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# The MCP package was renamed src/mcp -> src/mcp_server so it no longer shadows
# the third-party ``mcp`` SDK under pytest's ``pythonpath = ["src"]``; these
# boundary checks now run offline (no skip).
from src.mcp_server import server as mcp_server
from src.models.api_key import APIKeyInfo
from src.models.document import Document

pytestmark = [pytest.mark.security]


def _key(user_id: str = "user-1") -> APIKeyInfo:
    return APIKeyInfo(
        key_id="key-1",
        user_id=user_id,
        workspace_id=None,
        permissions=["read", "search"],
        rate_limit=100,
        expires_at=None,
        status="active",
    )


def _scoped_key(workspace_id: str, user_id: str = "user-1") -> APIKeyInfo:
    """A workspace-scoped key (#138): bound to exactly ``workspace_id``,
    regardless of how many workspaces the owning user also owns."""
    return APIKeyInfo(
        key_id="key-scoped",
        user_id=user_id,
        workspace_id=workspace_id,
        permissions=["read", "search", "write"],
        rate_limit=100,
        expires_at=None,
        status="active",
    )


def _patch_db(mock_db: AsyncMock):
    return patch.object(mcp_server, "get_database", AsyncMock(return_value=mock_db))


@pytest.mark.asyncio
async def test_get_workspace_ids_rejects_unauthorised_workspace() -> None:
    """Requesting a specific workspace the user does not own returns an error
    and no workspace ids."""
    mock_db = AsyncMock()
    mock_db.get_user_workspace_ids = AsyncMock(return_value=["ws-owned"])
    with _patch_db(mock_db):
        ws_ids, error = await mcp_server._get_workspace_ids(_key(), "ws-foreign")
    assert ws_ids == []
    assert error is not None
    assert "don't have access" in error


@pytest.mark.asyncio
async def test_get_workspace_ids_allows_owned_workspace() -> None:
    """A workspace the user owns resolves to exactly that workspace."""
    mock_db = AsyncMock()
    mock_db.get_user_workspace_ids = AsyncMock(return_value=["ws-a", "ws-b"])
    with _patch_db(mock_db):
        ws_ids, error = await mcp_server._get_workspace_ids(_key(), "ws-b")
    assert ws_ids == ["ws-b"]
    assert error is None


@pytest.mark.asyncio
async def test_search_blocks_unauthorised_workspace_and_never_searches() -> None:
    """When a foreign workspace is requested, _handle_search returns the access
    error WITHOUT ever invoking the search service."""
    mock_db = AsyncMock()
    mock_db.get_user_workspace_ids = AsyncMock(return_value=["ws-owned"])
    mock_search = AsyncMock()

    with (
        _patch_db(mock_db),
        patch.object(mcp_server, "get_search_service", AsyncMock(return_value=mock_search)),
    ):
        result = await mcp_server._handle_search(
            _key(), {"query": "secret", "workspace_id": "ws-foreign"}
        )

    text = result[0].text
    assert "don't have access" in text
    # The search service must never be called for an unauthorised workspace.
    mock_search.search.assert_not_called()


@pytest.mark.asyncio
async def test_get_context_blocks_document_in_unauthorised_workspace() -> None:
    """get_document_context must refuse a document whose workspace the user does
    not own, and must NOT fetch its chunks."""
    foreign_doc = Document(
        id="doc-x",
        name="foreign.txt",
        workspace_id="ws-foreign",
        source_type="upload",
        mime_type="text/plain",
        size_bytes=10,
        chunk_count=1,
        status="processed",
        created_at=__import__("datetime").datetime.now(),
        updated_at=__import__("datetime").datetime.now(),
    )
    mock_db = AsyncMock()
    mock_db.get_document_by_id = AsyncMock(return_value=foreign_doc)
    mock_db.get_user_workspace_ids = AsyncMock(return_value=["ws-owned"])
    mock_db.get_document_chunks_by_doc_id = AsyncMock(return_value=[])

    with _patch_db(mock_db):
        result = await mcp_server._handle_get_context(_key(), {"document_id": "doc-x"})

    text = result[0].text
    assert "don't have access" in text
    # Must not have leaked the document body.
    mock_db.get_document_chunks_by_doc_id.assert_not_called()


# ---------------------------------------------------------------------------
# #138: workspace-scoped key binding parity with REST's _resolve_workspace.
#
# REST's _resolve_workspace (src/services/auth.py) binds a workspace-scoped
# key (APIKeyInfo.workspace_id is not None) to exactly that workspace and
# rejects any other workspace_id — even one the owning user also owns
# (see tests/security/test_workspace_isolation.py::
# test_workspace_scoped_key_cannot_cross_even_to_an_owned_workspace). MCP's
# _get_workspace_ids used to derive access purely from
# database.get_user_workspace_ids(user_id) — the user's FULL owned set —
# never consulting key_info.workspace_id at all. These tests would PASS
# against that old code (mock_db.get_user_workspace_ids returns both
# workspaces, and the old code let the scoped key reach either one), so they
# pin the regression: a scoped key requesting a workspace outside its
# binding must be rejected on MCP exactly as it is on REST.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_workspace_ids_scoped_key_cannot_cross_to_owned_workspace() -> None:
    """A workspace-scoped key must not reach a different workspace, even one
    the owning user also owns (mirrors the REST regression test)."""
    mock_db = AsyncMock()
    # The user owns BOTH ws-a and ws-b, but the key is scoped to ws-a only.
    mock_db.get_user_workspace_ids = AsyncMock(return_value=["ws-a", "ws-b"])
    with _patch_db(mock_db):
        ws_ids, error = await mcp_server._get_workspace_ids(_scoped_key("ws-a"), "ws-b")
    assert ws_ids == []
    assert error is not None
    assert "don't have access" in error


@pytest.mark.asyncio
async def test_get_workspace_ids_scoped_key_matching_request_resolves() -> None:
    """A scoped key requesting its own bound workspace still resolves fine."""
    mock_db = AsyncMock()
    mock_db.get_user_workspace_ids = AsyncMock(return_value=["ws-a", "ws-b"])
    with _patch_db(mock_db):
        ws_ids, error = await mcp_server._get_workspace_ids(_scoped_key("ws-a"), "ws-a")
    assert ws_ids == ["ws-a"]
    assert error is None


@pytest.mark.asyncio
async def test_get_workspace_ids_scoped_key_no_request_narrows_to_binding() -> None:
    """With no workspace_id argument, a scoped key must narrow to exactly its
    bound workspace — never expand to the user's full owned set (REST parity:
    _resolve_workspace never expands a scoped key's access either)."""
    mock_db = AsyncMock()
    mock_db.get_user_workspace_ids = AsyncMock(return_value=["ws-a", "ws-b"])
    with _patch_db(mock_db):
        ws_ids, error = await mcp_server._get_workspace_ids(_scoped_key("ws-a"), None)
    assert ws_ids == ["ws-a"]
    assert error is None


@pytest.mark.asyncio
async def test_search_blocks_scoped_key_from_other_owned_workspace() -> None:
    """search_documents must refuse a scoped key querying a workspace outside
    its binding, and must never invoke the search service for it."""
    mock_db = AsyncMock()
    mock_db.get_user_workspace_ids = AsyncMock(return_value=["ws-a", "ws-b"])
    mock_search = AsyncMock()

    with (
        _patch_db(mock_db),
        patch.object(mcp_server, "get_search_service", AsyncMock(return_value=mock_search)),
    ):
        result = await mcp_server._handle_search(
            _scoped_key("ws-a"), {"query": "secret", "workspace_id": "ws-b"}
        )

    text = result[0].text
    assert "don't have access" in text
    mock_search.search.assert_not_called()
