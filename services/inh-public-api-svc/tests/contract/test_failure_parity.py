"""REST ↔ MCP failure-path parity contract (#98/#99).

Both surfaces expose the same write capabilities (upload, refresh, delete),
and a dependency failure (MQ down, vector store down, DB degraded) must leave
the SAME document state and surface an error on either surface. Issues #98
and #99 exist because nothing enforced this: the REST refresh handler marked
the document failed on MQ outage while its MCP twin silently stranded it as
"pending".

This suite pins the cross-surface contract. The REST halves live in
tests/unit/test_upload_document.py (``test_mq_failure_marks_document_failed``)
and tests/unit/test_refresh_and_verify_endpoints.py
(``test_refresh_marks_failed_on_publish_error``); this file covers the MCP
halves and the not-yet-implemented recovery contracts, marked ``xfail`` with
the issue that tracks them. When a fix lands (e.g. PR #96 for #98), the test
starts XPASSing — remove the marker to lock the behavior in.

Rule of thumb (see CLAUDE.md): a state mutation followed by a publish needs a
compensating mark-failed path on EVERY surface that runs it.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from mcp.types import CallToolRequest, CallToolRequestParams

from src.main import create_app
from src.mcp_server import server as mcp_server
from src.models.api_key import APIKeyInfo
from src.models.document import Document
from src.services.auth import ResolvedAuth, _resolve_workspace, resolve_workspace_write
from src.services.database import get_database

pytestmark = pytest.mark.asyncio

WS = "ws-1"


def _write_key() -> APIKeyInfo:
    return APIKeyInfo(
        key_id="key-1",
        user_id="user-1",
        workspace_id=None,
        permissions=["read", "search", "write"],  # type: ignore[arg-type]
        rate_limit=100,
        expires_at=None,
        status="active",
    )


def _scoped_key(workspace_id: str) -> APIKeyInfo:
    """A workspace-scoped key (#138): bound to exactly ``workspace_id``."""
    return APIKeyInfo(
        key_id="key-scoped",
        user_id="user-1",
        workspace_id=workspace_id,
        permissions=["read", "search", "write"],  # type: ignore[arg-type]
        rate_limit=100,
        expires_at=None,
        status="active",
    )


def _document(document_id: str = "doc-1") -> Document:
    now = datetime.now(timezone.utc)
    return Document(
        id=document_id,
        name="report.pdf",
        workspace_id=WS,
        source_type="s3",
        mime_type="application/pdf",
        size_bytes=2048,
        chunk_count=3,
        status="processed",
        created_at=now,
        updated_at=now,
        metadata=None,
    )


def _upload_fields(document_id: str = "doc-1") -> dict:
    return {
        "document_id": document_id,
        "workspace_id": WS,
        "user_id": "user-1",
        "filename": "stored.pdf",
        "original_filename": "report.pdf",
        "content_type": "application/pdf",
        "size_bytes": 2048,
        "storage_backend": "s3",
        "storage_path": f"{WS}/abc/stored.pdf",
        "storage_bucket": "docs",
        "storage_url": "s3://docs/stored.pdf",
    }


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.validate_api_key = AsyncMock(return_value=_write_key())
    db.get_document_by_id = AsyncMock(return_value=_document())
    db.get_user_workspace_ids = AsyncMock(return_value=[WS])
    db.get_document_upload_fields = AsyncMock(return_value=_upload_fields())
    db.create_or_reset_pending_document = AsyncMock(return_value=None)
    db.mark_document_failed = AsyncMock(return_value=None)
    return db


async def _call_mcp_tool(name: str, arguments: dict, db: AsyncMock):
    """Drive a tool through the real dispatcher (auth + permission + handler)."""
    server = mcp_server.create_mcp_server()
    with patch.object(mcp_server, "get_database", AsyncMock(return_value=db)):
        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=arguments),
        )
        handler = server.request_handlers[CallToolRequest]
        result = await handler(req)
        return result.root.content


# ---------------------------------------------------------------------------
# Refresh: MQ down after the document was reset to 'pending'
# ---------------------------------------------------------------------------


