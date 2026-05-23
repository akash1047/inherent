"""In-memory message queue backend for testing.

Messages are stored in-process and delivered to subscribers synchronously.
Does NOT cross process boundaries — use only for unit tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from .base import BaseMQService, MessageHandler

if TYPE_CHECKING:
    from src.config.settings import Settings

logger = structlog.get_logger(__name__)


class MemoryMQService(BaseMQService):
    """In-memory message queue for testing and development."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._connected = False
        self._subscribers: dict[str, list[MessageHandler]] = {}
        self._history: dict[str, list[dict]] = {}

    @property
    def backend(self) -> str:
        return "memory"

    async def connect(self) -> None:
        self._connected = True
        logger.info("Memory MQ: connected")

    async def disconnect(self) -> None:
        self._connected = False
        self._subscribers.clear()
        logger.info("Memory MQ: disconnected")

    async def publish(self, topic: str, message: dict) -> None:
        if not self._connected:
            raise RuntimeError("Memory MQ: not connected")

        # Store in history
        self._history.setdefault(topic, []).append(message)

        # Notify subscribers
        handlers = self._subscribers.get(topic, [])
        for handler in handlers:
            try:
                await handler(message)
            except Exception as e:
                logger.error("Memory MQ: handler error", topic=topic, error=str(e))

        logger.debug("Memory MQ: published", topic=topic, subscriber_count=len(handlers))

    async def subscribe(
        self,
        topic: str,
        handler: MessageHandler,
        *,
        group_id: str = "default",
    ) -> None:
        self._subscribers.setdefault(topic, []).append(handler)
        logger.info("Memory MQ: subscribed", topic=topic, group_id=group_id)

    async def unsubscribe(self, topic: str) -> None:
        self._subscribers.pop(topic, None)
        logger.info("Memory MQ: unsubscribed", topic=topic)

    def is_connected(self) -> bool:
        return self._connected

    # Test helpers
    def get_history(self, topic: str) -> list[dict]:
        """Get all messages published to a topic (test helper)."""
        return self._history.get(topic, [])

    def clear_history(self) -> None:
        """Clear all message history (test helper)."""
        self._history.clear()
