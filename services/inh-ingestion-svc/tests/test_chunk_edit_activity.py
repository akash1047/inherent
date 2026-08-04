"""Chunk-edit activity must keep provenance consistent (#9) and must not
swallow failures on the Weaviate side (#137).

Editing a chunk previously updated only ``content`` and a naive word-count
``token_count``, leaving the stored ``content_hash`` (sha256 of the content,
the #41 verifiable-evidence hash) stale — so any re-hash check would flag a
legitimately edited chunk as tampered. The edit must recompute ``content_hash``
and use the same ``estimate_tokens`` as the store path.

The Weaviate-side activity had a parallel defect: ``update_chunk_weaviate``
caught every exception and returned ``False`` instead of re-raising. A
Temporal activity that *returns* (even ``False``) is a *completed* activity
to the SDK -- the workflow's RetryPolicy never engages, and (before the
matching workflow fix) the workflow's bare ``except: pass`` then reported the
edit as fully successful even though the vector never updated. These tests
pin the activity-level half of that fix: given a Weaviate failure, the
activity must propagate it, not swallow it.
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.temporal.activities.chunk import estimate_tokens
from src.temporal.activities.chunk_edit import (
    record_chunk_edit_weaviate_failure,
    update_chunk_postgresql,
    update_chunk_weaviate,
)
from src.temporal.models import ChunkEditInput, ChunkEditWeaviateFailureInput

# ---------------------------------------------------------------------------
# Override conftest autouse fixtures -- these tests don't touch a real
# PostgreSQL; every DB/Weaviate dependency is mocked via shared_services.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def cleanup_test_data():
    yield


@pytest.fixture()
def db_service():
    yield None


@pytest.mark.asyncio
async def test_update_recomputes_content_hash_and_token_count():
    content = "The quick brown fox was edited into something longer."

    conn = MagicMock()
    result = MagicMock()
    result.rowcount = 1
    conn.execute.return_value = result

    cm = MagicMock()
    cm.__enter__.return_value = conn
    cm.__exit__.return_value = False
    db = MagicMock()
    db.engine.connect.return_value = cm

    with patch("src.temporal.shared_services.get_db_service", return_value=db):
        await update_chunk_postgresql(
            ChunkEditInput(document_id="doc-1", chunk_index=0, content=content)
        )

    sql, params = conn.execute.call_args.args
    assert "content_hash" in str(sql), "UPDATE must set content_hash"
    assert params["content"] == content
    assert params["content_hash"] == hashlib.sha256(content.encode("utf-8")).hexdigest()
    # token_count must match the store-path estimator, not a naive word split.
    assert params["token_count"] == estimate_tokens(content)


class TestUpdateChunkWeaviateReraises:
    """#137: update_chunk_weaviate must propagate failures, never swallow."""

    @pytest.mark.asyncio
    async def test_weaviate_update_failure_is_reraised_not_swallowed(self):
        """A test against the OLD code fails here: the old activity caught
        the exception and `return False`d, so `pytest.raises` would never
        fire."""
        mock_weaviate = MagicMock()
        mock_weaviate.is_connected.return_value = True
        mock_weaviate.update_chunk = AsyncMock(side_effect=ConnectionError("TEI down"))

        with patch(
            "src.temporal.shared_services.get_weaviate_service",
            return_value=mock_weaviate,
        ):
            with pytest.raises(ConnectionError, match="TEI down"):
                await update_chunk_weaviate(
                    ChunkEditInput(
                        document_id="doc-1",
                        chunk_index=0,
                        content="new text",
                        workspace_id="ws1",
                        user_id="user1",
                    )
                )

    @pytest.mark.asyncio
    async def test_weaviate_not_connected_raises_instead_of_returning_false(self):
        """A disconnected Weaviate must also raise (so the RetryPolicy gets
        a shot at a transient reconnect window), matching store_in_weaviate's
        existing behavior for the same condition."""
        with patch(
            "src.temporal.shared_services.get_weaviate_service",
            return_value=None,
        ):
            with pytest.raises(RuntimeError, match="Weaviate not connected"):
                await update_chunk_weaviate(
                    ChunkEditInput(
                        document_id="doc-1",
                        chunk_index=0,
                        content="new text",
                        workspace_id="ws1",
                        user_id="user1",
                    )
                )

    @pytest.mark.asyncio
    async def test_weaviate_update_success_returns_true(self):
        mock_weaviate = MagicMock()
        mock_weaviate.is_connected.return_value = True
        mock_weaviate.update_chunk = AsyncMock(return_value=None)

        with patch(
            "src.temporal.shared_services.get_weaviate_service",
            return_value=mock_weaviate,
        ):
            result = await update_chunk_weaviate(
                ChunkEditInput(
                    document_id="doc-1",
                    chunk_index=0,
                    content="new text",
                    workspace_id="ws1",
                    user_id="user1",
                )
            )

        assert result is True


class TestRecordChunkEditWeaviateFailure:
    """#137 compensating mark-failed: durable, never masks the real error."""

    @pytest.mark.asyncio
    async def test_records_ingestion_event_with_failure_details(self):
        mock_db = MagicMock()
        mock_db.record_ingestion_event = AsyncMock(return_value=1)

        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            result = await record_chunk_edit_weaviate_failure(
                ChunkEditWeaviateFailureInput(
                    workflow_id="chunk-edit-doc1-0",
                    document_id="doc1",
                    workspace_id="ws1",
                    chunk_index=0,
                    error_message="TEI sidecar unreachable",
                )
            )

        assert result is True
        mock_db.record_ingestion_event.assert_called_once_with(
            workflow_run_id="chunk-edit-doc1-0",
            document_id="doc1",
            workspace_id="ws1",
            event_type="chunk_edit_weaviate",
            status="failed",
            metadata={"chunk_index": 0, "error": "TEI sidecar unreachable"},
        )

    @pytest.mark.asyncio
    async def test_never_raises_even_when_db_write_fails(self):
        """This activity's own failure must never mask the real Weaviate
        error the workflow is about to return -- it swallows and returns
        False instead of raising."""
        mock_db = MagicMock()
        mock_db.record_ingestion_event = AsyncMock(side_effect=RuntimeError("DB down"))

        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            result = await record_chunk_edit_weaviate_failure(
                ChunkEditWeaviateFailureInput(
                    workflow_id="chunk-edit-doc1-0",
                    document_id="doc1",
                    workspace_id="ws1",
                    chunk_index=0,
                    error_message="TEI sidecar unreachable",
                )
            )

        assert result is False
