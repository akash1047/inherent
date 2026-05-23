"""Logging configuration."""

import logging
import os
import sys

import structlog


def setup_logging(level: str = "INFO") -> None:
    """Setup structured logging.

    Uses JSON output in production (for Loki/Promtail ingestion) and
    human-readable console output in development.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    is_production = os.getenv("NODE_ENV", "").lower() == "production" or os.getenv(
        "SERVICE_MODE", ""
    ) in ("standalone", "api")

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # Shared processors for context and metadata
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if is_production:
        # JSON output for Loki/Promtail — all context fields become queryable
        shared_processors.append(structlog.processors.JSONRenderer())
    else:
        # Human-readable output for local development
        shared_processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=shared_processors,  # type: ignore[arg-type]
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
