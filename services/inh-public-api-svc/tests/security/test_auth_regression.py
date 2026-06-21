"""Authentication regression tests (#32).

Offline guards for the core auth gate (``AuthService.require_api_key``) and the
permission dependencies:

- expired key            → 401
- invalid / unknown key  → 401, and never returns key info (no data)
- missing permission     → 403 (read-only key denied search/write)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from src.models.api_key import APIKeyInfo
from src.services.auth import (
    AuthService,
    get_search_permission,
    get_write_permission,
)

pytestmark = pytest.mark.security


def _key(*, expires_at=None, permissions=None, status_="active") -> APIKeyInfo:
    return APIKeyInfo(
        key_id="key-1",
        user_id="user-1",
        workspace_id="ws-1",
        permissions=permissions or ["read", "search"],
        rate_limit=100,
        expires_at=expires_at,
        status=status_,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_expired_key_is_unauthorized() -> None:
    """A key past its expiry must be rejected with 401 even though the DB row
    'exists'."""
    expired = _key(expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    db = AsyncMock()
    # validate_api_key returns the (expired) row; require_api_key must still 401.
    db.validate_api_key = AsyncMock(return_value=expired)
    svc = AuthService(database=db)

    with pytest.raises(HTTPException) as exc_info:
        await svc.require_api_key("ink_expired")
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_invalid_key_is_unauthorized_and_returns_no_data() -> None:
    """An unknown/invalid key (DB returns None) → 401, and require_api_key never
    yields key info."""
    db = AsyncMock()
    db.validate_api_key = AsyncMock(return_value=None)
    svc = AuthService(database=db)

    with pytest.raises(HTTPException) as exc_info:
        await svc.require_api_key("ink_does_not_exist")
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_empty_key_is_unauthorized() -> None:
    """A blank credential must be rejected, never silently allowed."""
    db = AsyncMock()
    db.validate_api_key = AsyncMock(return_value=None)
    svc = AuthService(database=db)

    with pytest.raises(HTTPException) as exc_info:
        await svc.require_api_key("")
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_require_permission_denied_is_forbidden() -> None:
    """A valid key lacking the required permission → 403 (not 401)."""
    read_only = _key(permissions=["read"])
    db = AsyncMock()
    db.validate_api_key = AsyncMock(return_value=read_only)
    svc = AuthService(database=db)

    with pytest.raises(HTTPException) as exc_info:
        await svc.require_api_key("ink_readonly", required_permission="search")
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_read_only_key_denied_search_dependency() -> None:
    """The search dependency must reject a read-only key with 403."""
    read_only = _key(permissions=["read"])
    with pytest.raises(HTTPException) as exc_info:
        await get_search_permission(key_info=read_only)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_read_only_key_denied_write_dependency() -> None:
    """The write dependency must reject a read-only key with 403."""
    read_only = _key(permissions=["read"])
    with pytest.raises(HTTPException) as exc_info:
        await get_write_permission(key_info=read_only)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_valid_key_with_permission_is_allowed() -> None:
    """Sanity: a valid key WITH the permission passes (the gate is not
    over-broad)."""
    valid = _key(permissions=["read", "search"])
    db = AsyncMock()
    db.validate_api_key = AsyncMock(return_value=valid)
    svc = AuthService(database=db)

    result = await svc.require_api_key("ink_ok", required_permission="search")
    assert result.key_id == "key-1"
