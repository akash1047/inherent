"""Failure-injection: Redis MQ must NOT ack a message when the handler fails.

This is the core recoverability guarantee of the ingestion consumer: if the
message handler raises (a downstream dependency failed mid-processing), the
stream entry must stay PENDING (un-ACKed) so Redis redelivers it on the next
poll / after a restart. ACKing on failure would silently drop the work.

Mocking is at the redis async client boundary; no live Redis/Valkey required.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import Settings
from src.services.mq.redis_mq import RedisMQService

pytestmark = pytest.mark.failure_injection


@pytest.fixture
def mock_settings():
    settings = MagicMock(spec=Settings)
    settings.redis_url = "redis://localhost:6379"
    return settings


@pytest.fixture
def service(mock_settings):
    return RedisMQService(mock_settings)


@pytest.fixture
def mock_redis_client():
    client = MagicMock()
    client.ping = AsyncMock(return_value=True)
    client.xack = AsyncMock(return_value=1)
    client.xreadgroup = AsyncMock(return_value=[])
    return client


async def test_handle_message_does_not_ack_on_handler_failure(service, mock_redis_client):
    """When the handler raises, xack must NOT be called (message stays pending)."""
    service._redis = mock_redis_client
    service._connected = True

    failing_handler = AsyncMock(side_effect=RuntimeError("downstream dependency failed"))
    fields = {"payload": json.dumps({"document_id": "doc-1"})}

    # _handle_message catches the handler error internally and logs it; it must
    # not re-raise, and crucially must not ack.
    await service._handle_message(
        stream="core.document.uploaded.v1",
        group="default",
        message_id="1-0",
        fields=fields,
        handler=failing_handler,
    )

    failing_handler.assert_awaited_once()
    mock_redis_client.xack.assert_not_called()


async def test_handle_message_acks_on_handler_success(service, mock_redis_client):
    """Control case: on success the message IS acked (so we know the assert means something)."""
    service._redis = mock_redis_client
    service._connected = True

    ok_handler = AsyncMock(return_value=None)
    fields = {"payload": json.dumps({"document_id": "doc-1"})}

    await service._handle_message(
        stream="core.document.uploaded.v1",
        group="default",
        message_id="1-0",
        fields=fields,
        handler=ok_handler,
    )

    ok_handler.assert_awaited_once()
    mock_redis_client.xack.assert_awaited_once_with("core.document.uploaded.v1", "default", "1-0")


async def test_poll_loop_does_not_ack_when_handler_raises(service, mock_redis_client):
    """End-to-end through the poll loop: one delivered message, handler raises,
    no ack is issued so Redis can redeliver it."""
    service._redis = mock_redis_client
    service._connected = True
    service._running = True

    stream = "core.document.uploaded.v1"
    message = ("5-0", {"payload": json.dumps({"document_id": "doc-1"})})

    # First xreadgroup call (pending recovery, id="0") returns nothing.
    # Second call (new messages, id=">") returns one message, then we stop.
    call_state = {"n": 0}

    async def fake_xreadgroup(*args, **kwargs):
        call_state["n"] += 1
        if call_state["n"] == 1:
            return []  # pending-recovery phase: nothing to recover
        if call_state["n"] == 2:
            return [(stream, [message])]  # deliver one new message
        service._running = False  # stop the loop after delivering
        return []

    mock_redis_client.xreadgroup.side_effect = fake_xreadgroup

    failing_handler = AsyncMock(side_effect=RuntimeError("downstream dependency failed"))

    with patch("asyncio.sleep", new=AsyncMock()):
        await service._poll_loop(stream, "default", "consumer-1", failing_handler)

    failing_handler.assert_awaited()
    # The delivered message must never be acked.
    mock_redis_client.xack.assert_not_called()
