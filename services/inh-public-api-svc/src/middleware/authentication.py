"""Authentication middleware.

Extracts and validates API key from request headers, populating
request.state.api_key_info for downstream middleware (rate limiting, audit).

This middleware does NOT enforce authentication -- that's handled by
route-level FastAPI dependencies. It only populates state.
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.services import metrics
from src.utils import get_logger

logger = get_logger(__name__)

# Paths that don't need auth resolution
EXEMPT_PATHS = {"/health", "/health/ready", "/health/live", "/metrics"}


async def get_auth_service():
    """Lazy import to avoid circular imports at module level."""
    from src.services.auth import get_auth_service as _get_auth_service

    return await _get_auth_service()


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Middleware that resolves API key info into request state.

    This middleware runs before audit logging and rate limiting so that
    those middlewares can read request.state.api_key_info. It does NOT
    reject unauthenticated requests -- route dependencies handle that.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Initialize state so downstream middleware always finds the attribute.
        # auth_error distinguishes "backend errored" from "no/invalid key" so
        # rate limiting (#149) doesn't punish a holder of a valid, high-limit
        # key as harshly as a truly unauthenticated caller just because the
        # auth backend had a transient blip.
        request.state.api_key_info = None
        request.state.auth_error = False

        # Skip exempt paths (health, metrics)
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        # Extract API key from headers
        api_key = self._extract_api_key(request)
        if not api_key:
            return await call_next(request)

        # Validate key -- catch ALL errors to never break the pipeline. A failure
        # here must still be visible (warning + metric), not just a debug log,
        # since it silently changes which rate-limit bucket the request lands in.
        try:
            auth_service = await get_auth_service()
            key_info = await auth_service.validate_api_key(api_key)
            if key_info and not key_info.is_expired():
                request.state.api_key_info = key_info
        except Exception:
            logger.warning("Auth middleware: key validation failed", exc_info=True)
            # Distinct from error_handler.py's "validation_error" (malformed
            # request body) -- this is the auth backend itself failing, not a
            # bad key or bad input.
            metrics.record_auth_failure("auth_backend_error")
            request.state.auth_error = True

        return await call_next(request)

    @staticmethod
    def _extract_api_key(request: Request) -> str | None:
        """Extract API key from X-API-Key or Authorization header."""
        # Try X-API-Key first
        api_key = request.headers.get("x-api-key")
        if api_key:
            return api_key

        # Try Authorization: Bearer <key>
        auth_header = request.headers.get("authorization")
        if auth_header:
            if auth_header.startswith("Bearer "):
                return auth_header[7:]
            return auth_header

        return None
