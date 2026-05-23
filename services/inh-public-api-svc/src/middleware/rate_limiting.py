"""Rate limiting middleware.

This middleware:
1. Extracts API key info from request state (set by auth)
2. Checks rate limit using token bucket algorithm
3. Adds rate limit headers to response
4. Returns 429 Too Many Requests if limit exceeded
"""

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from src.config import settings
from src.config.constants import DEFAULT_RATE_LIMIT, RATE_LIMIT_HEADERS
from src.core.exceptions import RateLimitError
from src.core.problem_details import from_exception
from src.core.rate_limiter import RateLimitInfo, get_rate_limiter
from src.middleware.request_context import get_request_context
from src.utils import get_logger

logger = get_logger(__name__)


def _add_rate_limit_headers(response: Response, info: RateLimitInfo) -> None:
    """Add rate limit headers to response."""
    response.headers[RATE_LIMIT_HEADERS["limit"]] = str(info.limit)
    response.headers[RATE_LIMIT_HEADERS["remaining"]] = str(info.remaining)
    response.headers[RATE_LIMIT_HEADERS["reset"]] = str(int(info.reset_at))


def _create_rate_limit_response(info: RateLimitInfo, path: str) -> JSONResponse:
    """Create a 429 response with rate limit details."""
    ctx = get_request_context()
    trace_id = ctx.request_id if ctx else None

    exc = RateLimitError(
        detail=f"Rate limit of {info.limit} requests per {info.window_seconds} seconds exceeded.",
        retry_after=info.reset_in_seconds,
        limit=info.limit,
        remaining=0,
    )

    response = JSONResponse(
        status_code=429,
        content=from_exception(exc, instance=path, trace_id=trace_id),
        media_type="application/problem+json",
    )

    # Add rate limit headers
    _add_rate_limit_headers(response, info)

    # Add Retry-After header
    response.headers[RATE_LIMIT_HEADERS["retry_after"]] = str(info.reset_in_seconds)

    return response


class RateLimitingMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces rate limits based on API key configuration."""

    # Paths that bypass rate limiting
    EXEMPT_PATHS = {"/health", "/health/ready", "/health/live", "/metrics"}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Check if rate limiting is enabled
        if not settings.rate_limit_enabled:
            return await call_next(request)

        # Skip rate limiting for exempt paths
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        # Get API key info from request state (set by auth dependency)
        # If not set, the request hasn't been authenticated yet - let it through
        # and auth will handle rejecting it
        api_key_info = getattr(request.state, "api_key_info", None)
        if api_key_info is None:
            return await call_next(request)

        # Get rate limit from API key (uses default if not specified)
        rate_limit = getattr(api_key_info, "rate_limit", None) or DEFAULT_RATE_LIMIT
        key_id = getattr(api_key_info, "key_id", "unknown")

        # Check rate limit
        rate_limiter = get_rate_limiter()
        result = await rate_limiter.check_rate_limit(
            key=key_id,
            limit=rate_limit,
            window_seconds=settings.rate_limit_window_seconds,
        )

        if not result.allowed:
            logger.warning(
                "Rate limit exceeded",
                key_id=key_id,
                limit=rate_limit,
                path=request.url.path,
            )
            return _create_rate_limit_response(result.info, request.url.path)

        # Process request
        response = await call_next(request)

        # Add rate limit headers to successful response
        _add_rate_limit_headers(response, result.info)

        return response
