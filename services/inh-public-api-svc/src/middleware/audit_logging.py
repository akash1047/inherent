"""Audit logging middleware.

This middleware logs structured audit events for all API requests,
providing a complete audit trail for compliance and debugging.
"""

from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.config import settings
from src.middleware.request_context import get_request_context
from src.services import metrics
from src.utils import get_logger

logger = get_logger("audit")


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs structured audit events for all requests."""

    # Paths that don't need audit logging
    QUIET_PATHS = {"/health", "/health/ready", "/health/live", "/metrics"}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip audit logging if disabled
        if not settings.audit_log_enabled:
            return await call_next(request)

        # Skip quiet paths (health checks, metrics)
        if request.url.path in self.QUIET_PATHS:
            return await call_next(request)

        # Track active requests
        metrics.increment_active_requests()

        try:
            # Process request
            response = await call_next(request)

            # Log audit event
            self._log_audit_event(request, response)

            # Record metrics
            self._record_metrics(request, response)

            return response
        finally:
            metrics.decrement_active_requests()

    def _log_audit_event(self, request: Request, response: Response) -> None:
        """Log a structured audit event."""
        ctx = get_request_context()

        # Build auth context from request state
        api_key_info = getattr(request.state, "api_key_info", None)
        auth_context = {}
        if api_key_info:
            auth_context = {
                "key_id": getattr(api_key_info, "key_id", None),
                "user_id": getattr(api_key_info, "user_id", None),
                "workspace_id": getattr(api_key_info, "workspace_id", None),
                "permissions": getattr(api_key_info, "permissions", []),
            }

        # Calculate duration
        duration_ms = ctx.duration_ms if ctx else 0

        # Log structured audit event
        logger.info(
            "api_request",
            event_type="api_request",
            timestamp=datetime.now(timezone.utc).isoformat(),
            trace_id=ctx.request_id if ctx else None,
            request={
                "method": request.method,
                "path": request.url.path,
                "query": str(request.query_params) if request.query_params else None,
                "user_agent": ctx.user_agent if ctx else None,
                "client_ip": ctx.client_ip if ctx else None,
            },
            auth=auth_context if auth_context else None,
            response={
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )

    def _record_metrics(self, request: Request, response: Response) -> None:
        """Record Prometheus metrics for the request."""
        ctx = get_request_context()

        # Normalize endpoint for metrics (remove IDs)
        endpoint = self._normalize_endpoint(request.url.path)

        # Record request count
        metrics.record_request(
            method=request.method,
            endpoint=endpoint,
            status_code=response.status_code,
        )

        # Record latency
        if ctx:
            duration_seconds = ctx.duration_ms / 1000
            metrics.observe_request_latency(
                method=request.method,
                endpoint=endpoint,
                duration_seconds=duration_seconds,
            )

    def _normalize_endpoint(self, path: str) -> str:
        """Normalize endpoint path for metrics.

        Replaces dynamic path segments (UUIDs, IDs) with placeholders
        to prevent metric cardinality explosion.
        """
        import re

        # Replace UUIDs with {id}
        path = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "{id}",
            path,
            flags=re.IGNORECASE,
        )

        # Replace MongoDB ObjectIds with {id}
        path = re.sub(r"/[0-9a-f]{24}(?=/|$)", "/{id}", path, flags=re.IGNORECASE)

        # Replace numeric IDs with {id}
        path = re.sub(r"/\d+(?=/|$)", "/{id}", path)

        return path
