"""Format-aware chunking driven by the registry's `chunking_hint` (#129).

Before this change, `chunk_text` resolved its strategy purely from config —
never from the document's format — so a 10k-row XLSX and a one-page memo were
split by the identical positional token-window rule. The result: a chunk
retrieved on its own carried no column header, no sheet name, no sender, no
subject — nothing that lets an agent interpret or cite it without a second
lookup. See the #129 issue body for the measured baseline (669 XLSX chunks,
exactly one with the header row) this file's tests replace.

Precedence under test (per the #129 issue's proposed contract):
    per-document override > registry `chunking_hint` > global config.

Each hint's strategy is exercised directly (offset-correctness, adversarial
shapes) AND through the full `_chunk_text_inner` dispatch (precedence,
`metadata.chunking_strategy` attribution, backward compatibility when no
`content_type` is supplied at all).
"""

from __future__ import annotations

import asyncio

import pytest

from src.config.settings import Settings
from src.temporal.activities import chunk as chunk_mod
from src.temporal.activities.chunk import (
    _chunk_by_rows,
    _chunk_by_sections,
    _chunk_prose,
    _chunk_text_inner,
    _detect_header_block,
)
from src.temporal.models import ChunkTextInput


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """No-op override of the package-level DB-dependent autouse fixture.

    The package ``tests/conftest.py`` defines an autouse ``cleanup_test_data``
    that depends on ``db_service`` and skips when PostgreSQL is unavailable.
    These tests are fully mocked/offline, same pattern as
    ``tests/test_chunking_config.py``.
    """
    yield


def _normalize(s: str) -> str:
    return " ".join(s.split())


# ---------------------------------------------------------------------------
# Shared shapes mirroring the real extractors (extract.py) so these tests
# exercise the actual text shape a chunker will see, not an idealized one.
# ---------------------------------------------------------------------------


def _xlsx_shaped_text(num_rows: int = 40, num_cols: int = 5) -> str:
    """Mirrors `_extract_xlsx_text`'s output: a "## Sheet: <name>" heading
    followed by pipe-delimited rows, header row first."""
    header = " | ".join(f"col{i}" for i in range(num_cols))
    rows = [header]
    for r in range(num_rows):
        rows.append(" | ".join(f"r{r}c{i}" for i in range(num_cols)))
    return "## Sheet: Data\n" + "\n".join(rows)


def _csv_shaped_text(num_rows: int = 40, num_cols: int = 5) -> str:
    """Mirrors a plain CSV `text_passthrough` extraction: header row first,
    no sheet heading (CSV has no sheet concept)."""
    header = ",".join(f"col{i}" for i in range(num_cols))
    rows = [header]
    for r in range(num_rows):
        rows.append(",".join(f"r{r}c{i}" for i in range(num_cols)))
    return "\n".join(rows)


def _pptx_shaped_text(num_slides: int = 20) -> str:
    """Mirrors `_extract_pptx_text`'s output: "## Slide N: Title" headings
    with body lines under each."""
    slides = []
    for i in range(1, num_slides + 1):
        slides.append(f"## Slide {i}: Point {i}\nBody line one for slide {i}.\nBody line two.")
    return "\n\n".join(slides)


def _eml_shaped_text() -> str:
    """Mirrors `_extract_eml_text`'s output: header block, blank line, then
    a long enough body to require multiple sentence chunks."""
    headers = (
        "From: alice@example.com\n"
        "To: bob@example.com\n"
        "Subject: Q3 numbers\n"
        "Date: Mon, 1 Jun 2026 10:00:00 +0000"
    )
    body = " ".join(f"This is sentence number {i} of the email body." for i in range(40))
    return f"{headers}\n\n{body}"


# ---------------------------------------------------------------------------
# _chunk_by_rows (tabular hint: CSV, XLSX)
# ---------------------------------------------------------------------------


