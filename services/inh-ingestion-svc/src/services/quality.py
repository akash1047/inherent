"""Data quality checks for the ingestion pipeline.

Validates data at key pipeline stages (extraction, chunking) to catch
quality issues early. Critical failures raise exceptions (retried by
Temporal); warnings are logged but do not stop the pipeline.
"""

from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class QualityCheckResult:
    """Result of a single data quality check."""

    passed: bool
    check_name: str
    severity: str  # "critical", "warning", "info"
    message: str
    metadata: dict | None = None


class DataQualityService:
    """Validates data quality at each pipeline stage."""

    # --- Text Quality Checks (after extraction) ---

    def check_extracted_text(self, text: str, filename: str) -> list[QualityCheckResult]:
        """Run all text quality checks after extraction.

        Args:
            text: The extracted text content.
            filename: Original filename for context in messages.

        Returns:
            List of QualityCheckResult for each check run.
        """
        results: list[QualityCheckResult] = []

        # 1. Empty text check (critical)
        if not text or not text.strip():
            results.append(
                QualityCheckResult(
                    passed=False,
                    check_name="text_not_empty",
                    severity="critical",
                    message=f"Extracted text is empty for {filename}",
                )
            )
            return results  # No point checking further

        results.append(
            QualityCheckResult(
                passed=True,
                check_name="text_not_empty",
                severity="info",
                message="Text extraction produced content",
            )
        )

        # 2. Minimum length check (warning)
        stripped_len = len(text.strip())
        if stripped_len < 10:
            results.append(
                QualityCheckResult(
                    passed=False,
                    check_name="text_min_length",
                    severity="warning",
                    message=(
                        f"Extracted text suspiciously short ({stripped_len} chars) for {filename}"
                    ),
                    metadata={"char_count": stripped_len},
                )
            )

        # 3. High whitespace ratio (warning) -- may indicate bad extraction
        non_ws = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))
        if len(text) > 0 and non_ws / len(text) < 0.3:
            ws_pct = 100 - int(non_ws / len(text) * 100)
            results.append(
                QualityCheckResult(
                    passed=False,
                    check_name="text_whitespace_ratio",
                    severity="warning",
                    message=f"Text is {ws_pct}% whitespace -- possible extraction issue",
                    metadata={"whitespace_ratio": round(1 - non_ws / len(text), 2)},
                )
            )

        # 4. Binary content detection (warning)
        null_count = text.count("\x00")
        if null_count > 0:
            results.append(
                QualityCheckResult(
                    passed=False,
                    check_name="no_binary_content",
                    severity="warning",
                    message=f"Text contains {null_count} null bytes -- may be binary",
                    metadata={"null_bytes": null_count},
                )
            )

        return results

    # --- Chunk Quality Checks (after chunking) ---

    def check_chunks(self, chunks: list[dict], filename: str) -> list[QualityCheckResult]:
        """Run all chunk quality checks after chunking.

        Args:
            chunks: List of chunk dicts with at least 'content' and 'chunk_index' keys.
            filename: Original filename for context in messages.

        Returns:
            List of QualityCheckResult for each check run.
        """
        results: list[QualityCheckResult] = []

        # 1. Non-empty chunks list (critical)
        if not chunks:
            results.append(
                QualityCheckResult(
                    passed=False,
                    check_name="chunks_not_empty",
                    severity="critical",
                    message=f"Chunking produced 0 chunks for {filename}",
                )
            )
            return results

        # 2. All chunks have content (warning)
        empty_chunks = [c for c in chunks if not c.get("content", "").strip()]
        if empty_chunks:
            results.append(
                QualityCheckResult(
                    passed=False,
                    check_name="no_empty_chunks",
                    severity="warning",
                    message=f"{len(empty_chunks)} of {len(chunks)} chunks are empty",
                    metadata={"empty_indices": [c.get("chunk_index") for c in empty_chunks]},
                )
            )

        # 3. Chunk size bounds (warning) -- no chunk should be > 50k chars or < 5 chars
        oversized = [c for c in chunks if len(c.get("content", "")) > 50000]
        tiny = [c for c in chunks if 0 < len(c.get("content", "").strip()) < 5]
        if oversized:
            results.append(
                QualityCheckResult(
                    passed=False,
                    check_name="chunk_size_bounds",
                    severity="warning",
                    message=f"{len(oversized)} chunks exceed 50k chars",
                    metadata={"oversized_count": len(oversized)},
                )
            )
        if tiny:
            results.append(
                QualityCheckResult(
                    passed=False,
                    check_name="chunk_min_size",
                    severity="warning",
                    message=f"{len(tiny)} chunks are < 5 chars",
                    metadata={"tiny_count": len(tiny)},
                )
            )

        # 4. Chunk index continuity (warning)
        indices = sorted(c.get("chunk_index", 0) for c in chunks)
        expected = list(range(len(chunks)))
        if indices != expected:
            results.append(
                QualityCheckResult(
                    passed=False,
                    check_name="chunk_index_continuity",
                    severity="warning",
                    message=f"Chunk indices not continuous: {indices[:5]}...",
                    metadata={"actual_indices": indices[:10]},
                )
            )

        # 5. Total content coverage (info)
        total_chars = sum(len(c.get("content", "")) for c in chunks)
        results.append(
            QualityCheckResult(
                passed=True,
                check_name="chunk_coverage",
                severity="info",
                message=f"{len(chunks)} chunks, {total_chars} total chars",
                metadata={"chunk_count": len(chunks), "total_chars": total_chars},
            )
        )

        return results

    def has_critical_failure(self, results: list[QualityCheckResult]) -> bool:
        """Check if any result is a critical failure.

        Args:
            results: List of quality check results to inspect.

        Returns:
            True if at least one result is a failed critical check.
        """
        return any(not r.passed and r.severity == "critical" for r in results)

    def log_results(self, results: list[QualityCheckResult], document_id: str) -> None:
        """Log all quality check results at the appropriate level.

        Args:
            results: List of quality check results.
            document_id: Document identifier for structured log context.
        """
        for r in results:
            if not r.passed and r.severity == "critical":
                logger.error(
                    "Quality check FAILED",
                    check=r.check_name,
                    document_id=document_id,
                    message=r.message,
                    metadata=r.metadata,
                )
            elif not r.passed and r.severity == "warning":
                logger.warning(
                    "Quality check warning",
                    check=r.check_name,
                    document_id=document_id,
                    message=r.message,
                    metadata=r.metadata,
                )
            else:
                logger.debug(
                    "Quality check passed",
                    check=r.check_name,
                    document_id=document_id,
                )
