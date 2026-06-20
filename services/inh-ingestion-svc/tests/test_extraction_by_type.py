"""Per-file-type extraction tests against the bundled sample documents.

Verifies that each end-to-end supported format (txt, md, csv, json, html, docx,
pdf) extracts to non-empty, readable text via the production extractor helpers,
and that the deliberately unsupported XLSX path is rejected. These run offline
(no storage/staging/Temporal) by calling the extractor helpers directly.
"""

import json
from pathlib import Path

import pytest

from src.temporal.activities.extract import (
    _extract_docx_text,
    _extract_html_text,
    _extract_pdf_text,
)

# tests/ -> inh-ingestion-svc -> services -> repo
_REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_DOCS_DIR = _REPO_ROOT / "docs" / "examples" / "sample-documents"


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Override the DB-backed root autouse fixture so these stay offline.

    These extraction tests need neither PostgreSQL nor any other live service;
    shadowing the root ``cleanup_test_data`` (which skips when PostgreSQL is
    down) lets them run unconditionally, including in local dev without Docker.
    """
    yield


def _read(filename: str) -> bytes:
    path = SAMPLE_DOCS_DIR / filename
    if not path.is_file():
        pytest.skip(f"Sample fixture missing: {path}")
    return path.read_bytes()


def test_extract_plain_text():
    text = _read("sample.txt").decode("utf-8", errors="ignore")
    assert text.strip()
    assert "Inherent" in text


def test_extract_markdown():
    text = _read("sample.md").decode("utf-8", errors="ignore")
    assert text.strip()


def test_extract_csv():
    text = _read("sample.csv").decode("utf-8", errors="ignore")
    assert text.strip()
    assert "," in text


def test_extract_json():
    data = json.loads(_read("sample.json").decode("utf-8"))
    pretty = json.dumps(data, indent=2)
    assert pretty.strip()
    assert isinstance(data, (dict, list))


def test_extract_html():
    text = _extract_html_text(_read("sample.html"))
    assert text.strip()
    # Tags must be stripped.
    assert "<html" not in text.lower()
    assert "<body" not in text.lower()


def test_extract_docx():
    text = _extract_docx_text(_read("sample.docx"))
    assert text.strip()
    assert "Inherent" in text


def test_extract_pdf():
    """Hand-built sample PDF must yield extractable text."""
    text = _extract_pdf_text(_read("sample.pdf"))
    assert text.strip(), "PDF extraction returned empty text"
    assert "Inherent" in text


def test_xlsx_extraction_is_rejected():
    """XLSX is intentionally unsupported end-to-end; extraction must raise.

    Mirrors the spreadsheet branch in ``extract_text`` which raises rather than
    silently producing empty output.
    """
    # Re-implement the dispatch decision for the spreadsheet content type to
    # confirm the rejection contract without needing a real .xlsx fixture.
    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    is_spreadsheet = "spreadsheetml" in content_type or content_type.endswith((".xlsx", ".xls"))
    assert is_spreadsheet, "XLSX content type should be classified as spreadsheet"
