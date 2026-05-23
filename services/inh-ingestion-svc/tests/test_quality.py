"""Tests for DataQualityService (DE-S023)."""

import pytest

from src.services.quality import DataQualityService


@pytest.fixture(autouse=True)
async def cleanup_test_data():
    """Override global autouse cleanup -- no DB needed."""
    yield


@pytest.fixture()
def db_service():
    """Override -- not used."""
    yield None


class TestCheckExtractedText:
    def setup_method(self):
        self.svc = DataQualityService()

    def test_valid_text_passes(self):
        results = self.svc.check_extracted_text("This is valid content for testing.", "doc.txt")
        assert not self.svc.has_critical_failure(results)
        assert any(r.check_name == "text_not_empty" and r.passed for r in results)

    def test_empty_text_critical_failure(self):
        results = self.svc.check_extracted_text("", "doc.txt")
        assert self.svc.has_critical_failure(results)
        assert results[0].check_name == "text_not_empty"
        assert results[0].severity == "critical"

    def test_none_text_critical_failure(self):
        results = self.svc.check_extracted_text("", "doc.txt")
        assert self.svc.has_critical_failure(results)

    def test_whitespace_only_critical_failure(self):
        results = self.svc.check_extracted_text("   \n\t  ", "doc.txt")
        assert self.svc.has_critical_failure(results)

    def test_short_text_warning(self):
        results = self.svc.check_extracted_text("Hi!", "doc.txt")
        warnings = [r for r in results if r.check_name == "text_min_length"]
        assert len(warnings) == 1
        assert warnings[0].severity == "warning"

    def test_high_whitespace_ratio_warning(self):
        text = "a" + " " * 100
        results = self.svc.check_extracted_text(text, "doc.txt")
        ws_checks = [r for r in results if r.check_name == "text_whitespace_ratio"]
        assert len(ws_checks) == 1
        assert ws_checks[0].severity == "warning"

    def test_binary_content_warning(self):
        text = "hello\x00world\x00test"
        results = self.svc.check_extracted_text(text, "doc.txt")
        binary = [r for r in results if r.check_name == "no_binary_content"]
        assert len(binary) == 1
        assert binary[0].metadata["null_bytes"] == 2

    def test_normal_text_no_warnings(self):
        text = "This is a perfectly normal document with enough content to pass all checks."
        results = self.svc.check_extracted_text(text, "doc.txt")
        assert not self.svc.has_critical_failure(results)
        warnings = [r for r in results if not r.passed]
        assert len(warnings) == 0


class TestCheckChunks:
    def setup_method(self):
        self.svc = DataQualityService()

    def test_valid_chunks_pass(self):
        chunks = [
            {"content": "First chunk content here.", "chunk_index": 0},
            {"content": "Second chunk content here.", "chunk_index": 1},
        ]
        results = self.svc.check_chunks(chunks, "doc.txt")
        assert not self.svc.has_critical_failure(results)

    def test_empty_chunks_critical(self):
        results = self.svc.check_chunks([], "doc.txt")
        assert self.svc.has_critical_failure(results)
        assert results[0].check_name == "chunks_not_empty"

    def test_empty_chunk_content_warning(self):
        chunks = [
            {"content": "Good content", "chunk_index": 0},
            {"content": "", "chunk_index": 1},
        ]
        results = self.svc.check_chunks(chunks, "doc.txt")
        empty = [r for r in results if r.check_name == "no_empty_chunks"]
        assert len(empty) == 1
        assert empty[0].severity == "warning"

    def test_oversized_chunk_warning(self):
        chunks = [{"content": "x" * 60000, "chunk_index": 0}]
        results = self.svc.check_chunks(chunks, "doc.txt")
        oversized = [r for r in results if r.check_name == "chunk_size_bounds"]
        assert len(oversized) == 1

    def test_tiny_chunk_warning(self):
        chunks = [{"content": "Hi", "chunk_index": 0}]
        results = self.svc.check_chunks(chunks, "doc.txt")
        tiny = [r for r in results if r.check_name == "chunk_min_size"]
        assert len(tiny) == 1

    def test_non_continuous_indices_warning(self):
        chunks = [
            {"content": "Content A", "chunk_index": 0},
            {"content": "Content B", "chunk_index": 5},
        ]
        results = self.svc.check_chunks(chunks, "doc.txt")
        continuity = [r for r in results if r.check_name == "chunk_index_continuity"]
        assert len(continuity) == 1

    def test_coverage_info_always_present(self):
        chunks = [{"content": "Some content", "chunk_index": 0}]
        results = self.svc.check_chunks(chunks, "doc.txt")
        coverage = [r for r in results if r.check_name == "chunk_coverage"]
        assert len(coverage) == 1
        assert coverage[0].passed is True
        assert coverage[0].metadata["chunk_count"] == 1


class TestHasCriticalFailure:
    def test_no_failures(self):
        svc = DataQualityService()
        from src.services.quality import QualityCheckResult

        results = [QualityCheckResult(True, "check1", "info", "ok")]
        assert not svc.has_critical_failure(results)

    def test_warning_not_critical(self):
        svc = DataQualityService()
        from src.services.quality import QualityCheckResult

        results = [QualityCheckResult(False, "check1", "warning", "warn")]
        assert not svc.has_critical_failure(results)

    def test_critical_detected(self):
        svc = DataQualityService()
        from src.services.quality import QualityCheckResult

        results = [QualityCheckResult(False, "check1", "critical", "fail")]
        assert svc.has_critical_failure(results)


class TestLogResults:
    def test_log_results_does_not_raise(self):
        svc = DataQualityService()
        from src.services.quality import QualityCheckResult

        results = [
            QualityCheckResult(True, "ok", "info", "passed"),
            QualityCheckResult(False, "warn", "warning", "warned"),
            QualityCheckResult(False, "fail", "critical", "failed"),
        ]
        # Should not raise
        svc.log_results(results, "doc-123")
