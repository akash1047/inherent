"""Context window builder (PM-S019)."""

from __future__ import annotations

from typing import Protocol

from src.models.document import DocumentChunk
from src.models.search import ContextChunk, SearchResult
from src.utils import get_logger

logger = get_logger(__name__)


class _ContextCapableDatabase(Protocol):
    async def get_context_chunks(
        self, workspace_id: str, ranges: list[tuple[str, int, int]]
    ) -> list[DocumentChunk]: ...


def _match_chunk_index(match: SearchResult) -> int | None:
    """Pull chunk_index out of metadata (where SearchService currently puts it)."""
    if match.metadata and "chunk_index" in match.metadata:
        try:
            return int(match.metadata["chunk_index"])
        except (TypeError, ValueError):
            return None
    return None


def _compute_ranges(matches: list[SearchResult], k: int) -> list[tuple[str, int, int]]:
    """Group matches by document_id and compute combined (lo, hi) per doc.

    Lo is clamped to 0 here; hi is left uncapped because the DB naturally
    returns only real rows.
    """
    if k <= 0:
        return []
    per_doc: dict[str, list[int]] = {}
    for m in matches:
        idx = _match_chunk_index(m)
        if idx is None:
            continue
        per_doc.setdefault(m.document_id, []).append(idx)
    ranges: list[tuple[str, int, int]] = []
    for doc_id, indexes in per_doc.items():
        lo = max(0, min(indexes) - k)
        hi = max(indexes) + k
        ranges.append((doc_id, lo, hi))
    return ranges


def _assign_windows(
    matches: list[SearchResult],
    rows: list[DocumentChunk],
    k: int,
) -> None:
    """Populate context_before / context_after on each match using fetched rows."""
    by_doc: dict[str, list[DocumentChunk]] = {}
    for row in rows:
        by_doc.setdefault(row.document_id, []).append(row)
    for doc_rows in by_doc.values():
        doc_rows.sort(key=lambda r: r.chunk_index)

    for m in matches:
        idx = _match_chunk_index(m)
        if idx is None:
            continue
        doc_rows = by_doc.get(m.document_id, [])
        before = [r for r in doc_rows if idx - k <= r.chunk_index < idx]
        after = [r for r in doc_rows if idx < r.chunk_index <= idx + k]
        m.context_before = [
            ContextChunk(
                chunk_id=r.id,
                chunk_index=r.chunk_index,
                content=r.content,
                token_count=r.token_count or 0,
            )
            for r in before
        ]
        m.context_after = [
            ContextChunk(
                chunk_id=r.id,
                chunk_index=r.chunk_index,
                content=r.content,
                token_count=r.token_count or 0,
            )
            for r in after
        ]


class ContextWindowBuilder:
    """Expands search results with neighbouring chunks via one batched PG fetch."""

    def __init__(self, database: _ContextCapableDatabase) -> None:
        self._db = database

    async def expand(
        self,
        matches: list[SearchResult],
        workspace_id: str,
        k: int,
    ) -> None:
        if not matches:
            return
        if k == 0:
            for m in matches:
                m.context_before = []
                m.context_after = []
            return
        ranges = _compute_ranges(matches, k)
        if not ranges:
            return
        try:
            rows = await self._db.get_context_chunks(workspace_id, ranges)
        except Exception as exc:
            logger.error(
                "context_window_fetch_failed",
                workspace_id=workspace_id,
                error=str(exc),
            )
            return
        _assign_windows(matches, rows, k)
