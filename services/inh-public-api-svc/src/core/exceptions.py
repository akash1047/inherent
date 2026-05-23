"""Custom exception hierarchy for the public API.

All exceptions inherit from InherentAPIError and map to specific HTTP status codes
and RFC 7807 Problem Details error types.
"""

from typing import Any

from src.config.constants import ERROR_TITLES, ERROR_TYPES


class InherentAPIError(Exception):
    """Base exception for all API errors.

    Attributes:
        status_code: HTTP status code for this error.
        error_type: RFC 7807 error type URL.
        title: Human-readable error title.
        detail: Detailed error description.
        extensions: Additional error context.
    """

    status_code: int = 500
    error_key: str = "internal_error"

    def __init__(
        self,
        detail: str | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> None:
        self.detail = detail or self.default_detail
        self.extensions = extensions or {}
        super().__init__(self.detail)

    @property
    def default_detail(self) -> str:
        return "An unexpected error occurred."

    @property
    def error_type(self) -> str:
        return ERROR_TYPES.get(self.error_key, ERROR_TYPES["internal_error"])

    @property
    def title(self) -> str:
        return ERROR_TITLES.get(self.error_key, ERROR_TITLES["internal_error"])


class AuthenticationError(InherentAPIError):
    """401 Unauthorized - Invalid or missing API key."""

    status_code = 401
    error_key = "authentication_failed"

    @property
    def default_detail(self) -> str:
        return "Invalid or missing API key."


class AuthorizationError(InherentAPIError):
    """403 Forbidden - Missing required permission."""

    status_code = 403
    error_key = "authorization_failed"

    @property
    def default_detail(self) -> str:
        return "You do not have permission to perform this action."


class RateLimitError(InherentAPIError):
    """429 Too Many Requests - Rate limit exceeded."""

    status_code = 429
    error_key = "rate_limit_exceeded"

    def __init__(
        self,
        detail: str | None = None,
        retry_after: int | None = None,
        limit: int | None = None,
        remaining: int = 0,
        extensions: dict[str, Any] | None = None,
    ) -> None:
        ext = extensions or {}
        if retry_after is not None:
            ext["retry_after"] = retry_after
        if limit is not None:
            ext["limit"] = limit
        ext["remaining"] = remaining
        super().__init__(detail=detail, extensions=ext)
        self.retry_after = retry_after

    @property
    def default_detail(self) -> str:
        return "You have exceeded your rate limit. Please try again later."


class ResourceNotFoundError(InherentAPIError):
    """404 Not Found - Requested resource not found."""

    status_code = 404
    error_key = "resource_not_found"

    def __init__(
        self,
        resource_type: str | None = None,
        resource_id: str | None = None,
        detail: str | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> None:
        ext = extensions or {}
        if resource_type:
            ext["resource_type"] = resource_type
        if resource_id:
            ext["resource_id"] = resource_id
        super().__init__(detail=detail, extensions=ext)

    @property
    def default_detail(self) -> str:
        return "The requested resource was not found."


class ValidationError(InherentAPIError):
    """422 Unprocessable Entity - Request validation failed."""

    status_code = 422
    error_key = "validation_error"

    def __init__(
        self,
        detail: str | None = None,
        errors: list[dict[str, Any]] | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> None:
        ext = extensions or {}
        if errors:
            ext["errors"] = errors
        super().__init__(detail=detail, extensions=ext)

    @property
    def default_detail(self) -> str:
        return "Request validation failed."


class ServiceUnavailableError(InherentAPIError):
    """503 Service Unavailable - Dependency or service unavailable."""

    status_code = 503
    error_key = "service_unavailable"

    def __init__(
        self,
        service_name: str | None = None,
        detail: str | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> None:
        ext = extensions or {}
        if service_name:
            ext["service"] = service_name
        super().__init__(detail=detail, extensions=ext)

    @property
    def default_detail(self) -> str:
        return "Service temporarily unavailable. Please try again later."


class BadRequestError(InherentAPIError):
    """400 Bad Request - Malformed request."""

    status_code = 400
    error_key = "bad_request"

    @property
    def default_detail(self) -> str:
        return "The request could not be understood or was missing required parameters."
