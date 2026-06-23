"""Context-window authorization regression tests (#32, guarding #41).

The P0 bug: context expansion fetched neighbour chunks scoped to ``workspace_id``
only. In a workspace shared by multiple Weaviate tenants, that could return
another user's neighbour chunks. The fix threads ``user_id`` into
``get_context_chunks`` and filters by it (via a join to
``processed_documents.user_id``).

These tests assert, offline:
1. ``ContextWindowBuilder.expand`` calls ``get_context_chunks`` WITH the
   requesting ``user_id``.
2. ``DatabaseService.get_context_chunks`` binds the ``user_id`` into the query
   args (so the SQL is actually user-scoped, not just signature-scoped).
3. A neighbour belonging to another user is NOT surfaced when the DB (correctly)
   filters it out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.document import DocumentChunk
from src.models.search import SearchResult
from src.services.context_window import ContextWindowBuilder
from src.services.database import DatabaseService

pytestmark = pytest.mark.security


@dataclass
class _RecordingDB:
    """Stub DB that records the (workspace_id, user_id, ranges) it was called with."""

    rows: list[DocumentChunk]
    calls: list[tuple[str, str, list[tuple[str, int, int]]]] = field(default_factory=list)

    async def get_context_chunks(
        self, workspace_id: str, user_id: str, ranges: list[tuple[str, int, int]]
    ) -> list[DocumentChunk]:
        self.calls.append((workspace_id, user_id, list(ranges)))
        return list(self.rows)


def _match(chunk_id: str, doc: str, idx: int) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        document_id=doc,
        document_name=f"{doc}.md",
        content="match",
        score=0.9,
        metadata={"chunk_index": idx},
    )


def _chunk(chunk_id: str, doc: str, idx: int) -> DocumentChunk:
    return DocumentChunk(
        id=chunk_id,
        document_id=doc,
        content=f"content-{doc}-{idx}",
        chunk_index=idx,
        token_count=10,
    )


@pytest.mark.asyncio
async def test_expand_passes_user_id_to_get_context_chunks() -> None:
    """The builder must forward the requesting user_id into the DB fetch."""
    db = _RecordingDB(rows=[_chunk("c4", "doc-a", 4), _chunk("c6", "doc-a", 6)])
    m = _match("c5", "doc-a", 5)
    await ContextWindowBuilder(db).expand([m], workspace_id="ws-shared", user_id="user-1", k=1)

    assert len(db.calls) == 1
    workspace_id, user_id, _ranges = db.calls[0]
    assert workspace_id == "ws-shared"
    assert user_id == "user-1"


@pytest.mark.asyncio
async def test_get_context_chunks_binds_user_id_into_query_args() -> None:
    """The SQL layer must bind user_id (and workspace_id) into the query params,
    proving the neighbour fetch is genuinely user-scoped."""
    captured: dict[str, object] = {}

    class _FakeResult:
        def fetchall(self):
            return []

    mock_session = AsyncMock()

    async def _execute(query, params):
        captured["params"] = params
        return _FakeResult()

    mock_session.execute = _execute

    # session() is an async context manager yielding mock_session.
    db = DatabaseService.__new__(DatabaseService)

    class _SessionCtx:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, *args):
            return False

    db.session = MagicMock(return_value=_SessionCtx())  # type: ignore[method-assign]

    await db.get_context_chunks(
        workspace_id="ws-shared",
        user_id="user-1",
        ranges=[("doc-a", 3, 7)],
    )

    params = captured["params"]
    assert isinstance(params, dict)
    assert params.get("workspace_id") == "ws-shared"
    # The critical assertion: user scoping is present in the bound args (#41).
    assert params.get("user_id") == "user-1"


@pytest.mark.asyncio
async def test_neighbour_owned_by_other_user_is_not_returned() -> None:
    """When the DB filters by user_id, a foreign user's neighbour never reaches
    the result. We model the DB returning ONLY the requesting user's rows; the
    builder must not surface a chunk it never received."""
    # doc-a chunk 5 is the match; chunk 6 belongs to the requesting user,
    # chunk 4 (the foreign neighbour) is correctly withheld by the user-scoped DB.
    db = _RecordingDB(rows=[_chunk("c6", "doc-a", 6)])
    m = _match("c5", "doc-a", 5)
    await ContextWindowBuilder(db).expand([m], workspace_id="ws-shared", user_id="user-1", k=1)

    # The foreign neighbour (chunk 4) is absent from context_before.
    before_ids = [c.chunk_id for c in (m.context_before or [])]
    after_ids = [c.chunk_id for c in (m.context_after or [])]
    assert "c4" not in before_ids
    assert "c4" not in after_ids
    # The requesting user's own neighbour is present.
    assert after_ids == ["c6"]
    assert before_ids == []
