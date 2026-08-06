"""Docs-sync contract (#117, extended #193): the supported-file-types table
in docs/reference/file-types.md, and the other prose surfaces that name file
types, must match inh_contracts.file_types's own view of FILE_TYPE_REGISTRY.

This is the test the #117 issue asks for explicitly: "Docs must be GENERATED
from or VERIFIED against the registry -- a supported-types table that can
drift from the code is the defect being fixed, so a test that fails when they
disagree is part of the deliverable." Before this file, the equivalent table
lived by hand in docs/index.md and had already drifted twice over (missing
``image/png`` from docs/examples/README.md's allowed-types line, and from
tests/unit/test_upload_document.py's own "verify every allowed type" test --
see CURRENT_SCATTER in the #117 PR description). Nothing enforced agreement;
this test is that enforcement.

Regenerate the checked-in table after changing FILE_TYPE_REGISTRY:
    uv run --project services/inh-contracts python scripts/generate_supported_formats.py

#193 note on scope: the #117 table above is fully generated and byte-exact
verified. README.md, docs/index.md, and the mcp-tools.md prose paragraph were
changed to a non-exhaustive "representative types + link to file-types.md"
style instead (see #193's own suggested fix #2) -- a list that never claims
completeness cannot drift, so there is nothing for a test to check there.
docs/examples/README.md's "Allowed MIME types" line and 400-error JSON
example DO make an exhaustive, literal claim (real curl/response examples a
reader may copy verbatim), so those two get real, code-derived assertions
below instead.
"""

from __future__ import annotations

from pathlib import Path

from inh_contracts.file_types import FILE_TYPE_REGISTRY, all_mime_types, render_markdown_table

# tests/unit -> inh-public-api-svc -> services -> repo root (mirrors the
# existing REPO_ROOT convention in inh-ingestion-svc's
# test_extraction_by_type.py, which reaches into docs/examples the same way).
REPO_ROOT = Path(__file__).resolve().parents[4]
DOC_PATH = REPO_ROOT / "docs" / "reference" / "file-types.md"
EXAMPLES_DOC_PATH = REPO_ROOT / "docs" / "examples" / "README.md"
MCP_TOOLS_DOC_PATH = REPO_ROOT / "docs" / "reference" / "mcp-tools.md"

BEGIN_MARKER = (
    "<!-- BEGIN GENERATED FILE TYPES TABLE (#117; run "
    "scripts/generate_supported_formats.py to refresh) -->"
)
END_MARKER = "<!-- END GENERATED FILE TYPES TABLE -->"


def test_file_types_doc_exists():
    assert DOC_PATH.is_file(), f"expected {DOC_PATH} to exist"


def test_file_types_doc_matches_registry():
    """The checked-in table between the markers must be BYTE-IDENTICAL to
    what render_markdown_table() produces right now. A mismatch means
    FILE_TYPE_REGISTRY changed (or the doc was hand-edited) without
    regenerating the doc -- exactly the drift #117 exists to prevent."""
    text = DOC_PATH.read_text()
    assert BEGIN_MARKER in text, "missing generated-table BEGIN marker"
    assert END_MARKER in text, "missing generated-table END marker"

    start = text.index(BEGIN_MARKER) + len(BEGIN_MARKER)
    end = text.index(END_MARKER)
    checked_in = text[start:end].strip("\n")
    expected = render_markdown_table().strip("\n")

    assert checked_in == expected, (
        "docs/reference/file-types.md is out of sync with FILE_TYPE_REGISTRY. "
        "Run: uv run --project services/inh-contracts python "
        "scripts/generate_supported_formats.py"
    )


def test_every_registry_type_named_in_doc():
    """Belt-and-suspenders on top of the exact-match check above: every
    registered MIME type must appear somewhere in the doc, so a future
    refactor of render_markdown_table() that accidentally drops a row still
    gets caught even if someone (wrongly) updates this test's marker
    comparison alongside it."""
    text = DOC_PATH.read_text()
    for mime in all_mime_types():
        assert mime in text, f"{mime} not documented in {DOC_PATH}"


