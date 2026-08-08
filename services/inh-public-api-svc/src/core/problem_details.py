"""RFC 7807 Problem Details implementation.

This module provides a standard format for HTTP API error responses
as defined in RFC 7807 (https://tools.ietf.org/html/rfc7807).
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from src.config import settings
from src.config.constants import ERROR_TITLES, ERROR_TYPE_SLUGS


class ProblemDetail(BaseModel):
    """RFC 7807 Problem Details response model.

    Attributes:
        type: A URI reference that identifies the problem type.
        title: A short, human-readable summary of the problem.
        status: The HTTP status code.
        detail: A human-readable explanation specific to this occurrence.
        instance: A URI reference that identifies the specific occurrence.
        trace_id: Request correlation ID for debugging.
        timestamp: ISO 8601 timestamp of when the error occurred.
        extensions: Additional problem-specific properties.
    """

    type: str = Field(
        ...,
        description="URI reference identifying the problem type",
        json_schema_extra={"example": f"{settings.error_base_url}/rate-limit-exceeded"},
    )
    title: str = Field(
        ...,
        description="Short, human-readable summary",
        json_schema_extra={"example": "Rate Limit Exceeded"},
    )
    status: int = Field(
        ...,
        description="HTTP status code",
        json_schema_extra={"example": 429},
    )
    detail: str = Field(
        ...,
        description="Human-readable explanation",
        json_schema_extra={
            "example": "You have exceeded your rate limit of 100 requests per minute."
        },
    )
    instance: str | None = Field(
        default=None,
        description="URI reference identifying the specific occurrence",
        json_schema_extra={"example": "/v1/search"},
    )
    trace_id: str | None = Field(
        default=None,
        description="Request correlation ID for debugging",
        json_schema_extra={"example": "550e8400-e29b-41d4-a716-446655440000"},
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "type": f"{settings.error_base_url}/rate-limit-exceeded",
                "title": "Rate Limit Exceeded",
                "status": 429,
                "detail": "You have exceeded your rate limit of 100 requests per minute.",
                "instance": "/v1/search",
                "trace_id": "550e8400-e29b-41d4-a716-446655440000",
                "timestamp": "2024-01-08T12:00:00.000Z",
            }
        }
    }

    def to_dict(self, extensions: dict[str, Any] | None = None) -> dict[str, Any]:
        """Convert to dictionary with optional extensions.

        Extensions are merged at the top level per RFC 7807.
        """
        result = self.model_dump(exclude_none=True)
        if extensions:
            # Extensions are added as top-level properties per RFC 7807
            result.update(extensions)
        return result


def _build_error_type(error_key: str) -> str:
    """Build the RFC 7807 `type` URI for an error key from LIVE configuration (#222).

    Reads settings.error_base_url at call time -- not a frozen module-level
    dict -- so an ERROR_BASE_URL env var override (prod api.inherent.sh vs dev
    dev-api.inherent.sh, or a future domain) reaches every served response
    with a single setting, never a grep across constants.py.
    """
    slug = ERROR_TYPE_SLUGS.get(error_key, ERROR_TYPE_SLUGS["internal_error"])
    return f"{settings.error_base_url}/{slug}"


def create_problem_detail(
    error_key: str,
    status: int,
    detail: str,
    instance: str | None = None,
    trace_id: str | None = None,
    extensions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a Problem Details response dictionary.

    Args:
        error_key: Key for ERROR_TYPE_SLUGS and ERROR_TITLES lookup.
        status: HTTP status code.
        detail: Human-readable error description.
        instance: Request path or URI.
        trace_id: Request correlation ID.
        extensions: Additional context to include.

    Returns:
        Dictionary suitable for JSON response.
    """
    problem = ProblemDetail(
        type=_build_error_type(error_key),
        title=ERROR_TITLES.get(error_key, ERROR_TITLES["internal_error"]),
        status=status,
        detail=detail,
        instance=instance,
        trace_id=trace_id,
    )
    return problem.to_dict(extensions)


def from_exception(
    exc: "InherentAPIError",  # noqa: F821 - Forward reference
    instance: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Create Problem Details from an InherentAPIError.

    Args:
        exc: The exception to convert.
        instance: Request path or URI.
        trace_id: Request correlation ID.

    Returns:
        Dictionary suitable for JSON response.
    """
    # Import here to avoid circular imports
    from src.core.exceptions import InherentAPIError

    if not isinstance(exc, InherentAPIError):
        return create_problem_detail(
            error_key="internal_error",
            status=500,
            detail=str(exc),
            instance=instance,
            trace_id=trace_id,
        )

    problem = ProblemDetail(
        # Built from exc.error_key + the LIVE configured base (_build_error_type),
        # not exc.error_type -- the latter is a static snapshot from
        # src/config/constants.py (see its docstring) that can't see a
        # settings.error_base_url override. Every served response must reflect
        # the live config; only the exception class's own property is static.
        type=_build_error_type(exc.error_key),
        title=exc.title,
        status=exc.status_code,
        detail=exc.detail,
        instance=instance,
        trace_id=trace_id,
    )
    return problem.to_dict(exc.extensions)
