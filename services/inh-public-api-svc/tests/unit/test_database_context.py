"""Unit tests for DatabaseService.get_context_chunks (PM-S019)."""

from __future__ import annotations

import pytest

from src.services.database import DatabaseService


@pytest.mark.asyncio
async def test_empty_ranges_returns_empty_without_db_call() -> None:
    """Short-circuit: empty ranges must not execute any SQL."""
    # We instantiate without a real engine; the method must return []
    # before any session is opened when ranges is empty.
    db = DatabaseService.__new__(DatabaseService)  # bypass __init__
    rows = await db.get_context_chunks(workspace_id="ws-any", ranges=[])
    assert rows == []


def test_method_exists_and_is_awaitable() -> None:
    """Sanity: method is attached and is an async callable."""
    import inspect

    assert hasattr(DatabaseService, "get_context_chunks")
    assert inspect.iscoroutinefunction(DatabaseService.get_context_chunks)
