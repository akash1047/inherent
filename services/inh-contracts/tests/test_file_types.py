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

    def test_current_ten_formats_present(self):
        """Pins the eight formats that existed pre-#117, plus XLSX (#118) and
        PPTX (#119), migrated/added with no loss (acceptance criterion: 'All
        8 current formats migrate to registry entries with behavior
        unchanged')."""
        keys = {spec.key for spec in FILE_TYPE_REGISTRY}
        assert keys == {
            "txt",
            "markdown",
            "csv",
            "html",
            "json",
            "pdf",
            "docx",
            "xlsx",
            "pptx",
            "png",
        }


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
        """.xls (legacy binary Excel, NOT the same format as .xlsx) must stay
        unregistered -- #118 explicitly requires legacy .xls to be rejected,
        never silently mis-parsed as its OOXML successor. (.xlsx itself is
        now registered as of #118 -- see test_get_spec_for_extension_xlsx.)"""
        assert get_spec_for_extension(".xls") is None

    def test_get_spec_by_key(self):
        assert get_spec_by_key("png").mime_types == ("image/png",)
        assert get_spec_by_key("does-not-exist") is None

    def test_all_mime_types_matches_historical_allowed_list(self):
        """Pins byte-for-byte parity (SET *and* ORDER) with the pre-#117
        hand-maintained ALLOWED_MIME_TYPES list in constants.py, so the 400
        error text's exact wording is unchanged by this migration -- with
        XLSX (#118) and PPTX (#119) inserted right after docx, keeping the
        three OOXML siblings adjacent (matches the registry's own ordering:
        see the FILE_TYPE_REGISTRY comment). png stays last, as before."""
        assert all_mime_types() == [
            "text/plain",
            "text/markdown",
            "text/csv",
            "text/html",
            "application/pdf",
            "application/json",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "image/png",
        ]

    def test_get_spec_for_mime_strips_content_type_parameters(self):
        """The most common real-world Content-Type variation -- a browser or
        HTTP client appending '; charset=...' -- must not 400 (#117 review)."""
        spec = get_spec_for_mime("text/plain; charset=utf-8")
        assert spec is not None
        assert spec.key == "txt"

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

    def test_get_spec_for_mime_xlsx(self):
        """#118: XLSX is registered, REST-only (binary), tabular chunking."""
        spec = get_spec_for_mime(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert spec is not None
        assert spec.key == "xlsx"
        assert spec.surfaces == frozenset({"rest"})
        assert spec.chunking_hint == "tabular"
        assert spec.extractor == "xlsx"

    def test_get_spec_for_mime_pptx(self):
        """#119: PPTX is registered, REST-only (binary). chunking_hint is
        "structured" -- ChunkingHint has no "sections" member (the issue's
        proposed name); "structured" is the closest existing value for a
        format made of discrete addressable units (slides) rather than
        continuous prose, same rationale as json's "structured" hint."""
        spec = get_spec_for_mime(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
        assert spec is not None
        assert spec.key == "pptx"
        assert spec.surfaces == frozenset({"rest"})
        assert spec.chunking_hint == "structured"
        assert spec.extractor == "pptx"

    def test_get_spec_for_extension_xlsx(self):
        assert get_spec_for_extension(".xlsx").key == "xlsx"

    def test_get_spec_for_extension_pptx(self):
        assert get_spec_for_extension(".pptx").key == "pptx"


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

    # -- BLOCKER 3: bounded-prefix signature scan, not strict byte-0 match --
    # This repo's own pypdf parses each of these leading-junk PDFs to a real
    # page (verified directly against pypdf.PdfReader, not asserted blind);
    # a strict startswith() rejected uploads that worked fine end-to-end.

    def test_pdf_with_leading_blank_line_accepted(self):
        content = b"\n\n%PDF-1.4\n%useful pdf content follows"
        spec = sniff_content_type(content, "application/pdf")
        assert spec.key == "pdf"

    def test_pdf_with_leading_utf8_bom_accepted(self):
        content = b"\xef\xbb\xbf%PDF-1.4\n%useful pdf content follows"
        spec = sniff_content_type(content, "application/pdf")
        assert spec.key == "pdf"

    def test_pdf_with_leading_whitespace_accepted(self):
        content = b"   %PDF-1.7\n%useful pdf content follows"
        spec = sniff_content_type(content, "application/pdf")
        assert spec.key == "pdf"

    def test_pdf_signature_must_still_appear_somewhere_in_the_window(self):
        """The bounded-prefix tolerance is not "accept anything declared
        PDF" -- content with NO PDF signature anywhere in the sniff window
        is still rejected."""
        with pytest.raises(ContentTypeMismatchError):
            sniff_content_type(b"this text never contains the pdf marker at all", "application/pdf")

    # -- BLOCKER 4: shared-magic-prefix formats (the OOXML/ZIP family) must
    # not mutually reject each other. This was proven with a SYNTHETIC xlsx
    # spec before #118 landed; now that XLSX (#118) and PPTX (#119) are both
    # REAL registry entries, this exercises the real three-way family --
    # docx, xlsx, pptx -- with no monkeypatching required. #130 (ZIP) is the
    # next sibling this same guarantee must hold for.

    def test_shared_magic_family_does_not_mutually_reject(self):
        """A real DOCX, a real XLSX, and a real PPTX -- all declaring the
        identical ZIP local-file-header magic (PK\\x03\\x04) -- each sniff
        clean as THEMSELVES. Registering the second and third OOXML sibling
        did not newly break the first (docx), which is the exact regression
        #117's first attempt (treating shared magic as an automatic reject)
        would have caused the moment #118 landed."""
        docx_spec = get_spec_by_key("docx")
        xlsx_spec = get_spec_by_key("xlsx")
        pptx_spec = get_spec_by_key("pptx")
        assert docx_spec is not None
        assert xlsx_spec is not None
        assert pptx_spec is not None

        docx_result = sniff_content_type(b"PK\x03\x04 real docx bytes", docx_spec.mime_types[0])
        assert docx_result.key == "docx"

        xlsx_result = sniff_content_type(b"PK\x03\x04 real xlsx bytes", xlsx_spec.mime_types[0])
        assert xlsx_result.key == "xlsx"

        pptx_result = sniff_content_type(b"PK\x03\x04 real pptx bytes", pptx_spec.mime_types[0])
        assert pptx_result.key == "pptx"

    def test_shared_magic_family_still_rejects_a_genuinely_different_binary(self):
        """The overlap tolerance is family-scoped, not "PDF/PNG can now claim
        to be a docx" -- a real cross-family mismatch (PNG bytes) is still
        caught for each of the three real OOXML siblings."""
        for spec in (get_spec_by_key("docx"), get_spec_by_key("xlsx"), get_spec_by_key("pptx")):
            assert spec is not None
            with pytest.raises(ContentTypeMismatchError):
                sniff_content_type(b"\x89PNG\r\n\x1a\n fake png bytes", spec.mime_types[0])

    def test_xlsx_bytes_declared_as_docx_pass_the_byte_sniff(self):
        """The reachable case this guarantee implies: a byte sniff CANNOT
        distinguish the OOXML siblings from each other (a 4-byte ZIP header
        is all any of them has to check). Genuine XLSX bytes, declared as
        DOCX, pass `sniff_content_type` -- it resolves to the DECLARED spec
        (docx), not the true one. This is NOT a hole: `sniff_content_type`
        only proves "these bytes are plausibly a ZIP-family OOXML document",
        never "these bytes are SPECIFICALLY a .docx". Disambiguation for a
        filename-less/extension-mismatched upload is deferred to the
        extraction stage, which fails loudly instead of mis-parsing (see
        inh-ingestion-svc's test_extraction_by_type.py::
        test_genuine_xlsx_fed_to_docx_extractor_fails_loudly_not_silently)."""
        docx_spec = get_spec_by_key("docx")
        assert docx_spec is not None

        # Genuine XLSX bytes (same ZIP signature), declared as the DOCX mime.
        result = sniff_content_type(b"PK\x03\x04 an actual xlsx workbook's bytes", docx_spec.mime_types[0])
        # Resolves to the DECLARED type -- sniff_content_type's contract is
        # "do the bytes CONTRADICT the declared type", not "identify the
        # true type". They don't contradict (same family), so it resolves
        # docx, silently wrong about the TRUE format.
        assert result.key == "docx"

    def test_xlsx_named_file_declared_as_docx_is_caught_by_extension_check(self):
        """The byte sniff alone cannot catch a mislabeled OOXML sibling, but
        `check_extension_consistency` (the THIRD signal: filename) can, and
        does, whenever the upload has a recognized, differing extension --
        the common real-world case (an uploader's filename normally matches
        its true type even when Content-Type is wrong)."""
        docx_spec = get_spec_by_key("docx")
        assert docx_spec is not None
        with pytest.raises(ExtensionMismatchError) as exc_info:
            check_extension_consistency("workbook.xlsx", docx_spec)
        assert "xlsx" in str(exc_info.value)
        assert "docx" in str(exc_info.value)


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
        """The '.pdf' extension is a BINARY (magic-bearing) format, so
        declaring it 'text/plain' is a real, actionable disagreement."""
        spec = get_spec_for_mime("text/plain")
        with pytest.raises(ExtensionMismatchError) as exc_info:
            check_extension_consistency("report.pdf", spec)
        assert "pdf" in str(exc_info.value)
        assert "txt" in str(exc_info.value)

    # -- BLOCKER 1: TEXT-format extensions (magic is None) must NEVER reject,
    # regardless of which text/* type is declared. text/plain is a truthful,
    # IANA-valid Content-Type for Markdown/CSV/HTML uploads (text/markdown
    # was only registered in 2016; plenty of clients and OS mime databases
    # still emit text/plain for any text file) -- these are exactly the
    # correctly-labeled uploads the #117 review caught being rejected.

    @pytest.mark.parametrize(
        "filename,declared_mime",
        [
            ("README.md", "text/plain"),
            ("data.csv", "text/plain"),
            ("page.html", "text/plain"),
            ("cfg.json", "text/plain"),
            ("notes.txt", "text/markdown"),
            ("notes.txt", "text/csv"),
        ],
    )
    def test_sibling_text_extension_is_accepted(self, filename, declared_mime):
        """Every text-format extension (magic is None) declared as any
        other text-format type must be accepted -- the exact scenarios named
        in the #117 review's BLOCKER 1."""
        spec = get_spec_for_mime(declared_mime)
        check_extension_consistency(filename, spec)  # must not raise

    def test_binary_extension_declared_as_text_is_still_rejected(self):
        """The check still catches a REAL contradiction: a '.pdf' (binary,
        magic-bearing) file declared as any text/* type."""
        for declared_mime in ("text/plain", "text/markdown", "text/csv"):
            spec = get_spec_for_mime(declared_mime)
            with pytest.raises(ExtensionMismatchError):
                check_extension_consistency("report.pdf", spec)

    def test_text_extension_declared_as_binary_is_not_caught_here(self):
        """The mirror case (declared PDF, filename says .txt) is NOT caught
        by this function -- .txt has no magic, so it never triggers the
        check. It IS still caught overall, by `sniff_content_type`'s byte
        sniff (real text bytes won't match the PDF signature) -- this
        function is one of two checks, not the only one."""
        spec = get_spec_for_mime("application/pdf")
        check_extension_consistency("notes.txt", spec)  # must not raise

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