class TestChunkByRows:
    def test_offsets_map_to_source(self):
        text = _csv_shaped_text(num_rows=30)
        chunks = _chunk_by_rows(text, "doc", max_size=200)
        assert len(chunks) >= 2
        for c in chunks:
            span = text[c.start_char : c.end_char]
            # Relaxed invariant vs. test_chunk_offsets.py's strict equality:
            # injected header/sheet context is NOT part of the source span,
            # so the source slice is a SUBSTRING of the (larger) content, not
            # equal to it. The real body text itself still matches exactly.
            assert _normalize(span) in _normalize(c.content)

    def test_every_chunk_carries_the_header_row_csv(self):
        text = _csv_shaped_text(num_rows=50, num_cols=5)
        chunks = _chunk_by_rows(text, "doc", max_size=150)
        assert len(chunks) > 3, "test is only meaningful if it forces multiple chunks"
        header = "col0,col1,col2,col3,col4"
        for c in chunks:
            assert header in c.content, f"chunk missing header row: {c.content!r}"

    def test_every_chunk_carries_sheet_heading_and_header_row_xlsx(self):
        text = _xlsx_shaped_text(num_rows=60, num_cols=5)
        chunks = _chunk_by_rows(text, "doc", max_size=150)
        assert len(chunks) > 3
        for c in chunks:
            assert "## Sheet: Data" in c.content
            assert "col0 | col1 | col2 | col3 | col4" in c.content

    def test_oversized_single_row_is_sliced_not_dropped(self):
        # A row with 200 columns (adversarial case from the #129 brief) —
        # one row alone exceeds max_chunk_size.
        header = " | ".join(f"col{i}" for i in range(200))
        wide_row = " | ".join(f"v{i}" for i in range(200))
        text = f"## Sheet: Wide\n{header}\n{wide_row}"
        chunks = _chunk_by_rows(text, "doc", max_size=100)
        assert len(chunks) >= 2, "the oversized row must be split, not silently truncated"
        # No chunk may blow far past the budget (allow the injected header on top).
        for c in chunks:
            assert len(c.content) <= 100 + 600
        # The oversized row's own text must be fully recoverable by
        # concatenating the slices in order (nothing dropped).
        rebuilt = "".join(
            text[c.start_char : c.end_char]
            for c in sorted(chunks, key=lambda c: c.start_char)
            if c.start_char >= len(f"## Sheet: Wide\n{header}\n")
        )
        assert rebuilt == wide_row

    def test_empty_text_produces_no_chunks(self):
        assert _chunk_by_rows("", "doc", max_size=100) == []


# ---------------------------------------------------------------------------
# _chunk_by_sections (structured hint: PPTX, JSON)
# ---------------------------------------------------------------------------


class TestChunkBySections:
    def test_offsets_map_to_source(self):
        text = _pptx_shaped_text(num_slides=10)
        chunks = _chunk_by_sections(text, "doc", max_size=80, overlap=0)
        assert len(chunks) >= 2
        for c in chunks:
            span = text[c.start_char : c.end_char]
            assert _normalize(span) in _normalize(c.content)

    def test_every_chunk_carries_its_slide_heading(self):
        text = _pptx_shaped_text(num_slides=15)
        chunks = _chunk_by_sections(text, "doc", max_size=60, overlap=0)
        assert len(chunks) >= 15, "small max_size should force per-slide (or finer) chunks"
        for c in chunks:
            assert "## Slide" in c.content, f"chunk missing its slide heading: {c.content!r}"

    def test_falls_back_to_token_chunking_when_no_section_markers(self):
        # Adversarial: a "structured" hint applied to text with no "## "
        # markers at all (e.g. JSON's pretty-printed body, or an extractor
        # that changed shape). Must degrade gracefully, never crash, never
        # emit one giant unbounded chunk.
        text = "{\n" + ",\n".join(f'  "key{i}": "value{i}"' for i in range(200)) + "\n}"
        chunks = _chunk_by_sections(text, "doc", max_size=100, overlap=10)
        assert len(chunks) >= 2
        for c in chunks:
            assert len(c.content) <= 100 + 50  # size-bounded like _chunk_by_size

    def test_empty_text_produces_no_chunks(self):
        assert _chunk_by_sections("", "doc", max_size=100, overlap=0) == []


