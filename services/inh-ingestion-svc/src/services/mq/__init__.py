"""Message queue service factory.

Creates the appropriate MQ backend based on the MQ_BACKEND setting.
All backends implement BaseMQService for consistent behavior across
dev, staging, and production environments.

Supported backends:
    redis   — Valkey/Redis Streams (default, recommended for all environments)
    memory  — In-process only (unit tests only, does NOT cross containers)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from .base import BaseMQService, MessageHandler

if TYPE_CHECKING:
    from src.config.settings import Settings

logger = structlog.get_logger(__name__)

# Re-export for backward compatibility
__all__ = ["BaseMQService", "MessageHandler", "create_mq_service"]


def create_mq_service(settings: Settings) -> BaseMQService:
    """Factory: create the MQ service for the configured backend.

    Reads ``settings.mq_backend`` (env var ``MQ_BACKEND``, default ``"redis"``).

    Returns:
        A connected-ready (but not yet connected) BaseMQService instance.
    """
    backend = settings.mq_backend

    if backend == "memory":
        from .memory_mq import MemoryMQService

        logger.info("Creating Memory MQ service (in-process only, for tests)")
        return MemoryMQService(settings)

    # Default: redis (works with Valkey, Redis, any Redis-protocol server)
    from .redis_mq import RedisMQService

    logger.info("Creating Redis MQ service")
    return RedisMQService(settings)
