"""Unit tests for src.services.mq."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from src.services.mq import MQService, close_mq_service, get_mq_service


class TestMQService:
    """Tests for MQService."""

    async def test_publish_calls_xadd(self):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1234-0")

        with patch("src.services.mq.aioredis") as mock_aioredis:
            mock_aioredis.from_url.return_value = mock_redis
            svc = MQService("redis://localhost:6379")

        svc._redis = mock_redis
        svc._connected = True

        msg_id = await svc.publish("test.topic", {"key": "value"})

        assert msg_id == "1234-0"
        mock_redis.xadd.assert_awaited_once_with(
            "test.topic",
            {"payload": json.dumps({"key": "value"})},
        )

    async def test_publish_auto_connects(self):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="5678-0")

        with patch("src.services.mq.aioredis") as mock_aioredis:
            mock_aioredis.from_url.return_value = mock_redis
            svc = MQService("redis://localhost:6379")

        svc._redis = mock_redis
        svc._connected = False

        await svc.publish("topic", {"data": 1})

        # Should have called ping (connect)
        mock_redis.ping.assert_awaited_once()
        assert svc._connected is True

    async def test_close(self):
        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with patch("src.services.mq.aioredis") as mock_aioredis:
            mock_aioredis.from_url.return_value = mock_redis
            svc = MQService("redis://localhost:6379")

        svc._redis = mock_redis
        svc._connected = True

        await svc.close()

        mock_redis.close.assert_awaited_once()
        assert svc._connected is False


class TestMQSingleton:
    """Tests for singleton management functions."""

    async def test_get_and_close(self):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with patch("src.services.mq.aioredis") as mock_aioredis:
            mock_aioredis.from_url.return_value = mock_redis

            import src.services.mq as mod

            mod._mq_service = None

            svc = await get_mq_service()
            assert svc is not None
            assert await get_mq_service() is svc  # same instance

            await close_mq_service()
            assert mod._mq_service is None