class TestRefreshMqDownParity:
    """REST marks the document failed and returns 503 (covered in
    tests/unit/test_refresh_and_verify_endpoints.py). The MCP twin must do the
    equivalent: mark failed + clear error — never a permanently-pending doc."""

    async def test_mcp_refresh_mq_down_marks_document_failed(self):
        db = _mock_db()
        failing_mq = AsyncMock()
        failing_mq.publish = AsyncMock(side_effect=RuntimeError("mq down"))

        with patch("src.services.mq.get_mq_service", new=AsyncMock(return_value=failing_mq)):
            result = await _call_mcp_tool(
                "refresh_stale_source",
                {"api_key": "ink_k", "document_id": "doc-1"},
                db,
            )

        # Parity with REST: the pending reset must be compensated...
        db.mark_document_failed.assert_awaited_once()
        # ...and the caller must see a real error, not a success summary.
        assert "Error" in result[0].text

    async def test_mcp_refresh_mq_down_never_reports_success(self):
        """Even before #98 is fixed, an MQ outage must not read as success —
        this half of the contract already holds (the dispatcher catch-all
        returns an error) and must not regress while #96 is in flight."""
        db = _mock_db()
        failing_mq = AsyncMock()
        failing_mq.publish = AsyncMock(side_effect=RuntimeError("mq down"))

        with patch("src.services.mq.get_mq_service", new=AsyncMock(return_value=failing_mq)):
            result = await _call_mcp_tool(
                "refresh_stale_source",
                {"api_key": "ink_k", "document_id": "doc-1"},
                db,
            )

        assert "Error" in result[0].text
        assert "queued for re-ingestion" not in result[0].text


# ---------------------------------------------------------------------------
# Delete: vector store down before anything user-visible is removed
# ---------------------------------------------------------------------------


class TestDeleteVectorStoreDownParity:
    """REST returns 503 with the document intact (covered in
    tests/unit/test_delete_document.py). The MCP twin must be equivalent:
    error text, no database delete, operation retryable."""

    async def test_mcp_delete_vector_store_down_leaves_document_intact(self):
        db = _mock_db()
        db.delete_document = AsyncMock()
        failing_search = AsyncMock()
        failing_search.delete_document_vectors = AsyncMock(
            side_effect=RuntimeError("weaviate down")
        )

        with patch(
            "src.services.deletion.get_search_service",
            new=AsyncMock(return_value=failing_search),
        ):
            result = await _call_mcp_tool(
                "delete_document",
                {"api_key": "ink_k", "document_id": "doc-1"},
                db,
            )

        assert "Error" in result[0].text
        db.delete_document.assert_not_awaited()


# ---------------------------------------------------------------------------
# Upload: the compensating mark itself fails (#99)
# ---------------------------------------------------------------------------


class TestUploadDoubleFailureRecovery:
    """When MQ publish fails AND mark_document_failed also fails, the document
    is orphaned: DB says 'pending', the response says 'failed', and nothing can
    reconcile them. #99: the mark is retried with backoff; exhaustion emits a
    CRITICAL log + document_compensation_exhausted_total so the divergence is
    never silent (see src/services/compensation.py)."""

    async def test_upload_mark_failed_failure_is_retried(self):
        key = _write_key()
        db = _mock_db()
        db.get_document_id_by_content_hash = AsyncMock(return_value=None)
        db.get_document_id_by_filename = AsyncMock(return_value=None)
        db.mark_document_failed = AsyncMock(side_effect=RuntimeError("db degraded"))

        storage = MagicMock()
        storage.generate_key.return_value = f"{WS}/fake-uuid/test.txt"
        storage.upload_file = AsyncMock(return_value=f"{WS}/fake-uuid/test.txt")
        storage.build_storage_url.return_value = f"s3://docs/{WS}/fake-uuid/test.txt"
        storage._bucket = "docs"
        failing_mq = AsyncMock()
        failing_mq.publish = AsyncMock(side_effect=RuntimeError("mq down"))

        application = create_app()
        application.dependency_overrides[resolve_workspace_write] = lambda: ResolvedAuth(
            key_info=key, workspace_id=WS
        )
        application.dependency_overrides[get_database] = lambda: db
        try:
            with (
                # Upload storage/MQ acquisition lives in the shared intake
                # pipeline since #87 — patch there, not the REST module.
                patch("src.services.document_intake.get_storage_service", return_value=storage),
                patch(
                    "src.services.document_intake.get_mq_service",
                    new_callable=AsyncMock,
                    return_value=failing_mq,
                ),
            ):
                transport = ASGITransport(app=application)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    response = await ac.post(
                        "/v1/documents",
                        headers={"X-API-Key": "ink_test_key"},
                        files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
                    )
        finally:
            application.dependency_overrides.clear()

        # The response half of the contract already holds: never claim success.
        assert response.json()["status"] == "failed"
        # The recovery half is the #99 ask: the failed mark must be retried so
        # a transient DB blip can't orphan the row as 'pending'.
        assert db.mark_document_failed.await_count >= 2


# ---------------------------------------------------------------------------
# Refresh: the compensating mark itself fails — both surfaces (#99 sweep)
# ---------------------------------------------------------------------------


