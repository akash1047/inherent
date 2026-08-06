"""Tests for the file-type support registry (#117).

Written before the implementation (TESTS FIRST per CLAUDE.md): running this
file against the pre-#117 codebase fails with ImportError because
``inh_contracts.file_types`` did not exist -- there was no single place any
of these facts were even queryable, only five independent, hand-maintained
copies (see the module docstring in ``inh_contracts/file_types.py``).
"""

from __future__ import annotations

import pytest

from inh_contracts.file_types import (
    FILE_TYPE_REGISTRY,
    ContentTypeMismatchError,
    ExtensionMismatchError,
    UnknownContentTypeError,
    all_mime_types,
    check_extension_consistency,
    get_spec_by_key,
    get_spec_for_extension,
    get_spec_for_mime,
    mcp_mime_types,
    render_markdown_table,
    sniff_content_type,
)

# ---------------------------------------------------------------------------
# Registry shape / internal consistency
# ---------------------------------------------------------------------------


class TestRegistryShape:
    """The registry itself must be internally consistent -- these are the
    invariants every sibling format issue (#118-#130) will be trusted to
    keep holding when it adds an entry."""

    def test_keys_are_unique(self):
        keys = [spec.key for spec in FILE_TYPE_REGISTRY]
        assert len(keys) == len(set(keys)), "duplicate FileTypeSpec.key"

    def test_mime_types_are_globally_unique(self):
        """No two specs may claim the same MIME type -- lookup must be
        unambiguous."""
        seen: set[str] = set()
        for spec in FILE_TYPE_REGISTRY:
            for mime in spec.mime_types:
                assert mime not in seen, f"MIME '{mime}' claimed by multiple specs"
                seen.add(mime)

    def test_every_spec_has_at_least_one_mime_and_extension(self):
        for spec in FILE_TYPE_REGISTRY:
            assert spec.mime_types, f"{spec.key} has no mime_types"
            assert spec.extensions, f"{spec.key} has no extensions"

    def test_degradation_is_meaningless_without_optional_extra(self):
        """A spec with no optional_extra has nothing optional to degrade --
        the field should stay at its "hard_fail" default so it isn't
        mistakenly read as promising graceful degradation that doesn't
        exist."""
        for spec in FILE_TYPE_REGISTRY:
            if spec.optional_extra is None:
                assert spec.degradation == "hard_fail", (
                    f"{spec.key} has no optional_extra but degradation=" f"{spec.degradation!r}"
                )

    def test_current_eight_formats_present(self):
        """Pins the eight formats that existed pre-#117 migrated with no
        loss (acceptance criterion: 'All 8 current formats migrate to
        registry entries with behavior unchanged')."""
        keys = {spec.key for spec in FILE_TYPE_REGISTRY}
        assert keys == {"txt", "markdown", "csv", "html", "json", "pdf", "docx", "png"}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


class TestLookups:
    def test_get_spec_for_mime_known(self):
        spec = get_spec_for_mime("application/pdf")
        assert spec is not None
        assert spec.key == "pdf"

    def test_get_spec_for_mime_unknown_returns_none(self):
        assert get_spec_for_mime("application/x-nonexistent") is None

    def test_get_spec_for_mime_is_case_and_whitespace_tolerant(self):
        spec = get_spec_for_mime("  APPLICATION/PDF  ")
        assert spec is not None
        assert spec.key == "pdf"

    def test_get_spec_for_extension_with_and_without_dot(self):
        assert get_spec_for_extension(".md").key == "markdown"
        assert get_spec_for_extension("md").key == "markdown"

    def test_get_spec_for_extension_unknown_returns_none(self):
        assert get_spec_for_extension(".xlsx") is None

    def test_get_spec_by_key(self):
        assert get_spec_by_key("png").mime_types == ("image/png",)
        assert get_spec_by_key("does-not-exist") is None

    def test_all_mime_types_matches_historical_allowed_list(self):
        """Pins the exact SET of MIME types the pre-#117 hand-maintained
        ALLOWED_MIME_TYPES list in constants.py accepted, so the migration is
        provably behavior-preserving (registry entry order follows
        docs/index.md's prose order -- JSON before PDF -- which differs only
        in list POSITION, never in membership, from the old constants.py
        list; nothing reads ALLOWED_MIME_TYPES order, only membership)."""
        assert set(all_mime_types()) == {
            "text/plain",
            "text/markdown",
            "text/csv",
            "text/html",
            "application/json",
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "image/png",
        }
        assert len(all_mime_types()) == 8, "no type dropped or duplicated by the migration"

    def test_mcp_mime_types_matches_historical_text_subset(self):
        """Pins byte-for-byte parity with the pre-#117
        SUPPORTED_TEXT_MIME_TYPES (the text/* subset of ALLOWED_MIME_TYPES)."""
        assert mcp_mime_types() == ("text/csv", "text/html", "text/markdown", "text/plain")

    def test_json_is_rest_only(self):
        """JSON is textual but was never MCP-exposed pre-#117 -- the
        registry's explicit `surfaces` field (not a 'text/' prefix guess)
        must preserve that."""
        spec = get_spec_for_mime("application/json")
        assert spec.surfaces == frozenset({"rest"})


