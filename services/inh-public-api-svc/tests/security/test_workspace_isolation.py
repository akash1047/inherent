"""Workspace isolation regression tests (#32).

Guards ``_resolve_workspace`` (the shared core behind ``resolve_workspace_read``
/ ``resolve_workspace_search`` / ``resolve_workspace_write``): a user must never
be able to resolve a workspace that is not in their authorised set
(``get_user_workspace_ids``).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, status

from src.models.api_key import APIKeyInfo
from src.services.auth import _resolve_workspace

pytestmark = pytest.mark.security


def _user_key(permissions: list[str] | None = None) -> APIKeyInfo:
    """A user-scoped key (workspace_id=None) — access is driven purely by the
    user's authorised workspace set, which is the riskiest path."""
    return APIKeyInfo(
        key_id="key-user",
        user_id="user-1",
        workspace_id=None,
        permissions=permissions or ["read", "search", "write"],
        rate_limit=100,
        expires_at=None,
        status="active",
    )


def _patch_user_workspaces(ws_ids: list[str]):
    """Patch the DB so get_user_workspace_ids returns *ws_ids*."""
    mock_db = AsyncMock()
    mock_db.get_user_workspace_ids = AsyncMock(return_value=ws_ids)
    return patch("src.services.auth.get_database", AsyncMock(return_value=mock_db))


@pytest.mark.asyncio
async def test_request_for_unauthorised_workspace_is_forbidden() -> None:
    """A workspace NOT in the user's set, requested via header → 403."""
    key = _user_key()
    with _patch_user_workspaces(["ws-owned"]):
        with pytest.raises(HTTPException) as exc_info:
            await _resolve_workspace(key, "ws-someone-else", required=False)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_multi_workspace_user_can_access_each_owned_workspace() -> None:
    """A multi-workspace user can resolve any workspace in their own set."""
    key = _user_key()
    owned = ["ws-a", "ws-b", "ws-c"]
    with _patch_user_workspaces(owned):
        for ws in owned:
            resolved = await _resolve_workspace(key, ws, required=False)
            assert resolved.workspace_id == ws


@pytest.mark.asyncio
async def test_multi_workspace_user_cannot_access_foreign_workspace() -> None:
    """The same multi-workspace user is still blocked from a workspace outside
    their set — owning several workspaces must not grant access to all."""
    key = _user_key()
    with _patch_user_workspaces(["ws-a", "ws-b", "ws-c"]):
        with pytest.raises(HTTPException) as exc_info:
            await _resolve_workspace(key, "ws-foreign", required=False)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_workspace_scoped_key_cannot_cross_to_another_workspace() -> None:
    """A key scoped to one workspace cannot request a different workspace it
    does not own."""
    key = APIKeyInfo(
        key_id="key-ws",
        user_id="user-1",
        workspace_id="ws-scoped",
        permissions=["read", "search"],
        rate_limit=100,
        expires_at=None,
        status="active",
    )
    # The user only owns ws-scoped; a header asking for ws-other must 403.
    with _patch_user_workspaces(["ws-scoped"]):
        with pytest.raises(HTTPException) as exc_info:
            await _resolve_workspace(key, "ws-other", required=False)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_resolve_uses_only_authorised_set_for_default() -> None:
    """With no header and a single owned workspace, the resolved workspace is
    exactly that owned one (never a foreign id)."""
    key = _user_key()
    with _patch_user_workspaces(["ws-only"]):
        resolved = await _resolve_workspace(key, None, required=False)
    assert resolved.workspace_id == "ws-only"
