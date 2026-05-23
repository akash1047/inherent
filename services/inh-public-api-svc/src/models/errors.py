"""Error response models for API documentation."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """RFC 7807 Problem Details error response.

    Used for OpenAPI documentation of error responses.
    """

    type: str = Field(
        ...,
        description="URI reference identifying the problem type",
        json_schema_extra={"example": "https://api.inherent.systems/errors/authentication-failed"},
    )
    title: str = Field(
        ...,
        description="Short, human-readable summary",
        json_schema_extra={"example": "Authentication Failed"},
    )
    status: int = Field(
        ...,
        description="HTTP status code",
        json_schema_extra={"example": 401},
    )
    detail: str = Field(
        ...,
        description="Human-readable explanation",
        json_schema_extra={"example": "Invalid or missing API key."},
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
        ...,
        description="ISO 8601 timestamp",
        json_schema_extra={"example": "2024-01-08T12:00:00.000Z"},
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "https://api.inherent.systems/errors/authentication-failed",
                "title": "Authentication Failed",
                "status": 401,
                "detail": "Invalid or missing API key.",
                "instance": "/v1/search",
                "trace_id": "550e8400-e29b-41d4-a716-446655440000",
                "timestamp": "2024-01-08T12:00:00.000Z",
            }
        }
    }


class ValidationErrorDetail(BaseModel):
    """Individual validation error detail."""

    loc: list[str | int] = Field(
        ...,
        description="Location of the error in the request",
        json_schema_extra={"example": ["body", "query"]},
    )
    msg: str = Field(
        ...,
        description="Error message",
        json_schema_extra={"example": "field required"},
    )
    type: str = Field(
        ...,
        description="Error type",
        json_schema_extra={"example": "value_error.missing"},
    )


class ValidationErrorResponse(ErrorResponse):
    """Validation error response with field-level errors."""

    errors: list[ValidationErrorDetail] | None = Field(
        default=None,
        description="List of validation errors",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "https://api.inherent.systems/errors/validation-error",
                "title": "Validation Error",
                "status": 422,
                "detail": "Request validation failed.",
                "instance": "/v1/search",
                "trace_id": "550e8400-e29b-41d4-a716-446655440000",
                "timestamp": "2024-01-08T12:00:00.000Z",
                "errors": [
                    {
                        "loc": ["body", "query"],
                        "msg": "field required",
                        "type": "value_error.missing",
                    }
                ],
            }
        }
    }


class RateLimitErrorResponse(ErrorResponse):
    """Rate limit exceeded error response."""

    retry_after: int = Field(
        ...,
        description="Seconds to wait before retrying",
        json_schema_extra={"example": 45},
    )
    limit: int = Field(
        ...,
        description="Request limit per window",
        json_schema_extra={"example": 100},
    )
    remaining: int = Field(
        ...,
        description="Requests remaining in current window",
        json_schema_extra={"example": 0},
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "https://api.inherent.systems/errors/rate-limit-exceeded",
                "title": "Rate Limit Exceeded",
                "status": 429,
                "detail": "You have exceeded your rate limit of 100 requests per minute.",
                "instance": "/v1/search",
                "trace_id": "550e8400-e29b-41d4-a716-446655440000",
                "timestamp": "2024-01-08T12:00:00.000Z",
                "retry_after": 45,
                "limit": 100,
                "remaining": 0,
            }
        }
    }


# Common response types for OpenAPI documentation
ERROR_RESPONSES: dict[int, dict[str, Any]] = {
    400: {
        "model": ErrorResponse,
        "description": "Bad Request - Malformed request syntax",
    },
    401: {
        "model": ErrorResponse,
        "description": "Unauthorized - Invalid or missing API key",
    },
    403: {
        "model": ErrorResponse,
        "description": "Forbidden - Missing required permission",
    },
    404: {
        "model": ErrorResponse,
        "description": "Not Found - Resource not found",
    },
    422: {
        "model": ValidationErrorResponse,
        "description": "Validation Error - Request validation failed",
    },
    429: {
        "model": RateLimitErrorResponse,
        "description": "Too Many Requests - Rate limit exceeded",
    },
    500: {
        "model": ErrorResponse,
        "description": "Internal Server Error",
    },
    503: {
        "model": ErrorResponse,
        "description": "Service Unavailable - Dependency unavailable",
    },
}
