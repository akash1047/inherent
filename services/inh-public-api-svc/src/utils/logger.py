"""Structured logging configuration using structlog.

This module provides:
- Structured JSON logging for production (GCP Cloud Logging compatible)
- Console logging with colors for development
- Automatic correlation ID injection from contextvars
- Request context binding (user_id, workspace_id, etc.)
"""

import logging
import sys
from typing import Any

import structlog


def _add_logger_name(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Add logger name to event dict for PrintLogger."""
    if "logger" not in event_dict:
        if hasattr(logger, "_context") and isinstance(logger._context, dict):
            if "logger" in logger._context:
                event_dict["logger"] = logger._context["logger"]
        elif hasattr(logger, "name"):
            event_dict["logger"] = logger.name
    return event_dict


def _add_service_context(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Add service context for GCP Cloud Logging."""
    # Add severity for GCP Cloud Logging
    level = event_dict.get("level", "info").upper()
    event_dict["severity"] = level

    return event_dict


def _format_for_gcp(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Format log entry for GCP Cloud Logging.

    GCP Cloud Logging expects:
    - severity: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - message: The log message
    - Additional fields are indexed automatically
    """
    # Extract the event as message
    if "event" in event_dict:
        event_dict["message"] = event_dict.pop("event")

    # Ensure severity is set
    if "level" in event_dict:
        event_dict["severity"] = event_dict.pop("level").upper()

    return event_dict


def configure_logging(log_level: str = "INFO", json_format: bool = False) -> None:
    """Configure structlog with appropriate processors.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR).
        json_format: If True, output JSON (for production/GCP). If False, use console format.
    """
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )

    # Silence noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # Build processor chain
    processors: list[structlog.types.Processor] = [
        # Merge context variables (correlation IDs, user context)
        structlog.contextvars.merge_contextvars,
        # Add log level
        structlog.processors.add_log_level,
        # Add timestamp
        structlog.processors.TimeStamper(fmt="iso"),
        # Add logger name
        _add_logger_name,
    ]

    if json_format:
        # Production: JSON format for GCP Cloud Logging
        processors.extend(
            [
                _add_service_context,
                _format_for_gcp,
                structlog.processors.JSONRenderer(),
            ]
        )
    else:
        # Development: Console format with colors
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, log_level.upper())),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a logger instance and bind the logger name to context.

    Args:
        name: Logger name (typically __name__).

    Returns:
        Configured structlog BoundLogger.
    """
    logger = structlog.get_logger(name)
    if name:
        logger = logger.bind(logger=name)
    return logger


def bind_request_context(
    request_id: str | None = None,
    user_id: str | None = None,
    workspace_id: str | None = None,
    key_id: str | None = None,
) -> None:
    """Bind request context to structlog for all subsequent logs.

    Call this at the start of request processing to add context
    that will be included in all logs for this request.

    Args:
        request_id: Request correlation ID.
        user_id: Authenticated user ID.
        workspace_id: Target workspace ID.
        key_id: API key ID.
    """
    context: dict[str, Any] = {}
    if request_id:
        context["request_id"] = request_id
    if user_id:
        context["user_id"] = user_id
    if workspace_id:
        context["workspace_id"] = workspace_id
    if key_id:
        context["key_id"] = key_id

    if context:
        structlog.contextvars.bind_contextvars(**context)


def clear_request_context() -> None:
    """Clear all bound context variables.

    Call this at the end of request processing.
    """
    structlog.contextvars.clear_contextvars()
