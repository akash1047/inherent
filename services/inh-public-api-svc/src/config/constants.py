"""Constants for the public API service."""

from typing import Final, Literal

# API version
API_VERSION: Final[str] = "v1"

# Rate limits by pricing tier (requests per minute)
PLAN_RATE_LIMITS: Final[dict[str, int]] = {
    "starter": 100,  # $149/month
    "pro": 500,  # $349/month
    "team": 2000,  # $799/month
    "enterprise": 10000,  # $2K+/month
}

# Default rate limit for keys without tier info
DEFAULT_RATE_LIMIT: Final[int] = 100

# Rate limit window in seconds
RATE_LIMIT_WINDOW_SECONDS: Final[int] = 60

# RFC 7807 Error type URLs
ERROR_BASE_URL: Final[str] = "https://api.inherent.systems/errors"

ERROR_TYPES: Final[dict[str, str]] = {
    "authentication_failed": f"{ERROR_BASE_URL}/authentication-failed",
    "authorization_failed": f"{ERROR_BASE_URL}/authorization-failed",
    "rate_limit_exceeded": f"{ERROR_BASE_URL}/rate-limit-exceeded",
    "resource_not_found": f"{ERROR_BASE_URL}/resource-not-found",
    "validation_error": f"{ERROR_BASE_URL}/validation-error",
    "service_unavailable": f"{ERROR_BASE_URL}/service-unavailable",
    "internal_error": f"{ERROR_BASE_URL}/internal-error",
    "bad_request": f"{ERROR_BASE_URL}/bad-request",
}

# Error titles (human-readable)
ERROR_TITLES: Final[dict[str, str]] = {
    "authentication_failed": "Authentication Failed",
    "authorization_failed": "Authorization Failed",
    "rate_limit_exceeded": "Rate Limit Exceeded",
    "resource_not_found": "Resource Not Found",
    "validation_error": "Validation Error",
    "service_unavailable": "Service Unavailable",
    "internal_error": "Internal Server Error",
    "bad_request": "Bad Request",
}

# Security headers
SECURITY_HEADERS: Final[dict[str, str]] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}

# HSTS header (only for production)
HSTS_HEADER: Final[str] = "max-age=31536000; includeSubDomains"

# Request ID header names
REQUEST_ID_HEADER: Final[str] = "X-Request-ID"
CORRELATION_ID_HEADER: Final[str] = "X-Correlation-ID"

# Rate limit response headers
RATE_LIMIT_HEADERS: Final[dict[str, str]] = {
    "limit": "X-RateLimit-Limit",
    "remaining": "X-RateLimit-Remaining",
    "reset": "X-RateLimit-Reset",
    "retry_after": "Retry-After",
}

# Health check statuses
HealthStatus = Literal["healthy", "degraded", "unhealthy"]
HEALTH_STATUS_HEALTHY: Final[HealthStatus] = "healthy"
HEALTH_STATUS_DEGRADED: Final[HealthStatus] = "degraded"
HEALTH_STATUS_UNHEALTHY: Final[HealthStatus] = "unhealthy"

# Upload limits
MAX_UPLOAD_SIZE_BYTES: Final[int] = 50 * 1024 * 1024  # 50 MB
ALLOWED_MIME_TYPES: Final[list[str]] = [
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/html",
    "application/pdf",
    "application/json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "image/png",  # OCR via Tesseract (graceful fallback when OCR unavailable)
]

# Search constraints
MAX_SEARCH_QUERY_LENGTH: Final[int] = 1000
MAX_SEARCH_RESULTS: Final[int] = 100
DEFAULT_SEARCH_RESULTS: Final[int] = 10
MIN_SEARCH_SCORE: Final[float] = 0.0

# Pagination
MAX_PAGE_SIZE: Final[int] = 100
DEFAULT_PAGE_SIZE: Final[int] = 20

# Timeouts (in seconds)
DATABASE_HEALTH_CHECK_TIMEOUT: Final[float] = 5.0
WEAVIATE_HEALTH_CHECK_TIMEOUT: Final[float] = 5.0
