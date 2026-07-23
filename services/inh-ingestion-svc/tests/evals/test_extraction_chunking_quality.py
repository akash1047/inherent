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

from src.config.settings import Settings
from src.services.quality import DataQualityService
from src.temporal.activities.chunk import _chunk_by_size, _token_budget_char_cap, estimate_tokens
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

    # Eval-only hard fail on noisy extraction (REQ-EVL-2): production treats a
    # high whitespace ratio ("text_whitespace_ratio") as a non-blocking warning
    # -- a real document with unusual formatting shouldn't get rejected in
    # production. But a bundled golden fixture producing noisy output is a
    # regression in the extractor itself, not a property of unpredictable
    # input, so the eval holds it to a stricter bar than production severity
    # without changing DataQualityService's own "warning" classification.
    noisy = [r for r in results if not r.passed and r.check_name == "text_whitespace_ratio"]
    assert not noisy, (
        f"Noisy extraction output for {filename} (eval-only hard fail, "
        f"production severity unchanged): {[r.message for r in noisy]}"
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


@pytest.mark.parametrize("filename,content_type", SAMPLE_CASES, ids=[c[0] for c in SAMPLE_CASES])
def test_chunk_token_budget(sample_docs_dir, filename, content_type, test_settings: Settings):
    """No chunk exceeds the embedding model's token budget (REQ-EVL-2).

    Chunks with the same character cap ``chunk_text``'s inner impl derives
    from ``settings.embedding_max_tokens`` via ``_token_budget_char_cap``, so
    this exercises the actual budget the pipeline enforces rather than an
    arbitrary size -- a regression here means a real chunk could overrun the
    embedding model's token limit and get silently truncated by TEI.
    """
    raw = _read_fixture(sample_docs_dir, filename)
    text = _extract(raw, content_type, filename)
    assert text.strip(), f"No text to chunk for {filename}"

    settings = test_settings
    char_cap = _token_budget_char_cap(settings.embedding_max_tokens)
    chunks = _chunk_by_size(text, document_id=filename, max_size=char_cap, overlap=0)
    assert chunks, f"Chunking produced 0 chunks for {filename}"

    over_budget = [
        (c.chunk_index, estimate_tokens(c.content))
        for c in chunks
        if estimate_tokens(c.content) > settings.embedding_max_tokens
    ]
    assert not over_budget, (
        f"{len(over_budget)} chunk(s) exceed the {settings.embedding_max_tokens}-token "
        f"embedding budget for {filename}: {over_budget}"
    )
    print(
        f"[token-budget] {filename}: {len(chunks)} chunks, "
        f"max_tokens={max(estimate_tokens(c.content) for c in chunks)} "
        f"budget={settings.embedding_max_tokens}"
    )
