"""Docs-sync contract (#117): the supported-file-types table in
docs/reference/file-types.md must match inh_contracts.file_types's own
rendering of FILE_TYPE_REGISTRY.

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
"""

from __future__ import annotations

from pathlib import Path

from inh_contracts.file_types import render_markdown_table

# tests/unit -> inh-public-api-svc -> services -> repo root (mirrors the
# existing REPO_ROOT convention in inh-ingestion-svc's
# test_extraction_by_type.py, which reaches into docs/examples the same way).
REPO_ROOT = Path(__file__).resolve().parents[4]
DOC_PATH = REPO_ROOT / "docs" / "reference" / "file-types.md"

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
    from inh_contracts.file_types import all_mime_types

    text = DOC_PATH.read_text()
    for mime in all_mime_types():
        assert mime in text, f"{mime} not documented in {DOC_PATH}"