# ---------------------------------------------------------------------------
# sniff_content_type -- the hole #117 closes
# ---------------------------------------------------------------------------


class TestSniffContentType:
    def test_unregistered_declared_type_raises_unknown(self):
        with pytest.raises(UnknownContentTypeError):
            sniff_content_type(b"whatever", "application/x-msdownload")

    def test_correctly_labeled_text_passes(self):
        spec = sniff_content_type(b"hello world", "text/plain")
        assert spec.key == "txt"

    def test_correctly_labeled_pdf_passes(self):
        spec = sniff_content_type(b"%PDF-1.4\n...", "application/pdf")
        assert spec.key == "pdf"

    def test_pdf_labeled_bytes_that_are_not_pdf_are_rejected(self):
        """Declared PDF, but the bytes don't start with the PDF signature."""
        with pytest.raises(ContentTypeMismatchError):
            sniff_content_type(b"not actually a pdf", "application/pdf")

    def test_png_bytes_declared_as_text_plain_are_rejected(self):
        """The exact scenario named in the #117 acceptance criteria: a
        mislabeled binary (PNG bytes as text/plain) must be rejected."""
        png_magic = b"\x89PNG\r\n\x1a\n" + b"rest of a fake png"
        with pytest.raises(ContentTypeMismatchError) as exc_info:
            sniff_content_type(png_magic, "text/plain")
        assert "png" in str(exc_info.value)

    def test_png_bytes_declared_as_pdf_are_rejected(self):
        png_magic = b"\x89PNG\r\n\x1a\n" + b"rest of a fake png"
        with pytest.raises(ContentTypeMismatchError):
            sniff_content_type(png_magic, "application/pdf")

    def test_short_content_shorter_than_magic_is_rejected_not_crashed(self):
        """A 2-byte upload declared as PDF must not raise IndexError/etc --
        `bytes.startswith` handles short buffers safely, this pins that the
        wrapper doesn't break that."""
        with pytest.raises(ContentTypeMismatchError):
            sniff_content_type(b"%P", "application/pdf")

    def test_correctly_labeled_docx_passes(self):
        spec = sniff_content_type(
            b"PK\x03\x04rest of a real docx zip",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert spec.key == "docx"


# ---------------------------------------------------------------------------
# check_extension_consistency -- the third leg of the sniffing story.
# sniff_content_type compares BYTES against the DECLARED type; this compares
# the FILENAME against the DECLARED type. Between the two, any disagreement
# among {declared type, filename, actual bytes} is caught by at least one
# check (see document_intake.py's docstring for the full argument).
# ---------------------------------------------------------------------------


class TestCheckExtensionConsistency:
    def test_matching_extension_passes(self):
        spec = get_spec_for_mime("application/pdf")
        check_extension_consistency("report.pdf", spec)  # must not raise

    def test_mismatched_known_extension_rejected(self):
        """The '.pdf' extension belongs to a DIFFERENT registered spec than
        the declared 'text/plain' -- a real disagreement, not a false
        positive on an unrelated file."""
        spec = get_spec_for_mime("text/plain")
        with pytest.raises(ExtensionMismatchError) as exc_info:
            check_extension_consistency("report.pdf", spec)
        assert "pdf" in str(exc_info.value)
        assert "txt" in str(exc_info.value)

    def test_unknown_extension_is_not_an_error(self):
        """An extension the registry doesn't recognize (e.g. a format #117
        doesn't cover yet) must NOT be rejected on that basis alone --
        content_type is the authoritative signal; an unrecognized extension
        is simply not evidence of anything."""
        spec = get_spec_for_mime("text/plain")
        check_extension_consistency("notes.xyz", spec)  # must not raise

    def test_no_extension_is_not_an_error(self):
        """A filename with no extension at all (e.g. the REST route's
        'unnamed' fallback) must not be rejected -- there's nothing to
        compare."""
        spec = get_spec_for_mime("text/plain")
        check_extension_consistency("unnamed", spec)  # must not raise

    def test_case_insensitive_extension_match(self):
        spec = get_spec_for_mime("application/pdf")
        check_extension_consistency("REPORT.PDF", spec)  # must not raise


# ---------------------------------------------------------------------------
# Docs generation
# ---------------------------------------------------------------------------


class TestRenderMarkdownTable:
    def test_renders_a_row_per_registry_entry(self):
        table = render_markdown_table()
        for spec in FILE_TYPE_REGISTRY:
            assert spec.key in table

    def test_renders_valid_markdown_table_header(self):
        table = render_markdown_table()
        lines = table.strip().splitlines()
        assert lines[0].startswith("|")
        assert set(lines[1].replace("|", "").strip()) <= {"-", " "}

    def test_deterministic_across_calls(self):
        """Docs generation must be reproducible -- a diff-only script run
        must never produce spurious churn from nondeterministic ordering
        (e.g. iterating a set)."""
        assert render_markdown_table() == render_markdown_table()