# ---------------------------------------------------------------------------
# _chunk_prose (prose hint: txt, markdown, docx, eml, epub, rtf, odt, pdf, html)
# ---------------------------------------------------------------------------


class TestChunkProse:
    def test_no_header_block_behaves_exactly_like_plain_sentence_chunking(self):
        # The overwhelming common case (a plain memo/report) must be BYTE-FOR-
        # BYTE unchanged from the pre-#129 sentence chunker — no regression
        # for the vast majority of prose documents that have no leading
        # "Key: value" block.
        from src.temporal.activities.chunk import _chunk_by_sentences

        text = "First sentence here. Second sentence here. Third sentence here. Fourth one."
        expected = _chunk_by_sentences(text, "doc", max_size=30, overlap=5)
        actual = _chunk_prose(text, "doc", max_size=30, overlap=5)
        assert [(c.content, c.start_char, c.end_char) for c in actual] == [
            (c.content, c.start_char, c.end_char) for c in expected
        ]

    def test_every_chunk_carries_sender_and_subject_for_eml_shaped_text(self):
        text = _eml_shaped_text()
        chunks = _chunk_prose(text, "doc", max_size=120, overlap=20)
        assert len(chunks) >= 3, "test is only meaningful if it forces multiple chunks"
        for c in chunks:
            assert "From: alice@example.com" in c.content
            assert "Subject: Q3 numbers" in c.content

    def test_header_block_not_double_counted_in_first_chunk(self):
        text = _eml_shaped_text()
        chunks = _chunk_prose(text, "doc", max_size=120, overlap=20)
        # The header shouldn't appear TWICE in the first chunk (it's already
        # part of the source span there).
        assert chunks[0].content.count("From: alice@example.com") == 1

    def test_detect_header_block_ignores_ordinary_prose(self):
        text = "This is just a normal paragraph. It has a colon: right here, mid-sentence."
        header, end = _detect_header_block(text)
        assert header == ""
        assert end == 0

    def test_detect_header_block_finds_eml_style_headers(self):
        text = _eml_shaped_text()
        header, end = _detect_header_block(text)
        assert "From: alice@example.com" in header
        assert "Subject: Q3 numbers" in header
        assert text[end:].startswith("\n") or text[end - 1] == "\n" or end > 0


# ---------------------------------------------------------------------------
# Full dispatch: _chunk_text_inner precedence + metadata.chunking_strategy
# ---------------------------------------------------------------------------


class _FakeStaging:
    def __init__(self, text: str) -> None:
        self._text = text
        self.written_chunks: list[dict] | None = None

    def read_text(self, workflow_run_id: str) -> str:
        return self._text

    def write_chunks(self, workflow_run_id: str, chunks: list[dict]) -> None:
        self.written_chunks = chunks