# ---------------------------------------------------------------------------
# #193: docs/examples/README.md's literal, copy-pasteable examples.
#
# Unlike README.md/docs/index.md's prose (converted to a non-exhaustive
# "representative types + link" style that cannot drift because it no longer
# claims completeness), these two spots print values a reader can paste
# straight into a terminal -- an exhaustive claim that DOES need to track
# FILE_TYPE_REGISTRY, so it gets a real, code-derived assertion instead.
# ---------------------------------------------------------------------------


def test_examples_readme_exists():
    assert EXAMPLES_DOC_PATH.is_file(), f"expected {EXAMPLES_DOC_PATH} to exist"


def test_examples_readme_400_error_matches_registry():
    """The 'Unsupported file type' 400 JSON example must be BYTE-IDENTICAL to
    the real error `document_intake.py` raises (`ALLOWED_MIME_TYPES`, i.e.
    `all_mime_types()`, joined the same way) for the SAME declared content
    type the example uses (`application/octet-stream`). This is the literal
    error string #193's issue body calls out as one that "DOES change
    whenever `all_mime_types()` changes" -- previously nothing re-derived it
    from the registry to catch drift."""
    expected_detail = (
        "Unsupported file type 'application/octet-stream'. "
        f"Allowed types: {', '.join(all_mime_types())}"
    )
    text = EXAMPLES_DOC_PATH.read_text()
    assert expected_detail in text, (
        "docs/examples/README.md's 400 'Unsupported file type' example is out of "
        "sync with FILE_TYPE_REGISTRY. Expected this exact detail string:\n"
        f"{expected_detail}"
    )


def test_examples_readme_mentions_every_mime_type():
    """Every registered MIME type must appear somewhere in
    docs/examples/README.md (the 400 example above already guarantees this
    when it passes, but this assertion is independent of that string's exact
    wording -- it still catches a dropped/renamed type even if someone edits
    the 400 example's phrasing without also updating the dedicated
    'Allowed MIME types' line near the top of the Upload section)."""
    text = EXAMPLES_DOC_PATH.read_text()
    for mime in all_mime_types():
        assert mime in text, f"{mime} not mentioned anywhere in {EXAMPLES_DOC_PATH}"


# ---------------------------------------------------------------------------
# #193: docs/reference/mcp-tools.md's upload_document `content_type` docs.
#
# This doc already uses a "canonical types spelled out, code-family
# summarized as 'text/x-python and friends'" style rather than a full 30-item
# enumeration, so a byte-exact/full-mention check (like the two above) would
# force spelling out every code-language MIME alias in prose, which is not
# the doc's own goal. Instead: every MCP-eligible registry SPEC must have AT
# LEAST ONE of its identifying strings (a mime type or an extension) present
# somewhere in the doc -- real drift protection (a whole new MCP-surfaced
# format landing with zero mention here still fails this) without forcing an
# exhaustive alias dump.
# ---------------------------------------------------------------------------


def test_mcp_tools_doc_exists():
    assert MCP_TOOLS_DOC_PATH.is_file(), f"expected {MCP_TOOLS_DOC_PATH} to exist"


def test_mcp_tools_doc_mentions_every_mcp_eligible_format():
    text = MCP_TOOLS_DOC_PATH.read_text()
    for spec in FILE_TYPE_REGISTRY:
        if "mcp" not in spec.surfaces:
            continue
        identifiers = (*spec.mime_types, *spec.extensions)
        assert any(identifier in text for identifier in identifiers), (
            f"MCP-eligible format '{spec.key}' ({identifiers}) is not mentioned "
            f"anywhere in {MCP_TOOLS_DOC_PATH} -- the upload_document content_type "
            "docs need updating for this format."
        )
