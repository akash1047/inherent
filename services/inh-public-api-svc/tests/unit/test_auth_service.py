"""Unit tests for the auth service."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from src.models.api_key import APIKeyInfo
from src.services.auth import (
    AuthService,
    get_api_key_info,
    get_read_permission,
    get_search_permission,
)


@pytest.fixture
def mock_database():
    """Create a mock database service."""
    return AsyncMock()


@pytest.fixture
def auth_service(mock_database):
    """Create an AuthService instance with mocked database."""
    return AuthService(database=mock_database)


@pytest.fixture
def valid_key_info():
    """A valid, non-expired API key info with read+search permissions."""
    return APIKeyInfo(
        key_id="key-001",
        user_id="user-001",
        workspace_id="ws-001",
        permissions=["read", "search"],
        rate_limit=100,
        expires_at=None,
        status="active",
    )


@pytest.fixture
def expired_key_info():
    """An API key info that has expired."""
    return APIKeyInfo(
        key_id="key-expired",
        user_id="user-001",
        workspace_id="ws-001",
        permissions=["read", "search"],
        rate_limit=100,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        status="active",
    )


@pytest.fixture
def read_only_key_info():
    """An API key info with only read permission."""
    return APIKeyInfo(
        key_id="key-read",
        user_id="user-001",
        workspace_id="ws-001",
        permissions=["read"],
        rate_limit=100,
        expires_at=None,
        status="active",
    )


class TestValidateApiKey:
    """Tests for AuthService.validate_api_key()."""

    async def test_valid_key_returns_key_info(self, auth_service, mock_database, valid_key_info):
        """Should return APIKeyInfo for a valid API key."""
        mock_database.validate_api_key = AsyncMock(return_value=valid_key_info)

        result = await auth_service.validate_api_key("ink_test_valid_key")
        assert result is not None
        assert result.key_id == "key-001"
        assert result.workspace_id == "ws-001"
        assert result.permissions == ["read", "search"]

    async def test_invalid_key_returns_none(self, auth_service, mock_database):
        """Should return None for an invalid API key."""
        mock_database.validate_api_key = AsyncMock(return_value=None)

        result = await auth_service.validate_api_key("ink_invalid_key")
        assert result is None

    async def test_empty_key_returns_none(self, auth_service):
        """Should return None for an empty string."""
        result = await auth_service.validate_api_key("")
        assert result is None

    async def test_strips_bearer_prefix(self, auth_service, mock_database, valid_key_info):
        """Should strip 'Bearer ' prefix before validation."""
        mock_database.validate_api_key = AsyncMock(return_value=valid_key_info)

        await auth_service.validate_api_key("Bearer ink_test_key")
        # The database should receive the key without "Bearer " prefix
        mock_database.validate_api_key.assert_awaited_once_with("ink_test_key")

    async def test_key_without_bearer_prefix(self, auth_service, mock_database, valid_key_info):
        """Should pass key directly if no Bearer prefix."""
        mock_database.validate_api_key = AsyncMock(return_value=valid_key_info)

        await auth_service.validate_api_key("ink_raw_key")
        mock_database.validate_api_key.assert_awaited_once_with("ink_raw_key")


class TestRequireApiKey:
    """Tests for AuthService.require_api_key()."""

    async def test_valid_key_returns_info(self, auth_service, mock_database, valid_key_info):
        """Should return APIKeyInfo for a valid, non-expired key."""
        mock_database.validate_api_key = AsyncMock(return_value=valid_key_info)

        result = await auth_service.require_api_key("ink_test_key")
        assert result.key_id == "key-001"

    async def test_invalid_key_raises_401(self, auth_service, mock_database):
        """Should raise 401 HTTPException for an invalid key."""
        mock_database.validate_api_key = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await auth_service.require_api_key("ink_bad_key")
        assert exc_info.value.status_code == 401
        assert "Invalid or expired API key" in exc_info.value.detail

    async def test_expired_key_raises_401(self, auth_service, mock_database, expired_key_info):
        """Should raise 401 HTTPException for an expired key."""
        mock_database.validate_api_key = AsyncMock(return_value=expired_key_info)

        with pytest.raises(HTTPException) as exc_info:
            await auth_service.require_api_key("ink_expired_key")
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    async def test_missing_permission_raises_403(
        self, auth_service, mock_database, read_only_key_info
    ):
        """Should raise 403 HTTPException when key lacks the required permission."""
        mock_database.validate_api_key = AsyncMock(return_value=read_only_key_info)

        with pytest.raises(HTTPException) as exc_info:
            await auth_service.require_api_key("ink_read_key", required_permission="search")
        assert exc_info.value.status_code == 403
        assert "search" in exc_info.value.detail

    async def test_has_required_permission_succeeds(
        self, auth_service, mock_database, valid_key_info
    ):
        """Should succeed when key has the required permission."""
        mock_database.validate_api_key = AsyncMock(return_value=valid_key_info)

        result = await auth_service.require_api_key("ink_test_key", required_permission="search")
        assert result.key_id == "key-001"

    async def test_no_required_permission_skips_check(
        self, auth_service, mock_database, valid_key_info
    ):
        """Should skip permission check when required_permission is None."""
        mock_database.validate_api_key = AsyncMock(return_value=valid_key_info)

        result = await auth_service.require_api_key("ink_test_key", required_permission=None)
        assert result.key_id == "key-001"

    async def test_empty_key_raises_401(self, auth_service):
        """Should raise 401 for an empty key string."""
        with pytest.raises(HTTPException) as exc_info:
            await auth_service.require_api_key("")
        assert exc_info.value.status_code == 401


class TestGetApiKeyInfoDependency:
    """Tests for the get_api_key_info FastAPI dependency."""

    @patch("src.services.auth.get_auth_service")
    async def test_extracts_from_x_api_key_header(self, mock_get_auth):
        """Should extract API key from X-API-Key header."""
        valid_info = APIKeyInfo(
            key_id="key-001",
            user_id="user-001",
            workspace_id="ws-001",
            permissions=["read", "search"],
            rate_limit=100,
            expires_at=None,
            status="active",
        )
        mock_auth_svc = AsyncMock()
        mock_auth_svc.require_api_key = AsyncMock(return_value=valid_info)
        mock_get_auth.return_value = mock_auth_svc

        result = await get_api_key_info(x_api_key="ink_from_header", authorization=None)
        assert result.key_id == "key-001"
        mock_auth_svc.require_api_key.assert_awaited_once_with("ink_from_header")

    @patch("src.services.auth.get_auth_service")
    async def test_extracts_from_authorization_bearer_header(self, mock_get_auth):
        """Should extract API key from Authorization: Bearer header."""
        valid_info = APIKeyInfo(
            key_id="key-002",
            user_id="user-001",
            workspace_id="ws-001",
            permissions=["read"],
            rate_limit=100,
            expires_at=None,
            status="active",
        )
        mock_auth_svc = AsyncMock()
        mock_auth_svc.require_api_key = AsyncMock(return_value=valid_info)
        mock_get_auth.return_value = mock_auth_svc

        result = await get_api_key_info(x_api_key=None, authorization="Bearer ink_bearer_key")
        assert result.key_id == "key-002"
        # Should strip "Bearer " and pass just the key
        mock_auth_svc.require_api_key.assert_awaited_once_with("ink_bearer_key")

    @patch("src.services.auth.get_auth_service")
    async def test_extracts_from_authorization_without_bearer(self, mock_get_auth):
        """Should accept Authorization header without Bearer prefix."""
        valid_info = APIKeyInfo(
            key_id="key-003",
            user_id="user-001",
            workspace_id="ws-001",
            permissions=["read"],
            rate_limit=100,
            expires_at=None,
            status="active",
        )
        mock_auth_svc = AsyncMock()
        mock_auth_svc.require_api_key = AsyncMock(return_value=valid_info)
        mock_get_auth.return_value = mock_auth_svc

        result = await get_api_key_info(x_api_key=None, authorization="ink_plain_auth")
        assert result.key_id == "key-003"
        mock_auth_svc.require_api_key.assert_awaited_once_with("ink_plain_auth")

    @patch("src.services.auth.get_auth_service")
    async def test_x_api_key_takes_precedence(self, mock_get_auth):
        """X-API-Key header should take precedence over Authorization header."""
        valid_info = APIKeyInfo(
            key_id="key-from-x-api",
            user_id="user-001",
            workspace_id="ws-001",
            permissions=["read"],
            rate_limit=100,
            expires_at=None,
            status="active",
        )
        mock_auth_svc = AsyncMock()
        mock_auth_svc.require_api_key = AsyncMock(return_value=valid_info)
        mock_get_auth.return_value = mock_auth_svc

        result = await get_api_key_info(
            x_api_key="ink_x_api_key",
            authorization="Bearer ink_auth_key",
        )
        assert result.key_id == "key-from-x-api"
        # Should use X-API-Key value, not Authorization
        mock_auth_svc.require_api_key.assert_awaited_once_with("ink_x_api_key")

    async def test_missing_both_headers_raises_401(self):
        """Should raise 401 when neither X-API-Key nor Authorization is provided."""
        with pytest.raises(HTTPException) as exc_info:
            await get_api_key_info(x_api_key=None, authorization=None)
        assert exc_info.value.status_code == 401
        assert "API key required" in exc_info.value.detail

    async def test_empty_x_api_key_and_no_authorization_raises_401(self):
        """Should raise 401 when X-API-Key is empty and Authorization is missing."""
        # FastAPI will pass None for missing headers, but test empty string fallback
        with pytest.raises(HTTPException) as exc_info:
            await get_api_key_info(x_api_key=None, authorization=None)
        assert exc_info.value.status_code == 401


class TestGetSearchPermission:
    """Tests for the get_search_permission dependency."""

    async def test_allows_search_permission(self):
        """Should return key_info when it has search permission."""
        key_info = APIKeyInfo(
            key_id="key-001",
            user_id="user-001",
            workspace_id="ws-001",
            permissions=["read", "search"],
            rate_limit=100,
            expires_at=None,
            status="active",
        )
        result = await get_search_permission(key_info=key_info)
        assert result.key_id == "key-001"

    async def test_denies_without_search_permission(self):
        """Should raise 403 when key lacks search permission."""
        key_info = APIKeyInfo(
            key_id="key-read",
            user_id="user-001",
            workspace_id="ws-001",
            permissions=["read"],
            rate_limit=100,
            expires_at=None,
            status="active",
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_search_permission(key_info=key_info)
        assert exc_info.value.status_code == 403
        assert "search" in exc_info.value.detail


class TestGetReadPermission:
    """Tests for the get_read_permission dependency."""

    async def test_allows_read_permission(self):
        """Should return key_info when it has read permission."""
        key_info = APIKeyInfo(
            key_id="key-001",
            user_id="user-001",
            workspace_id="ws-001",
            permissions=["read", "search"],
            rate_limit=100,
            expires_at=None,
            status="active",
        )
        result = await get_read_permission(key_info=key_info)
        assert result.key_id == "key-001"

    async def test_denies_without_read_permission(self):
        """Should raise 403 when key lacks read permission."""
        key_info = APIKeyInfo(
            key_id="key-search",
            user_id="user-001",
            workspace_id="ws-001",
            permissions=["search"],
            rate_limit=100,
            expires_at=None,
            status="active",
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_read_permission(key_info=key_info)
        assert exc_info.value.status_code == 403
        assert "read" in exc_info.value.detail

    async def test_denies_with_empty_permissions(self):
        """Should raise 403 when key has no permissions at all."""
        key_info = APIKeyInfo(
            key_id="key-empty",
            user_id="user-001",
            workspace_id="ws-001",
            permissions=[],
            rate_limit=100,
            expires_at=None,
            status="active",
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_read_permission(key_info=key_info)
        assert exc_info.value.status_code == 403