def _make_settings(**overrides) -> Settings:
    base = dict(
        DATABASE_URL="postgresql://x/y",
        WEAVIATE_URL="http://localhost:8080",
        WEAVIATE_API_KEY="",
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _run_chunk(
    monkeypatch, text: str, input_obj: ChunkTextInput, settings: Settings
) -> _FakeStaging:
    fake = _FakeStaging(text)
    import src.config.settings as settings_mod
    import src.temporal.shared_services as shared

    monkeypatch.setattr(shared, "get_staging_service", lambda: fake, raising=True)
    monkeypatch.setattr(chunk_mod, "get_settings", lambda: settings, raising=False)
    monkeypatch.setattr(settings_mod, "get_settings", lambda: settings, raising=True)
    asyncio.run(_chunk_text_inner(input_obj))
    return fake


class TestDispatchPrecedence:
    def test_tabular_mime_resolves_to_rows_strategy(self, monkeypatch):
        settings = _make_settings(CHUNKING_STRATEGY="tokens", MAX_CHUNK_SIZE=150, CHUNK_OVERLAP=0)
        fake = _run_chunk(
            monkeypatch,
            _csv_shaped_text(num_rows=40),
            ChunkTextInput(
                workflow_run_id="wf",
                document_id="d",
                content_type="text/csv",
            ),
            settings,
        )
        assert fake.written_chunks
        assert len(fake.written_chunks) > 1
        for c in fake.written_chunks:
            assert c["chunking_strategy"] == "rows"
            assert "col0" in c["content"]

    def test_structured_mime_resolves_to_sections_strategy(self, monkeypatch):
        settings = _make_settings(CHUNKING_STRATEGY="tokens", MAX_CHUNK_SIZE=80, CHUNK_OVERLAP=0)
        fake = _run_chunk(
            monkeypatch,
            _pptx_shaped_text(num_slides=10),
            ChunkTextInput(
                workflow_run_id="wf",
                document_id="d",
                content_type=(
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                ),
            ),
            settings,
        )
        assert fake.written_chunks
        for c in fake.written_chunks:
            assert c["chunking_strategy"] == "sections"
            assert "## Slide" in c["content"]

    def test_prose_mime_with_header_resolves_to_prose_header_strategy(self, monkeypatch):
        settings = _make_settings(CHUNKING_STRATEGY="tokens", MAX_CHUNK_SIZE=120, CHUNK_OVERLAP=20)
        fake = _run_chunk(
            monkeypatch,
            _eml_shaped_text(),
            ChunkTextInput(
                workflow_run_id="wf",
                document_id="d",
                content_type="message/rfc822",
            ),
            settings,
        )
        assert fake.written_chunks
        assert len(fake.written_chunks) > 1
        for c in fake.written_chunks:
            assert c["chunking_strategy"] == "prose_header"
            assert "Subject: Q3 numbers" in c["content"]

    def test_explicit_override_wins_over_registry_hint(self, monkeypatch):
        # content_type says "tabular" (csv) but the caller explicitly asked
        # for paragraph chunking — the override must win.
        settings = _make_settings(CHUNKING_STRATEGY="tokens", MAX_CHUNK_SIZE=150, CHUNK_OVERLAP=0)
        fake = _run_chunk(
            monkeypatch,
            _csv_shaped_text(num_rows=10),
            ChunkTextInput(
                workflow_run_id="wf",
                document_id="d",
                content_type="text/csv",
                strategy="paragraphs",
            ),
            settings,
        )
        assert fake.written_chunks
        for c in fake.written_chunks:
            assert c["chunking_strategy"] == "paragraphs"

    def test_no_content_type_falls_back_to_config_unchanged(self, monkeypatch):
        # Backward compatibility: a caller that never learned about #129
        # (content_type=None, the dataclass default) gets EXACTLY the
        # pre-#129 config-driven behavior.
        settings = _make_settings(
            CHUNKING_STRATEGY="sentences", MAX_CHUNK_SIZE=200, CHUNK_OVERLAP=10
        )
        fake = _run_chunk(
            monkeypatch,
            "Sentence one here. Sentence two here. Sentence three here.",
            ChunkTextInput(workflow_run_id="wf", document_id="d"),
            settings,
        )
        assert fake.written_chunks
        for c in fake.written_chunks:
            assert c["chunking_strategy"] == "sentences"

    def test_unregistered_content_type_falls_back_to_config(self, monkeypatch):
        # A content_type with no registry entry must degrade to the config
        # fallback, never crash the activity (adversarial: hint/text mismatch
        # taken to the extreme -- no hint resolvable at all).
        settings = _make_settings(
            CHUNKING_STRATEGY="paragraphs", MAX_CHUNK_SIZE=200, CHUNK_OVERLAP=0
        )
        fake = _run_chunk(
            monkeypatch,
            "Para one.\n\nPara two.\n\nPara three.",
            ChunkTextInput(
                workflow_run_id="wf",
                document_id="d",
                content_type="application/x-not-a-registered-type",
            ),
            settings,
        )
        assert fake.written_chunks
        for c in fake.written_chunks:
            assert c["chunking_strategy"] == "paragraphs"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
