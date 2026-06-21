"""Unit tests for ContextWindowBuilder (PM-S019)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.models.document import DocumentChunk
from src.models.search import SearchResult
from src.services.context_window import ContextWindowBuilder


@dataclass
class _FakeDB:
    """Minimal stub exposing only get_context_chunks()."""

    rows: list[DocumentChunk]
    raise_exc: Exception | None = None
    calls: list[tuple[str, str, list[tuple[str, int, int]]]] = field(default_factory=list)

    async def get_context_chunks(
        self, workspace_id: str, user_id: str, ranges: list[tuple[str, int, int]]
    ) -> list[DocumentChunk]:
        self.calls.append((workspace_id, user_id, list(ranges)))
        if self.raise_exc is not None:
            raise self.raise_exc
        return list(self.rows)


def _chunk(chunk_id: str, doc: str, idx: int, tc: int = 100) -> DocumentChunk:
    return DocumentChunk(
        id=chunk_id,
        document_id=doc,
        content=f"content-{doc}-{idx}",
        chunk_index=idx,
        token_count=tc,
    )


def _match(chunk_id: str, doc: str, idx: int) -> SearchResult:
    # metadata carries chunk_index; this is what search currently populates
    return SearchResult(
        chunk_id=chunk_id,
        document_id=doc,
        document_name=f"{doc}.md",
        content="match",
        score=0.9,
        metadata={"chunk_index": idx},
    )


@pytest.mark.asyncio
async def test_empty_matches_returns_empty() -> None:
    db = _FakeDB(rows=[])
    builder = ContextWindowBuilder(db)
    await builder.expand(matches=[], workspace_id="ws1", user_id="user1", k=2)
    assert db.calls == []


@pytest.mark.asyncio
async def test_single_match_k2_middle_of_doc() -> None:
    # Match at chunk 5 in a 10-chunk doc with k=2 → before [3,4], after [6,7]
    all_rows = [_chunk(f"ck{i}", "doc-a", i) for i in range(10)]
    db = _FakeDB(rows=all_rows)
    m = _match("ck5", "doc-a", 5)
    await ContextWindowBuilder(db).expand([m], "ws1", "user1", k=2)

    assert m.context_before is not None
    assert [c.chunk_index for c in m.context_before] == [3, 4]
    assert m.context_after is not None
    assert [c.chunk_index for c in m.context_after] == [6, 7]

    # Assert it was ONE query, ranging 3..7 for doc-a
    assert len(db.calls) == 1
    _ws, _uid, ranges = db.calls[0]
    assert ranges == [("doc-a", 3, 7)]


@pytest.mark.asyncio
async def test_match_at_first_chunk_clamps_before_to_empty() -> None:
    all_rows = [_chunk(f"ck{i}", "doc-a", i) for i in range(3)]
    db = _FakeDB(rows=all_rows)
    m = _match("ck0", "doc-a", 0)
    await ContextWindowBuilder(db).expand([m], "ws1", "user1", k=2)

    assert m.context_before == []
    assert m.context_after is not None
    assert [c.chunk_index for c in m.context_after] == [1, 2]


@pytest.mark.asyncio
async def test_match_at_last_chunk_clamps_after_to_empty() -> None:
    all_rows = [_chunk(f"ck{i}", "doc-a", i) for i in range(5)]
    db = _FakeDB(rows=all_rows)
    m = _match("ck4", "doc-a", 4)
    await ContextWindowBuilder(db).expand([m], "ws1", "user1", k=2)

    assert m.context_before is not None
    assert [c.chunk_index for c in m.context_before] == [2, 3]
    assert m.context_after == []


@pytest.mark.asyncio
async def test_two_matches_same_doc_independent_windows() -> None:
    all_rows = [_chunk(f"ck{i}", "doc-a", i) for i in range(10)]
    db = _FakeDB(rows=all_rows)
    m1 = _match("ck3", "doc-a", 3)
    m2 = _match("ck5", "doc-a", 5)
    await ContextWindowBuilder(db).expand([m1, m2], "ws1", "user1", k=2)

    assert [c.chunk_index for c in (m1.context_before or [])] == [1, 2]
    assert [c.chunk_index for c in (m1.context_after or [])] == [4, 5]
    assert [c.chunk_index for c in (m2.context_before or [])] == [3, 4]
    assert [c.chunk_index for c in (m2.context_after or [])] == [6, 7]
    # Overlap is allowed — chunk 4 appears in m1.after and m2.before
    assert len(db.calls) == 1


@pytest.mark.asyncio
async def test_two_matches_across_docs_single_batched_query() -> None:
    rows = [_chunk(f"a{i}", "doc-a", i) for i in range(5)] + [
        _chunk(f"b{i}", "doc-b", i) for i in range(5)
    ]
    db = _FakeDB(rows=rows)
    m1 = _match("a2", "doc-a", 2)
    m2 = _match("b3", "doc-b", 3)
    await ContextWindowBuilder(db).expand([m1, m2], "ws1", "user1", k=1)

    assert len(db.calls) == 1
    _ws, _uid, ranges = db.calls[0]
    assert sorted(ranges) == [("doc-a", 1, 3), ("doc-b", 2, 4)]


@pytest.mark.asyncio
async def test_k_zero_returns_empty_arrays_not_null() -> None:
    rows = [_chunk("ck5", "doc-a", 5)]
    db = _FakeDB(rows=rows)
    m = _match("ck5", "doc-a", 5)
    await ContextWindowBuilder(db).expand([m], "ws1", "user1", k=0)
    assert m.context_before == []
    assert m.context_after == []
    # With k=0 we can skip the DB call entirely — no ranges needed
    assert db.calls == []


@pytest.mark.asyncio
async def test_missing_token_count_treated_as_zero() -> None:
    rows = [
        _chunk("ck4", "doc-a", 4, tc=0),  # token_count=0 simulates NULL after coercion
        _chunk("ck5", "doc-a", 5, tc=50),
        _chunk("ck6", "doc-a", 6, tc=0),
    ]
    db = _FakeDB(rows=rows)
    m = _match("ck5", "doc-a", 5)
    await ContextWindowBuilder(db).expand([m], "ws1", "user1", k=1)
    assert m.context_before is not None and m.context_before[0].token_count == 0
    assert m.context_after is not None and m.context_after[0].token_count == 0


@pytest.mark.asyncio
async def test_db_failure_returns_response_without_context_not_raises() -> None:
    db = _FakeDB(rows=[], raise_exc=RuntimeError("pg down"))
    m = _match("ck5", "doc-a", 5)
    # Must NOT raise
    await ContextWindowBuilder(db).expand([m], "ws1", "user1", k=2)
    # Match keeps default None (not partial)
    assert m.context_before is None
    assert m.context_after is None
