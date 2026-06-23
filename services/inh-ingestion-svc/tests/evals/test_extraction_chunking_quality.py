"""Fixture-backed extraction & chunking quality evals, parametrized by file type.

For each bundled sample document we:

1. Extraction eval: run the same per-content-type extraction path used by the
   ``extract_text`` activity (via its underlying helpers) and assert the result
   is non-empty and passes ``DataQualityService.check_extracted_text`` with no
   critical failures. A simple fidelity metric is recorded.
2. Chunking eval: chunk the extracted text with the production chunker and
   assert ~100% coverage, continuous chunk indices, and that
   ``DataQualityService.check_chunks`` reports no critical failures.

Everything runs in-process against the files on disk -- no PostgreSQL, Weaviate,
storage, or Temporal worker required.
"""

import json
from pathlib import Path

import pytest

from src.services.quality import DataQualityService
from src.temporal.activities.chunk import _chunk_by_size
from src.temporal.activities.extract import (
    _extract_docx_text,
    _extract_html_text,
    _extract_pdf_text,
)

pytestmark = pytest.mark.eval


# (filename, content_type) for each supported end-to-end format.
SAMPLE_CASES = [
    ("sample.txt", "text/plain"),
    ("sample.md", "text/markdown"),
    ("sample.csv", "text/csv"),
    ("sample.json", "application/json"),
    ("sample.html", "text/html"),
    ("sample.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("sample.pdf", "application/pdf"),
]


def _extract(content: bytes, content_type: str, filename: str) -> str:
    """Mirror the per-content-type dispatch in ``extract_text``'s inner impl.

    Uses the real extractor helpers so the eval exercises production code.
    """
    content_type = content_type.lower()
    fn = filename.lower()

    if content_type in ("text/plain", "text/markdown", "text/csv"):
        return content.decode("utf-8", errors="ignore")
    if content_type == "application/json" or fn.endswith(".json"):
        data = json.loads(content.decode("utf-8"))
        return json.dumps(data, indent=2)
    if content_type == "application/pdf" or fn.endswith(".pdf"):
        return _extract_pdf_text(content)
    if "wordprocessingml" in content_type or fn.endswith((".docx", ".doc")):
        return _extract_docx_text(content)
    if content_type == "text/html" or fn.endswith(".html"):
        return _extract_html_text(content)
    return content.decode("utf-8", errors="ignore")


def _read_fixture(sample_docs_dir: Path, filename: str) -> bytes:
    path = sample_docs_dir / filename
    if not path.is_file():
        pytest.skip(f"Sample fixture missing: {path}")
    return path.read_bytes()


@pytest.mark.parametrize("filename,content_type", SAMPLE_CASES, ids=[c[0] for c in SAMPLE_CASES])
def test_extraction_quality(sample_docs_dir, filename, content_type):
    """Extraction produces non-empty text that passes quality checks."""
    raw = _read_fixture(sample_docs_dir, filename)

    text = _extract(raw, content_type, filename)

    # Non-empty extraction.
    assert text and text.strip(), f"Extraction produced empty text for {filename}"

    # Production quality gate: no critical failures.
    quality = DataQualityService()
    results = quality.check_extracted_text(text, filename)
    assert not quality.has_critical_failure(results), (
        f"Critical extraction quality failure for {filename}: "
        f"{[r.message for r in results if not r.passed and r.severity == 'critical']}"
    )

    # Simple fidelity metric: ratio of extracted text length to raw input size.
    # For text formats this is ~1.0; for PDF/DOCX it reflects how much readable
    # content survived the container overhead. We just require *some* signal.
    fidelity = len(text) / max(len(raw), 1)
    assert fidelity > 0, f"Zero fidelity for {filename}"
    print(
        f"[extract] {filename}: raw={len(raw)}B text={len(text)}chars " f"fidelity={fidelity:.4f}"
    )


@pytest.mark.parametrize("filename,content_type", SAMPLE_CASES, ids=[c[0] for c in SAMPLE_CASES])
def test_chunking_quality(sample_docs_dir, filename, content_type):
    """Chunking gives ~100% coverage, continuous indices, and passes checks."""
    raw = _read_fixture(sample_docs_dir, filename)
    text = _extract(raw, content_type, filename)
    assert text.strip(), f"No text to chunk for {filename}"

    # Use the production fixed-size chunker with a small size to force multiple
    # chunks for the larger fixtures. No overlap so coverage math is exact.
    max_size = 200
    chunks = _chunk_by_size(text, document_id=filename, max_size=max_size, overlap=0)
    assert chunks, f"Chunking produced 0 chunks for {filename}"

    # Continuous, zero-based chunk indices.
    indices = [c.chunk_index for c in chunks]
    assert indices == list(
        range(len(chunks))
    ), f"Chunk indices not continuous for {filename}: {indices}"

    # ~100% coverage: with no overlap, summed chunk lengths should equal the
    # text length minus only whitespace lost to per-chunk .strip(). Allow a
    # small tolerance for boundary stripping.
    summed = sum(len(c.content) for c in chunks)
    coverage = summed / max(len(text), 1)
    assert 0.90 <= coverage <= 1.05, (
        f"Chunk coverage out of tolerance for {filename}: {coverage:.4f} "
        f"(summed={summed}, text={len(text)})"
    )

    # Production quality gate: no critical failures.
    quality = DataQualityService()
    chunk_dicts = [{"content": c.content, "chunk_index": c.chunk_index} for c in chunks]
    results = quality.check_chunks(chunk_dicts, filename=filename)
    assert not quality.has_critical_failure(results), (
        f"Critical chunk quality failure for {filename}: "
        f"{[r.message for r in results if not r.passed and r.severity == 'critical']}"
    )
    print(
        f"[chunk] {filename}: text={len(text)}chars chunks={len(chunks)} "
        f"coverage={coverage:.4f}"
    )
