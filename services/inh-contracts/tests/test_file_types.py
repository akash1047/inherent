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
    EXPLICITLY_UNSUPPORTED,
    FILE_TYPE_REGISTRY,
    ContentTypeMismatchError,
    ExtensionMismatchError,
    FileTypeSpec,
    UnknownContentTypeError,
    all_mime_types,
    check_extension_consistency,
    explicitly_unsupported_message_for_extension,
    explicitly_unsupported_message_for_mime,
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

    def test_current_registered_formats_are_exactly_these(self):
        """Pins the eight formats that existed pre-#117 migrated with no
        loss (acceptance criterion: 'All 8 current formats migrate to
        registry entries with behavior unchanged')."""
        keys = {spec.key for spec in FILE_TYPE_REGISTRY}
        assert keys == {
            "txt", "markdown", "csv", "html", "pdf", "json", "docx",
            "xlsx", "pptx", "png", "eml", "epub", "rtf", "odt",
        }

    def test_longtail_formats_present(self):
        """#124/#125/#126: eml, epub, rtf, odt are registered."""
        keys = {spec.key for spec in FILE_TYPE_REGISTRY}
        assert {"eml", "epub", "rtf", "odt"} <= keys


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
        # NB: this deliberately uses an extension no issue will ever register.
        # It previously used ".xlsx", which stopped being unknown the moment
        # #118 landed -- caught by the restored exact pins at batch-3 merge.
        assert get_spec_for_extension(".xyz") is None
        assert get_spec_for_extension(".doc") is None

    def test_get_spec_by_key(self):
        assert get_spec_by_key("png").mime_types == ("image/png",)
        assert get_spec_by_key("does-not-exist") is None

    def test_all_mime_types_exact_set_and_order(self):
        """Pins the FULL registered MIME list, set AND order.

        The first eight entries preserve byte-for-byte parity with the
        pre-#117 hand-maintained ALLOWED_MIME_TYPES in constants.py, so the
        400 error text's wording is unchanged by that migration; the rest are
        the formats their own issues appended (#118, #119, #124-#126).

        This was temporarily relaxed to a prefix check while those format
        branches were in flight concurrently, purely to avoid every branch
        conflicting with every other on this one assertion. The exact pin is
        restored here now that they have all landed -- #117 added it because
        a registry comment claimed ordering parity it did not have, and a
        prefix check cannot catch that in the tail.
        """
        mimes = all_mime_types()
        assert mimes == [
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
            "message/rfc822",
            "application/epub+zip",
            "application/rtf",
            "text/rtf",
            "application/vnd.oasis.opendocument.text",
        ]

    def test_longtail_mime_types_present(self):
        """#124/#125/#126: the four new long-tail MIME types are registered
        (order-independent -- see the prefix-only rationale above)."""
        assert set(all_mime_types()) >= {
            "message/rfc822",
            "application/epub+zip",
            "application/rtf",
            "text/rtf",
            "application/vnd.oasis.opendocument.text",
        }

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

    # -- #124/#125/#126: long-tail formats. All REST-only (binary or,
    # for EML, raw-bytes-with-non-UTF-8-transfer-encodings) -- none of
    # these were ever MCP-eligible (mcp upload_document is inline UTF-8 text
    # only, #87 Task 3).

    def test_eml_registered_rest_only(self):
        spec = get_spec_for_mime("message/rfc822")
        assert spec is not None
        assert spec.key == "eml"
        assert spec.surfaces == frozenset({"rest"})
        assert spec.magic is None  # RFC 822 has no binary signature

    def test_epub_registered_with_zip_magic(self):
        spec = get_spec_for_mime("application/epub+zip")
        assert spec is not None
        assert spec.key == "epub"
        assert spec.surfaces == frozenset({"rest"})
        assert spec.magic == b"PK\x03\x04"

    def test_rtf_registered_with_both_mime_aliases(self):
        """application/rtf is canonical; text/rtf is the common alias -- both
        must resolve to the same spec (#126)."""
        canonical = get_spec_for_mime("application/rtf")
        alias = get_spec_for_mime("text/rtf")
        assert canonical is not None
        assert canonical.key == "rtf"
        assert alias is canonical

    def test_odt_registered_with_zip_magic(self):
        spec = get_spec_for_mime("application/vnd.oasis.opendocument.text")
        assert spec is not None
        assert spec.key == "odt"
        assert spec.surfaces == frozenset({"rest"})
        assert spec.magic == b"PK\x03\x04"


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
    # not mutually reject each other the moment a sibling registers. This is
    # the load-bearing test #118 (XLSX)/#119 (PPTX)/#130 (ZIP) all rely on:
    # registering a new spec with the SAME magic as an existing one must
    # leave the EXISTING one (docx) still valid, not newly broken.

    def test_shared_magic_family_does_not_mutually_reject(self, monkeypatch):
        """Simulates #118 landing: register a synthetic 'xlsx' spec with the
        identical ZIP signature docx already uses, then confirm BOTH a real
        DOCX-declared-as-DOCX and a real XLSX-declared-as-XLSX still sniff
        clean -- neither one takes the other down."""
        import inh_contracts.file_types as ft

        docx_spec = get_spec_by_key("docx")
        xlsx_spec = FileTypeSpec(
            key="xlsx",
            mime_types=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
            extensions=(".xlsx",),
            magic=b"PK\x03\x04",  # identical signature -- the whole point
            surfaces=frozenset({"rest"}),
            extractor="xlsx",
            chunking_hint="tabular",
        )
        monkeypatch.setattr(ft, "FILE_TYPE_REGISTRY", (*FILE_TYPE_REGISTRY, xlsx_spec))

        docx_result = ft.sniff_content_type(b"PK\x03\x04 real docx bytes", docx_spec.mime_types[0])
        assert docx_result.key == "docx"

        xlsx_result = ft.sniff_content_type(b"PK\x03\x04 real xlsx bytes", xlsx_spec.mime_types[0])
        assert xlsx_result.key == "xlsx"

    # -- #124/#125/#126 SPECIFIC ASK: verify by hand that registering the
    # real EPUB and ODT specs (both PK\x03\x04, same family as docx) does
    # NOT break DOCX validation -- the exact regression #117's shared-magic
    # fix (test_shared_magic_family_does_not_mutually_reject above) exists
    # to prevent, exercised here against the REAL registry (not a synthetic
    # monkeypatched sibling) now that epub/odt actually landed.

    def test_docx_still_validates_with_epub_and_odt_registered(self):
        """DOCX, EPUB, and ODT all share the PK\\x03\\x04 ZIP signature.
        Registering epub/odt must not make docx-declared uploads start
        failing -- each of the three still sniffs clean as itself."""
        docx = sniff_content_type(
            b"PK\x03\x04 real docx bytes",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert docx.key == "docx"

        epub = sniff_content_type(b"PK\x03\x04 real epub bytes", "application/epub+zip")
        assert epub.key == "epub"

        odt = sniff_content_type(
            b"PK\x03\x04 real odt bytes", "application/vnd.oasis.opendocument.text"
        )
        assert odt.key == "odt"

    def test_shared_magic_family_still_rejects_a_genuinely_different_binary(self, monkeypatch):
        """The overlap tolerance is family-scoped, not "PDF/PNG can now claim
        to be a docx" -- a real cross-family mismatch is still caught even
        with the synthetic xlsx sibling present."""
        import inh_contracts.file_types as ft

        docx_spec = get_spec_by_key("docx")
        xlsx_spec = FileTypeSpec(
            key="xlsx",
            mime_types=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
            extensions=(".xlsx",),
            magic=b"PK\x03\x04",
            surfaces=frozenset({"rest"}),
            extractor="xlsx",
            chunking_hint="tabular",
        )
        monkeypatch.setattr(ft, "FILE_TYPE_REGISTRY", (*FILE_TYPE_REGISTRY, xlsx_spec))

        with pytest.raises(ContentTypeMismatchError):
            ft.sniff_content_type(b"\x89PNG\r\n\x1a\n fake png bytes", docx_spec.mime_types[0])

    # -- #126 review item 5: RTF's magic ("{\rtf") is plausible ENGLISH
    # PROSE, unlike PDF's "%PDF-" -- a full 1024-byte substring search
    # false-positives on ordinary text that merely discusses RTF. RTF's
    # `magic_anchor_window` must keep real RTF files working while no longer
    # rejecting prose that mentions "{\rtf" outside the first few bytes.

    def test_real_rtf_file_still_sniffs_clean(self):
        spec = sniff_content_type(b"{\\rtf1\\ansi\\deff0 hello world}", "application/rtf")
        assert spec.key == "rtf"

    def test_prose_mentioning_rtf_signature_is_not_mislabeled_as_rtf(self):
        """The exact scenario the review caught: a markdown/text file
        EXPLAINING the RTF format, declared as its real type, must not be
        rejected just because the string '{\\rtf1' appears somewhere past
        the anchored window."""
        content = (
            b"RTF files begin with the control word {\\rtf1\\ansi -- "
            b"here is why that matters for parsers."
        )
        spec = sniff_content_type(content, "text/plain")
        assert spec.key == "txt"

    def test_prose_mentioning_rtf_signature_declared_as_markdown_is_not_mislabeled(self):
        content = b"# About RTF\n\nRTF files begin with {\\rtf1\\ansi in the header."
        spec = sniff_content_type(content, "text/markdown")
        assert spec.key == "markdown"

    def test_rtf_declared_but_bytes_are_not_rtf_still_rejected(self):
        """The anchor narrows the window, it doesn't remove the check --
        content genuinely not RTF, declared as RTF, is still caught."""
        with pytest.raises(ContentTypeMismatchError):
            sniff_content_type(b"this is definitely not an rtf file at all", "application/rtf")

    def test_rtf_with_leading_bom_within_anchor_window_still_accepted(self):
        content = b"\xef\xbb\xbf{\\rtf1\\ansi hello"
        spec = sniff_content_type(content, "application/rtf")
        assert spec.key == "rtf"


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

    # -- #126 review item 6: RTF has a `magic` (needed for sniffing) but is
    # genuinely ASCII text, not a binary container -- it belongs in the same
    # "never rejected here" bucket as .txt/.md/.csv/.html, via
    # `extension_check_exempt`, even though `magic is not None` for it.

    def test_rtf_extension_declared_as_text_plain_is_accepted(self):
        spec = get_spec_for_mime("text/plain")
        check_extension_consistency("notes.rtf", spec)  # must not raise

    def test_rtf_extension_declared_as_markdown_is_accepted(self):
        spec = get_spec_for_mime("text/markdown")
        check_extension_consistency("notes.rtf", spec)  # must not raise

    def test_rtf_extension_declared_as_its_own_type_still_passes(self):
        spec = get_spec_for_mime("application/rtf")
        check_extension_consistency("report.rtf", spec)  # must not raise

    def test_genuinely_binary_extension_still_rejected_alongside_exempt_rtf(self):
        """The RTF exemption is scoped to RTF -- a real binary extension
        (.pdf) declared as a mismatched type is still caught."""
        spec = get_spec_for_mime("text/plain")
        with pytest.raises(ExtensionMismatchError):
            check_extension_consistency("report.pdf", spec)


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


# ---------------------------------------------------------------------------
# EXPLICITLY_UNSUPPORTED -- deliberately-rejected formats with a real
# replacement (#124/#126 review blocker 3). A single shared table so REST
# and MCP cannot disagree about which formats get this treatment, unlike
# the pre-fix state where each surface (or just REST) held its own copy.
# ---------------------------------------------------------------------------


class TestExplicitlyUnsupported:
    def test_doc_and_msg_are_registered(self):
        keys = {spec.key for spec in EXPLICITLY_UNSUPPORTED}
        assert {"doc", "msg"} <= keys

    def test_explicitly_unsupported_types_are_not_in_the_real_registry(self):
        """A format cannot be both accepted and explicitly rejected -- the
        two tables must never overlap on MIME type or extension."""
        registered_mimes = set(all_mime_types())
        registered_extensions = {ext for spec in FILE_TYPE_REGISTRY for ext in spec.extensions}
        for spec in EXPLICITLY_UNSUPPORTED:
            assert not (set(spec.mime_types) & registered_mimes)
            assert not (set(spec.extensions) & registered_extensions)

    def test_message_for_mime_names_the_replacement(self):
        doc_message = explicitly_unsupported_message_for_mime("application/msword")
        assert doc_message is not None
        assert ".docx" in doc_message

        msg_message = explicitly_unsupported_message_for_mime("application/vnd.ms-outlook")
        assert msg_message is not None
        assert ".eml" in msg_message

    def test_message_for_mime_is_none_for_a_registered_or_unknown_type(self):
        assert explicitly_unsupported_message_for_mime("application/pdf") is None
        assert explicitly_unsupported_message_for_mime("application/x-made-up") is None

    def test_message_for_mime_strips_content_type_parameters(self):
        message = explicitly_unsupported_message_for_mime("application/msword; charset=utf-8")
        assert message is not None
        assert ".docx" in message

    def test_message_for_extension_covers_the_content_type_omitted_case(self):
        """The exact gap #124/#126 review blocker 3 found: a surface that
        resolves content type FROM the filename (MCP upload_document with
        content_type omitted) needs the extension itself as a rejection
        key, not just the MIME type."""
        doc_message = explicitly_unsupported_message_for_extension("report.doc")
        assert doc_message is not None
        assert ".docx" in doc_message

        msg_message = explicitly_unsupported_message_for_extension("message.MSG")
        assert msg_message is not None
        assert ".eml" in msg_message

    def test_message_for_extension_is_none_for_registered_or_unknown_extension(self):
        assert explicitly_unsupported_message_for_extension("report.docx") is None
        assert explicitly_unsupported_message_for_extension("notes.xyz") is None
        assert explicitly_unsupported_message_for_extension("no-extension-at-all") is None


class TestOOXMLSiblingsFromBatch3:
    """XLSX/PPTX registry and shared-magic tests carried over from the
    #118/#119 branch during the batch-3 merge (#118, #119)."""

    def test_get_spec_for_extension_pptx(self):
        assert get_spec_for_extension(".pptx").key == "pptx"

    def test_get_spec_for_extension_xlsx(self):
        assert get_spec_for_extension(".xlsx").key == "xlsx"

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

    def test_xlsx_bytes_renamed_to_match_the_declared_lie_passes_both_checks(self):
        """Review follow-up: the extension check above ONLY fires when the
        filename carries a RECOGNIZED, DIFFERING extension. It does NOT fire
        when the filename is renamed to MATCH the (false) declared type --
        genuine XLSX bytes, uploaded as "report.docx" and declared as DOCX,
        pass BOTH `sniff_content_type` (same ZIP family, no contradiction)
        AND `check_extension_consistency` (the extension IS ".docx", which
        DOES match the declared docx spec -- there is nothing for this check
        to object to). This is the complete, accurate statement of the
        shared-magic guarantee's limit: renaming to match the lie reaches
        extraction exactly like the extensionless case
        test_xlsx_bytes_declared_as_docx_pass_the_byte_sniff already covers --
        it is not a narrower or rarer case, it is the SAME reachable case
        under a different, equally realistic filename. All six renamed pairs
        among {docx, xlsx, pptx} behave identically (only docx<->xlsx is
        spelled out here; the other four follow the same two-check argument
        with no format-specific difference in either function)."""
        docx_spec = get_spec_by_key("docx")
        assert docx_spec is not None

        # Genuine XLSX bytes, uploaded as "report.docx", declared as docx.
        sniff_result = sniff_content_type(
            b"PK\x03\x04 an actual xlsx workbook's bytes", docx_spec.mime_types[0]
        )
        assert sniff_result.key == "docx"  # passes -- resolves to the DECLARED type

        check_extension_consistency("report.docx", docx_spec)  # must not raise -- ".docx" IS docx's own extension

        # The mirror case: genuine DOCX bytes, uploaded as "sheet.xlsx",
        # declared as xlsx -- same two-check pass, same underlying gap.
        xlsx_spec = get_spec_by_key("xlsx")
        assert xlsx_spec is not None
        sniff_result_2 = sniff_content_type(
            b"PK\x03\x04 an actual docx document's bytes", xlsx_spec.mime_types[0]
        )
        assert sniff_result_2.key == "xlsx"
        check_extension_consistency("sheet.xlsx", xlsx_spec)  # must not raise

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
