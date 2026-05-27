"""Tests for Temporal activities.

Covers:
- extract_text: error propagation, empty text guard, format handling

Activities use shared_services getters, so we patch those instead of
constructing service instances directly.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.temporal.models import (
    ExtractTextInput,
    ExtractTextOutput,
)


# Override autouse fixtures from conftest that require a real database
@pytest.fixture(autouse=True)
async def cleanup_test_data():
    """Override to skip DB cleanup for activity tests."""
    yield


@pytest.fixture()
def db_service():
    """Override to return None (activity tests don't use DB directly)."""
    yield None


# =========================================================================
# extract_text activity tests
# =========================================================================


class TestExtractTextActivity:
    """Tests for the extract_text activity."""

    @pytest.fixture
    def extract_input(self):
        """Standard extract text input."""
        return ExtractTextInput(
            workflow_run_id="wf_test_001",
            storage_backend="local",
            storage_path="storage/doc.txt",
            content_type="text/plain",
            original_filename="doc.txt",
        )

    @patch("src.temporal.shared_services.get_staging_service")
    @patch("src.temporal.shared_services.get_storage_service")
    @pytest.mark.asyncio
    async def test_extract_text_plain_success(
        self, mock_get_storage, mock_get_staging, extract_input
    ):
        """Plain text extraction should succeed and write to staging."""
        mock_storage = MagicMock()
        mock_storage.read_file.return_value = b"Hello, world!"
        mock_get_storage.return_value = mock_storage

        mock_staging = MagicMock()
        mock_get_staging.return_value = mock_staging

        from src.temporal.activities.extract import extract_text

        result = await extract_text(extract_input)

        assert isinstance(result, ExtractTextOutput)
        assert result.text_length == 13
        mock_staging.write_text.assert_called_once_with("wf_test_001", "Hello, world!")

    @patch("src.temporal.shared_services.get_staging_service")
    @patch("src.temporal.shared_services.get_storage_service")
    @pytest.mark.asyncio
    async def test_extract_text_raises_on_empty_content(
        self, mock_get_storage, mock_get_staging, extract_input
    ):
        """Should raise RuntimeError when extraction yields empty text."""
        mock_storage = MagicMock()
        mock_storage.read_file.return_value = b"   \n   "
        mock_get_storage.return_value = mock_storage

        mock_staging = MagicMock()
        mock_get_staging.return_value = mock_staging

        from src.temporal.activities.extract import extract_text

        with pytest.raises(RuntimeError, match="quality check failed|empty"):
            await extract_text(extract_input)

        # Staging should NOT be written to on failure
        mock_staging.write_text.assert_not_called()

    @patch("src.temporal.shared_services.get_storage_service")
    @pytest.mark.asyncio
    async def test_extract_text_storage_failure_propagates(self, mock_get_storage, extract_input):
        """Storage read failure should propagate, not be silenced."""
        mock_storage = MagicMock()
        mock_storage.read_file.side_effect = FileNotFoundError("No such file")
        mock_get_storage.return_value = mock_storage

        from src.temporal.activities.extract import extract_text

        with pytest.raises(FileNotFoundError, match="No such file"):
            await extract_text(extract_input)

    @patch("src.temporal.shared_services.get_staging_service")
    @patch("src.temporal.shared_services.get_storage_service")
    @pytest.mark.asyncio
    async def test_extract_text_json_success(self, mock_get_storage, mock_get_staging):
        """JSON extraction should parse and pretty-print."""
        mock_storage = MagicMock()
        mock_storage.read_file.return_value = b'{"key": "value"}'
        mock_get_storage.return_value = mock_storage

        mock_staging = MagicMock()
        mock_get_staging.return_value = mock_staging

        input_data = ExtractTextInput(
            workflow_run_id="wf_json",
            storage_backend="local",
            storage_path="data.json",
            content_type="application/json",
            original_filename="data.json",
        )

        from src.temporal.activities.extract import extract_text

        result = await extract_text(input_data)

        assert result.text_length > 0
        written_text = mock_staging.write_text.call_args[0][1]
        assert '"key": "value"' in written_text

    @patch("src.temporal.shared_services.get_staging_service")
    @patch("src.temporal.shared_services.get_storage_service")
    @pytest.mark.asyncio
    async def test_extract_text_xlsx_raises_until_supported(
        self, mock_get_storage, mock_get_staging
    ):
        """Spreadsheet binaries should fail explicitly until XLSX extraction exists."""
        mock_storage = MagicMock()
        mock_storage.read_file.return_value = b"PK\x03\x04fake workbook bytes"
        mock_get_storage.return_value = mock_storage

        mock_staging = MagicMock()
        mock_get_staging.return_value = mock_staging

        input_data = ExtractTextInput(
            workflow_run_id="wf_xlsx",
            storage_backend="local",
            storage_path="sheet.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            original_filename="sheet.xlsx",
        )

        from src.temporal.activities.extract import extract_text

        with pytest.raises(RuntimeError, match="Unsupported spreadsheet"):
            await extract_text(input_data)

        mock_staging.write_text.assert_not_called()

    @patch("src.temporal.shared_services.get_storage_service")
    @pytest.mark.asyncio
    async def test_extract_text_azure_without_url_raises(self, mock_get_storage):
        """Azure backend without storage_url should raise."""
        mock_get_storage.return_value = MagicMock()

        input_data = ExtractTextInput(
            workflow_run_id="wf_azure",
            storage_backend="azure",
            storage_path="doc.txt",
            content_type="text/plain",
            original_filename="doc.txt",
        )

        from src.temporal.activities.extract import extract_text

        with pytest.raises(RuntimeError, match="requires storage_url"):
            await extract_text(input_data)


class TestExtractHelpers:
    """Tests for format-specific extraction helpers."""

    def test_extract_pdf_text_with_pypdf(self):
        """PDF extraction should work with pypdf."""
        import io

        from src.temporal.activities.extract import _extract_pdf_text

        try:
            import pypdf

            # Use a real but minimal PDF to test the path
            writer = pypdf.PdfWriter()
            writer.add_blank_page(width=72, height=72)
            buf = io.BytesIO()
            writer.write(buf)
            pdf_bytes = buf.getvalue()

            result = _extract_pdf_text(pdf_bytes)
            # Blank page produces empty text — that's valid for the helper
            assert isinstance(result, str)
        except ImportError:
            pytest.skip("pypdf not installed")

    def test_extract_html_text_with_beautifulsoup(self):
        """HTML extraction should strip tags."""
        from src.temporal.activities.extract import _extract_html_text

        html = b"<html><body><p>Hello</p><script>alert('x')</script></body></html>"

        try:
            from bs4 import BeautifulSoup  # noqa: F401

            result = _extract_html_text(html)
            assert "Hello" in result
            assert "alert" not in result
        except ImportError:
            # Without bs4, fallback returns raw content
            result = _extract_html_text(html)
            assert "Hello" in result


# =========================================================================
# Model tests
# =========================================================================


class TestUpdatedModels:
    """Tests for updated dataclass models."""

    def test_update_stats_input_has_workflow_run_id(self):
        """UpdateStatsInput should accept optional workflow_run_id."""
        from src.temporal.models import UpdateStatsInput

        # Without workflow_run_id (backwards compatible)
        input1 = UpdateStatsInput(
            workspace_id="ws_1",
            document_delta=1,
            chunk_delta=10,
            size_delta=1000,
        )
        assert input1.workflow_run_id is None

        # With workflow_run_id
        input2 = UpdateStatsInput(
            workspace_id="ws_1",
            document_delta=1,
            chunk_delta=10,
            size_delta=1000,
            workflow_run_id="wf_abc123",
        )
        assert input2.workflow_run_id == "wf_abc123"
