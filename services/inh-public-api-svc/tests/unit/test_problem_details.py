"""Unit tests for RFC 7807 Problem Details."""

from src.core.exceptions import AuthenticationError, RateLimitError
from src.core.problem_details import ProblemDetail, create_problem_detail, from_exception


class TestProblemDetail:
    """Tests for ProblemDetail model."""

    def test_required_fields(self):
        """Should require type, title, status, detail."""
        problem = ProblemDetail(
            type="https://api.inherent.systems/errors/test",
            title="Test Error",
            status=400,
            detail="Test detail message",
        )
        assert problem.type == "https://api.inherent.systems/errors/test"
        assert problem.title == "Test Error"
        assert problem.status == 400
        assert problem.detail == "Test detail message"

    def test_optional_fields(self):
        """Should have optional fields with defaults."""
        problem = ProblemDetail(
            type="https://api.inherent.systems/errors/test",
            title="Test Error",
            status=400,
            detail="Test detail",
        )
        assert problem.instance is None
        assert problem.trace_id is None
        assert problem.timestamp is not None  # Auto-generated

    def test_to_dict_basic(self):
        """Should convert to dict without extensions."""
        problem = ProblemDetail(
            type="https://api.inherent.systems/errors/test",
            title="Test Error",
            status=400,
            detail="Test detail",
            instance="/v1/test",
            trace_id="abc-123",
        )
        result = problem.to_dict()
        assert result["type"] == "https://api.inherent.systems/errors/test"
        assert result["title"] == "Test Error"
        assert result["status"] == 400
        assert result["detail"] == "Test detail"
        assert result["instance"] == "/v1/test"
        assert result["trace_id"] == "abc-123"
        assert "timestamp" in result

    def test_to_dict_with_extensions(self):
        """Should merge extensions at top level."""
        problem = ProblemDetail(
            type="https://api.inherent.systems/errors/test",
            title="Test Error",
            status=400,
            detail="Test detail",
        )
        result = problem.to_dict(extensions={"retry_after": 30, "limit": 100})
        assert result["retry_after"] == 30
        assert result["limit"] == 100


class TestCreateProblemDetail:
    """Tests for create_problem_detail function."""

    def test_creates_valid_problem_detail(self):
        """Should create valid problem detail dict."""
        result = create_problem_detail(
            error_key="authentication_failed",
            status=401,
            detail="Invalid API key",
            instance="/v1/search",
            trace_id="trace-123",
        )
        assert result["type"] == "https://api.inherent.systems/errors/authentication-failed"
        assert result["title"] == "Authentication Failed"
        assert result["status"] == 401
        assert result["detail"] == "Invalid API key"
        assert result["instance"] == "/v1/search"
        assert result["trace_id"] == "trace-123"

    def test_includes_extensions(self):
        """Should include extensions in result."""
        result = create_problem_detail(
            error_key="rate_limit_exceeded",
            status=429,
            detail="Rate limit exceeded",
            extensions={"retry_after": 60},
        )
        assert result["retry_after"] == 60

    def test_unknown_error_key_falls_back(self):
        """Should fall back to internal_error for unknown keys."""
        result = create_problem_detail(
            error_key="unknown_key",
            status=500,
            detail="Unknown error",
        )
        assert "internal" in result["type"]


class TestFromException:
    """Tests for from_exception function."""

    def test_converts_authentication_error(self):
        """Should convert AuthenticationError to problem detail."""
        exc = AuthenticationError(detail="API key expired")
        result = from_exception(exc, instance="/v1/search", trace_id="trace-456")

        assert result["type"] == "https://api.inherent.systems/errors/authentication-failed"
        assert result["title"] == "Authentication Failed"
        assert result["status"] == 401
        assert result["detail"] == "API key expired"
        assert result["instance"] == "/v1/search"
        assert result["trace_id"] == "trace-456"

    def test_converts_rate_limit_error_with_extensions(self):
        """Should include extensions from RateLimitError."""
        exc = RateLimitError(
            detail="Rate limit exceeded",
            retry_after=30,
            limit=100,
            remaining=0,
        )
        result = from_exception(exc)

        assert result["status"] == 429
        assert result["retry_after"] == 30
        assert result["limit"] == 100
        assert result["remaining"] == 0

    def test_converts_generic_exception(self):
        """Should convert generic Exception to internal error."""
        exc = ValueError("Something went wrong")
        result = from_exception(exc)

        assert result["status"] == 500
        assert "internal" in result["type"]
        assert "Something went wrong" in result["detail"]
