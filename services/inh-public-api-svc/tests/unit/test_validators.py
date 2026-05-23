"""Unit tests for input validators."""

from src.utils.validators import (
    is_safe_path,
    sanitize_search_query,
    sanitize_string,
    validate_document_id,
    validate_uuid,
    validate_workspace_id,
)


class TestSanitizeSearchQuery:
    """Tests for sanitize_search_query."""

    def test_strips_whitespace(self):
        """Should strip leading and trailing whitespace."""
        assert sanitize_search_query("  hello  ") == "hello"

    def test_collapses_whitespace(self):
        """Should collapse multiple whitespace to single space."""
        assert sanitize_search_query("hello   world") == "hello world"

    def test_removes_control_characters(self):
        """Should remove control characters."""
        assert sanitize_search_query("hello\x00world") == "helloworld"

    def test_preserves_newlines_tabs(self):
        """Should preserve newlines and tabs."""
        assert sanitize_search_query("hello\tworld") == "hello world"

    def test_truncates_long_query(self):
        """Should truncate queries exceeding max length."""
        long_query = "x" * 2000
        result = sanitize_search_query(long_query)
        assert len(result) == 1000

    def test_empty_string(self):
        """Should handle empty string."""
        assert sanitize_search_query("") == ""

    def test_unicode_normalization(self):
        """Should normalize unicode."""
        # Combining character should be normalized
        result = sanitize_search_query("cafe\u0301")  # e + combining acute
        assert result == "caf\u00e9"  # e with acute


class TestValidateUuid:
    """Tests for validate_uuid."""

    def test_valid_uuid(self):
        """Should return True for valid UUID."""
        assert validate_uuid("550e8400-e29b-41d4-a716-446655440000") is True

    def test_valid_uuid_uppercase(self):
        """Should return True for uppercase UUID."""
        assert validate_uuid("550E8400-E29B-41D4-A716-446655440000") is True

    def test_invalid_uuid(self):
        """Should return False for invalid UUID."""
        assert validate_uuid("not-a-uuid") is False

    def test_empty_string(self):
        """Should return False for empty string."""
        assert validate_uuid("") is False

    def test_none(self):
        """Should return False for None."""
        assert validate_uuid(None) is False


class TestValidateDocumentId:
    """Tests for validate_document_id."""

    def test_valid_uuid(self):
        """Should return True for valid UUID."""
        assert validate_document_id("550e8400-e29b-41d4-a716-446655440000") is True

    def test_valid_objectid(self):
        """Should return True for valid MongoDB ObjectId."""
        assert validate_document_id("507f1f77bcf86cd799439011") is True

    def test_invalid_id(self):
        """Should return False for invalid ID."""
        assert validate_document_id("invalid") is False

    def test_empty_string(self):
        """Should return False for empty string."""
        assert validate_document_id("") is False


class TestValidateWorkspaceId:
    """Tests for validate_workspace_id."""

    def test_valid_uuid(self):
        """Should return True for valid UUID."""
        assert validate_workspace_id("550e8400-e29b-41d4-a716-446655440000") is True

    def test_valid_objectid(self):
        """Should return True for valid MongoDB ObjectId."""
        assert validate_workspace_id("507f1f77bcf86cd799439011") is True

    def test_invalid_id(self):
        """Should return False for invalid ID."""
        assert validate_workspace_id("invalid") is False


class TestSanitizeString:
    """Tests for sanitize_string."""

    def test_strips_whitespace(self):
        """Should strip whitespace."""
        assert sanitize_string("  hello  ") == "hello"

    def test_removes_control_characters(self):
        """Should remove control characters."""
        assert sanitize_string("hello\x00world") == "helloworld"

    def test_truncates_to_max_length(self):
        """Should truncate to max length."""
        result = sanitize_string("hello world", max_length=5)
        assert result == "hello"

    def test_default_max_length(self):
        """Should use default max length of 255."""
        long_string = "x" * 300
        result = sanitize_string(long_string)
        assert len(result) == 255


class TestIsSafePath:
    """Tests for is_safe_path."""

    def test_safe_path(self):
        """Should return True for safe relative path."""
        assert is_safe_path("folder/file.txt") is True

    def test_directory_traversal(self):
        """Should return False for directory traversal."""
        assert is_safe_path("../etc/passwd") is False
        assert is_safe_path("folder/../etc/passwd") is False

    def test_absolute_path_unix(self):
        """Should return False for Unix absolute path."""
        assert is_safe_path("/etc/passwd") is False

    def test_absolute_path_windows(self):
        """Should return False for Windows absolute path."""
        assert is_safe_path("C:\\Windows\\System32") is False

    def test_empty_path(self):
        """Should return False for empty path."""
        assert is_safe_path("") is False
