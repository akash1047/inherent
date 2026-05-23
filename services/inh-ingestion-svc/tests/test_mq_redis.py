"""Unit tests for RedisMQService."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import Settings
from src.services.mq.redis_mq import RedisMQService


@pytest.fixture
def mock_settings():
    """Create mock settings for RedisMQService."""
    settings = MagicMock(spec=Settings)
    settings.redis_url = "redis://localhost:6379"
    settings.mq_completion_topic = "core.document.processed.v1"
    return settings


@pytest.fixture
def service(mock_settings):
    """Create a RedisMQService instance."""
    return RedisMQService(mock_settings)


@pytest.fixture
def mock_redis_client():
    """Create a mock Redis async client."""
    client = MagicMock()
    client.ping = AsyncMock(return_value=True)
    client.xadd = AsyncMock(return_value="1234567890-0")
    client.xgroup_create = AsyncMock(return_value=True)
    client.xreadgroup = AsyncMock(return_value=[])
    client.xack = AsyncMock(return_value=1)
    client.aclose = AsyncMock(return_value=None)
    client.close = AsyncMock(return_value=None)
    return client


class TestRedisMQServiceBackend:
    """Tests for RedisMQService backend property."""

    def test_backend_returns_redis(self, service):
        """Test that backend property returns 'redis'."""
        assert service.backend == "redis"


class TestRedisMQServiceConnectionState:
    """Tests for RedisMQService connection state."""

    def test_not_connected_initially(self, service):
        """Test that service is not connected before connect() is called."""
        assert service.is_connected() is False
        assert service._connected is False
        assert service._redis is None

    @pytest.mark.asyncio
    async def test_connect_sets_connected_flag(self, service, mock_redis_client):
        """Test that connect() sets _connected to True after successful ping."""
        with patch("redis.asyncio.from_url", return_value=mock_redis_client):
            await service.connect()

            assert service.is_connected() is True
            assert service._connected is True
            assert service._running is True
            mock_redis_client.ping.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_clears_state(self, service, mock_redis_client):
        """Test that disconnect() clears connection state."""
        with patch("redis.asyncio.from_url", return_value=mock_redis_client):
            await service.connect()
            assert service.is_connected() is True

        await service.disconnect()

        assert service.is_connected() is False
        assert service._connected is False
        assert service._redis is None
        assert service._running is False
        mock_redis_client.aclose.assert_awaited_once()


class TestRedisMQServicePublish:
    """Tests for RedisMQService publish functionality."""

    @pytest.mark.asyncio
    async def test_publish_calls_xadd(self, service, mock_redis_client):
        """Test that publish() calls xadd on the Redis stream."""
        with patch("redis.asyncio.from_url", return_value=mock_redis_client):
            await service.connect()

        topic = "core.document.uploaded.v1"
        message = {"event_type": "document.uploaded", "document_id": "doc123"}

        await service.publish(topic, message)

        mock_redis_client.xadd.assert_awaited_once()
        call_args = mock_redis_client.xadd.call_args
        # First positional arg is the topic/stream name
        assert call_args[0][0] == topic
        # Second positional arg is the fields dict with "payload" key
        assert "payload" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_publish_raises_when_not_connected(self, service):
        """Test that publish() raises RuntimeError when not connected."""
        with pytest.raises(RuntimeError, match="Redis MQ: not connected"):
            await service.publish("test-topic", {"key": "value"})


class TestRedisMQServiceSubscribe:
    """Tests for RedisMQService subscribe/unsubscribe functionality."""

    @pytest.mark.asyncio
    async def test_subscribe_creates_poll_task(self, service, mock_redis_client):
        """Test that subscribe() creates a poll task entry in _poll_tasks."""
        with patch("redis.asyncio.from_url", return_value=mock_redis_client):
            await service.connect()

        topic = "core.document.uploaded.v1"
        handler = AsyncMock()

        await service.subscribe(topic, handler, group_id="test-group")

        assert topic in service._poll_tasks
        task = service._poll_tasks[topic]
        assert isinstance(task, asyncio.Task)

        # Cleanup: cancel the task to avoid warnings
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_poll_task(self, service, mock_redis_client):
        """Test that unsubscribe() removes the poll task for the topic."""
        with patch("redis.asyncio.from_url", return_value=mock_redis_client):
            await service.connect()

        topic = "core.document.uploaded.v1"
        handler = AsyncMock()

        await service.subscribe(topic, handler, group_id="test-group")
        assert topic in service._poll_tasks

        await service.unsubscribe(topic)

        assert topic not in service._poll_tasks
