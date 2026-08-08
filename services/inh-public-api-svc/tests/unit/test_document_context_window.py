"""Unit tests for windowed_document_context (#219).

Pure-function tests for the shared bounding computation REST
(GET /v1/chunks/{document_id}/context) and MCP (get_document_context) both
call, so the two surfaces cannot silently disagree on the default bound or
the chunk-selection rule.
"""

from src.models.document import (
    DEFAULT_MAX_CHARS,
    MAX_MAX_CHARS,
    DocumentChunk,
    windowed_document_context,
)


def _chunk(chunk_id: str, content: str, index: int) -> DocumentChunk:
    return DocumentChunk(
        id=chunk_id,
        document_id="doc-001",
        content=content,
        chunk_index=index,
        token_count=len(content.split()),
        metadata=None,
    )


class TestWindowedDocumentContext:
    def test_short_document_is_not_truncated(self):
        """A document whose combined text fits under max_chars is returned
        whole: truncated=False, next_offset=None, every chunk present."""
        chunks = [_chunk("c1", "first chunk", 0), _chunk("c2", "second chunk", 1)]
        window = windowed_document_context(chunks, offset=0, max_chars=DEFAULT_MAX_CHARS)

        assert window.full_text == "first chunk\n\nsecond chunk"
        assert window.truncated is False
        assert window.next_offset is None
        assert window.total_chars == len("first chunk\n\nsecond chunk")
        assert [c.id for c in window.chunks] == ["c1", "c2"]

    def test_default_bound_truncates_a_long_document_and_bounds_chunks_too(self):
        """The core #219 regression: a document whose combined text exceeds
        max_chars is truncated, AND the returned chunk list is bounded to the
        SAME window -- not every chunk in the document. 5 chunks of 6000
        chars each (30,008 chars joined) against DEFAULT_MAX_CHARS=20,000
        must drop the 5th chunk (which starts at 24,008, past the window)."""
        chunks = [_chunk(f"c{i}", "x" * 6000, i) for i in range(5)]
        window = windowed_document_context(chunks, offset=0, max_chars=DEFAULT_MAX_CHARS)

        assert window.total_chars == 6000 * 5 + 2 * 4  # 4 "\n\n" separators
        assert window.truncated is True
        assert window.next_offset == DEFAULT_MAX_CHARS
        # full_text is capped at max_chars plus the (small) truncation marker.
        marker_overhead = len(window.full_text) - DEFAULT_MAX_CHARS
        assert 0 < marker_overhead < 100
        assert "truncated" in window.full_text
        # Only the chunks overlapping [0, 20000) come back -- chunk 4 starts
        # at 24,008, entirely past the window, so it must be dropped from
        # `chunks` exactly as it is dropped from `full_text`.
        assert [c.id for c in window.chunks] == ["c0", "c1", "c2", "c3"]

    def test_offset_pages_into_the_remainder(self):
        """Requesting next_offset from a truncated page returns the rest of
        the document, ending non-truncated."""
        chunks = [_chunk(f"c{i}", "x" * 6000, i) for i in range(5)]
        first = windowed_document_context(chunks, offset=0, max_chars=DEFAULT_MAX_CHARS)
        second = windowed_document_context(
            chunks, offset=first.next_offset, max_chars=DEFAULT_MAX_CHARS
        )

        assert second.truncated is False
        assert second.next_offset is None
        # The remainder picks up exactly where the first page's window ended.
        joined = "\n\n".join(c.content for c in chunks)
        assert second.full_text == joined[first.next_offset :]
        # Chunk 3 straddles the page boundary (starts before offset 20000,
        # ends after it) so it legitimately appears on both pages -- a chunk
        # is never split mid-content.
        assert "c3" in {c.id for c in first.chunks}
        assert "c3" in {c.id for c in second.chunks}
        assert "c4" in {c.id for c in second.chunks}

    def test_offset_past_end_returns_empty_untruncated_slice(self):
        """An offset at or beyond total_chars is a valid 'nothing left to
        page' answer, not an error."""
        chunks = [_chunk("c1", "short", 0)]
        window = windowed_document_context(chunks, offset=999, max_chars=DEFAULT_MAX_CHARS)

        assert window.full_text == ""
        assert window.truncated is False
        assert window.next_offset is None
        assert window.chunks == []

    def test_no_chunks_returns_empty_window(self):
        window = windowed_document_context([], offset=0, max_chars=DEFAULT_MAX_CHARS)

        assert window.full_text == ""
        assert window.total_chars == 0
        assert window.truncated is False
        assert window.chunks == []

    def test_max_max_chars_constant_is_larger_than_default(self):
        """Sanity check on the bound relationship the API layer relies on
        for its Query(ge=..., le=...) validation."""
        assert MAX_MAX_CHARS > DEFAULT_MAX_CHARS
