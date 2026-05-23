"""Security headers middleware.

Adds security-related HTTP headers to all responses:
- X-Content-Type-Options: Prevents MIME type sniffing
- X-Frame-Options: Prevents clickjacking
- X-XSS-Protection: Enables XSS filtering
- Referrer-Policy: Controls referrer information
- Content-Security-Policy: Restricts resource loading
- Strict-Transport-Security: Enforces HTTPS (production only)
- Cache-Control: Prevents caching of API responses
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.config import settings
from src.config.constants import HSTS_HEADER, SECURITY_HEADERS


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that adds security headers to all responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        # Add standard security headers
        for header_name, header_value in SECURITY_HEADERS.items():
            response.headers[header_name] = header_value

        # Add HSTS header only in production
        if settings.is_production and settings.enable_hsts:
            response.headers["Strict-Transport-Security"] = HSTS_HEADER

        return response
