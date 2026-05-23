"""Unit tests for custom exceptions."""

from src.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
    InherentAPIError,
    RateLimitError,
    ResourceNotFoundError,
    ServiceUnavailableError,
    ValidationError,
)


class TestInherentAPIError:
    """Tests for base InherentAPIError."""

    def test_default_values(self):
        """Should have correct default values."""
        error = InherentAPIError()
        assert error.status_code == 500
        assert error.error_key == "internal_error"
        assert "unexpected error" in error.detail.lower()

    def test_custom_detail(self):
        """Should accept custom detail message."""
        error = InherentAPIError(detail="Custom error message")
        assert error.detail == "Custom error message"

    def test_extensions(self):
        """Should accept extensions dictionary."""
        error = InherentAPIError(extensions={"key": "value"})
        assert error.extensions == {"key": "value"}

    def test_error_type_url(self):
        """Should have valid error type URL."""
        error = InherentAPIError()
        assert error.error_type.startswith("https://api.inherent.systems/errors/")

    def test_title(self):
        """Should have human-readable title."""
        error = InherentAPIError()
        assert error.title == "Internal Server Error"


class TestAuthenticationError:
    """Tests for AuthenticationError."""

    def test_status_code(self):
        """Should have 401 status code."""
        error = AuthenticationError()
        assert error.status_code == 401

    def test_error_key(self):
        """Should have correct error key."""
        error = AuthenticationError()
        assert error.error_key == "authentication_failed"

    def test_default_detail(self):
        """Should have appropriate default detail."""
        error = AuthenticationError()
        assert "api key" in error.detail.lower()


class TestAuthorizationError:
    """Tests for AuthorizationError."""

    def test_status_code(self):
        """Should have 403 status code."""
        error = AuthorizationError()
        assert error.status_code == 403

    def test_error_key(self):
        """Should have correct error key."""
        error = AuthorizationError()
        assert error.error_key == "authorization_failed"


class TestRateLimitError:
    """Tests for RateLimitError."""

    def test_status_code(self):
        """Should have 429 status code."""
        error = RateLimitError()
        assert error.status_code == 429

    def test_retry_after(self):
        """Should store retry_after in extensions."""
        error = RateLimitError(retry_after=30)
        assert error.extensions["retry_after"] == 30
        assert error.retry_after == 30

    def test_limit_and_remaining(self):
        """Should store limit and remaining in extensions."""
        error = RateLimitError(limit=100, remaining=0)
        assert error.extensions["limit"] == 100
        assert error.extensions["remaining"] == 0


class TestResourceNotFoundError:
    """Tests for ResourceNotFoundError."""

    def test_status_code(self):
        """Should have 404 status code."""
        error = ResourceNotFoundError()
        assert error.status_code == 404

    def test_resource_info_in_extensions(self):
        """Should store resource info in extensions."""
        error = ResourceNotFoundError(resource_type="document", resource_id="123")
        assert error.extensions["resource_type"] == "document"
        assert error.extensions["resource_id"] == "123"


class TestValidationError:
    """Tests for ValidationError."""

    def test_status_code(self):
        """Should have 422 status code."""
        error = ValidationError()
        assert error.status_code == 422

    def test_errors_in_extensions(self):
        """Should store validation errors in extensions."""
        errors = [{"field": "name", "message": "required"}]
        error = ValidationError(errors=errors)
        assert error.extensions["errors"] == errors


class TestServiceUnavailableError:
    """Tests for ServiceUnavailableError."""

    def test_status_code(self):
        """Should have 503 status code."""
        error = ServiceUnavailableError()
        assert error.status_code == 503

    def test_service_name_in_extensions(self):
        """Should store service name in extensions."""
        error = ServiceUnavailableError(service_name="database")
        assert error.extensions["service"] == "database"


class TestBadRequestError:
    """Tests for BadRequestError."""

    def test_status_code(self):
        """Should have 400 status code."""
        error = BadRequestError()
        assert error.status_code == 400

    def test_error_key(self):
        """Should have correct error key."""
        error = BadRequestError()
        assert error.error_key == "bad_request"