class TestRefreshDoubleFailureRecoveryParity:
    """The #99 orphan exists on every compensation site, not just upload: the
    refresh handlers (REST and MCP) also mark the pending reset failed when MQ
    is down, and that mark can itself fail. Both surfaces must retry the mark
    (same helper, same contract) so no surface can silently strand a document
    as 'pending'."""

    async def test_rest_refresh_mark_failed_failure_is_retried(self):
        key = _write_key()
        db = _mock_db()
        db.mark_document_failed = AsyncMock(side_effect=RuntimeError("db degraded"))
        failing_mq = AsyncMock()
        failing_mq.publish = AsyncMock(side_effect=RuntimeError("mq down"))

        application = create_app()
        application.dependency_overrides[resolve_workspace_write] = lambda: ResolvedAuth(
            key_info=key, workspace_id=WS
        )
        application.dependency_overrides[get_database] = lambda: db
        try:
            with patch(
                "src.api.v1.documents.get_mq_service",
                new_callable=AsyncMock,
                return_value=failing_mq,
            ):
                transport = ASGITransport(app=application)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    response = await ac.post(
                        "/v1/documents/doc-1/refresh",
                        headers={"X-API-Key": "ink_test_key"},
                    )
        finally:
            application.dependency_overrides.clear()

        # Response half: the caller sees a real error, never success.
        assert response.status_code == 503
        # Recovery half: the failed mark is retried, not swallowed.
        assert db.mark_document_failed.await_count >= 2

    async def test_mcp_refresh_mark_failed_failure_is_retried(self):
        db = _mock_db()
        db.mark_document_failed = AsyncMock(side_effect=RuntimeError("db degraded"))
        failing_mq = AsyncMock()
        failing_mq.publish = AsyncMock(side_effect=RuntimeError("mq down"))

        with patch("src.services.mq.get_mq_service", new=AsyncMock(return_value=failing_mq)):
            result = await _call_mcp_tool(
                "refresh_stale_source",
                {"api_key": "ink_k", "document_id": "doc-1"},
                db,
            )

        # Parity with REST: error surfaced AND the mark retried.
        assert "Error" in result[0].text
        assert db.mark_document_failed.await_count >= 2


# ---------------------------------------------------------------------------
# Workspace scoping: a workspace-scoped key must bind identically on REST and
# MCP (#138)
# ---------------------------------------------------------------------------


class TestWorkspaceScopeParity:
    """REST's ``_resolve_workspace`` (src/services/auth.py) binds a
    workspace-scoped API key (``APIKeyInfo.workspace_id is not None``) to
    exactly that workspace and 403s a request for any other workspace — even
    one the owning user also owns (tests/security/test_workspace_isolation.py
    ::test_workspace_scoped_key_cannot_cross_even_to_an_owned_workspace).

    MCP's ``_get_workspace_ids`` had a SEPARATE implementation of this rule
    that only checked ``database.get_user_workspace_ids`` — the user's FULL
    owned set — and never consulted ``key_info.workspace_id`` at all. So a
    scoped key's MCP calls could reach any workspace its owner owned, while
    the identical REST request was rejected. This class pins both halves of
    the contract so the two surfaces cannot drift again: same key, same
    owned-workspace set, same foreign request, same rejection.
    """

    async def test_rest_scoped_key_rejects_other_owned_workspace(self):
        key = _scoped_key("ws-a")
        mock_db = AsyncMock()
        # The user owns BOTH ws-a and ws-b; the key is scoped to ws-a only.
        mock_db.get_user_workspace_ids = AsyncMock(return_value=["ws-a", "ws-b"])
        with patch("src.services.auth.get_database", AsyncMock(return_value=mock_db)):
            with pytest.raises(HTTPException) as exc_info:
                await _resolve_workspace(key, "ws-b", required=False)
        assert exc_info.value.status_code == 403

    async def test_mcp_scoped_key_rejects_other_owned_workspace(self):
        """MCP twin of the REST test above: identical key and owned set, the
        same foreign workspace requested through a real tool call — must also
        be rejected, not silently served."""
        key = _scoped_key("ws-a")
        db = _mock_db()
        db.validate_api_key = AsyncMock(return_value=key)
        db.get_user_workspace_ids = AsyncMock(return_value=["ws-a", "ws-b"])

        result = await _call_mcp_tool(
            "list_documents", {"api_key": "ink_k", "workspace_id": "ws-b"}, db
        )

        text = result[0].text
        assert "Error" in text
        assert "don't have access" in text
        # The foreign workspace must never be queried.
        db.get_documents.assert_not_awaited()

    async def test_mcp_scoped_key_with_no_workspace_arg_narrows_to_binding(self):
        """Parity with REST's other half: omitting workspace_id must resolve
        to exactly the key's bound workspace, never expand to the user's full
        owned set (REST's _resolve_workspace never expands a scoped key's
        access either)."""
        key = _scoped_key("ws-a")
        db = _mock_db()
        db.validate_api_key = AsyncMock(return_value=key)
        db.get_user_workspace_ids = AsyncMock(return_value=["ws-a", "ws-b"])
        db.get_documents_multi_workspace = AsyncMock(return_value=([], 0))

        await _call_mcp_tool("list_documents", {"api_key": "ink_k"}, db)

        # Only the key's bound workspace was queried — ws-b was never touched.
        db.get_documents_multi_workspace.assert_awaited_once_with(["ws-a"], 1, 20)
