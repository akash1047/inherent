"""Unit tests for the authentication middleware."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from starlette.requests import Request
from starlette.testclient import TestClient

from src.models.api_key import APIKeyInfo


def _make_valid_key_info(**overrides) -> APIKeyInfo:
    """Create a valid APIKeyInfo for testing."""
    defaults = {
        "key_id": "key-001",
        "user_id": "user-001",
        "workspace_id": "ws-001",
        "permissions": ["read", "search"],
        "rate_limit": 100,
        "expires_at": None,
        "status": "active",
    }
    defaults.update(overrides)
    return APIKeyInfo(**defaults)


def _make_expired_key_info() -> APIKeyInfo:
    """Create an expired APIKeyInfo for testing."""
    return _make_valid_key_info(
        key_id="key-expired",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )


def _create_test_app():
    """Create a minimal FastAPI app with only the AuthenticationMiddleware."""
    from fastapi import FastAPI

    from src.middleware.authentication import AuthenticationMiddleware

    app = FastAPI()
    app.add_middleware(AuthenticationMiddleware)

    @app.get("/test")
    async def test_endpoint(request: Request):
        api_key_info = getattr(request.state, "api_key_info", "NOT_SET")
        if api_key_info is None:
            return {"api_key_info": None}
        if api_key_info == "NOT_SET":
            return {"api_key_info": "NOT_SET"}
        return {
            "api_key_info": {
                "key_id": api_key_info.key_id,
                "user_id": api_key_info.user_id,
            }
        }

    @app.get("/health")
    async def health_endpoint(request: Request):
        api_key_info = getattr(request.state, "api_key_info", "NOT_SET")
        if api_key_info is None:
            return {"api_key_info": None}
        return {"api_key_info": "NOT_SET" if api_key_info == "NOT_SET" else "set"}

    return app


class TestAuthenticationMiddleware:
    """Tests for AuthenticationMiddleware."""

    @patch("src.middleware.authentication.get_auth_service")
    def test_sets_api_key_info_from_x_api_key_header(self, mock_get_auth):
        """Should populate request.state.api_key_info when X-API-Key header is present."""
        valid_info = _make_valid_key_info()
        mock_auth_svc = AsyncMock()
        mock_auth_svc.validate_api_key = AsyncMock(return_value=valid_info)
        mock_get_auth.return_value = mock_auth_svc

        app = _create_test_app()
        client = TestClient(app)

        response = client.get("/test", headers={"X-API-Key": "ink_test_key"})
        assert response.status_code == 200
        data = response.json()
        assert data["api_key_info"] is not None
        assert data["api_key_info"]["key_id"] == "key-001"
        assert data["api_key_info"]["user_id"] == "user-001"

    @patch("src.middleware.authentication.get_auth_service")
    def test_sets_api_key_info_from_bearer_header(self, mock_get_auth):
        """Should populate request.state.api_key_info from Authorization: Bearer header."""
        valid_info = _make_valid_key_info(key_id="key-bearer")
        mock_auth_svc = AsyncMock()
        mock_auth_svc.validate_api_key = AsyncMock(return_value=valid_info)
        mock_get_auth.return_value = mock_auth_svc

        app = _create_test_app()
        client = TestClient(app)

        response = client.get("/test", headers={"Authorization": "Bearer ink_bearer_key"})
        assert response.status_code == 200
        data = response.json()
        assert data["api_key_info"] is not None
        assert data["api_key_info"]["key_id"] == "key-bearer"

        # Verify the key was passed without Bearer prefix
        mock_auth_svc.validate_api_key.assert_awaited_once_with("ink_bearer_key")

    @patch("src.middleware.authentication.get_auth_service")
    def test_no_key_header_leaves_state_none(self, mock_get_auth):
        """Should leave api_key_info as None when no auth header is provided."""
        app = _create_test_app()
        client = TestClient(app)

        response = client.get("/test")
        assert response.status_code == 200
        data = response.json()
        assert data["api_key_info"] is None

        # Auth service should NOT be called
        mock_get_auth.assert_not_awaited()

    @patch("src.middleware.authentication.get_auth_service")
    def test_invalid_key_leaves_state_none(self, mock_get_auth):
        """Should leave api_key_info as None when auth service returns None."""
        mock_auth_svc = AsyncMock()
        mock_auth_svc.validate_api_key = AsyncMock(return_value=None)
        mock_get_auth.return_value = mock_auth_svc

        app = _create_test_app()
        client = TestClient(app)

        response = client.get("/test", headers={"X-API-Key": "ink_bad_key"})
        assert response.status_code == 200
        data = response.json()
        assert data["api_key_info"] is None

    def test_exempt_paths_skip_validation(self):
        """Should skip auth resolution for exempt paths like /health."""
        app = _create_test_app()
        client = TestClient(app)

        # No need to mock auth service — it should never be called
        response = client.get("/health", headers={"X-API-Key": "ink_some_key"})
        assert response.status_code == 200
        data = response.json()
        # api_key_info should be None (initialized but not validated)
        assert data["api_key_info"] is None

    @patch("src.middleware.authentication.get_auth_service")
    def test_validation_error_does_not_crash(self, mock_get_auth):
        """Should catch exceptions during validation and continue without crashing."""
        mock_get_auth.side_effect = RuntimeError("Database connection failed")

        app = _create_test_app()
        client = TestClient(app)

        response = client.get("/test", headers={"X-API-Key": "ink_test_key"})
        # Should NOT return 500 — middleware catches the error
        assert response.status_code == 200
        data = response.json()
        assert data["api_key_info"] is None

    @patch("src.middleware.authentication.get_auth_service")
    def test_expired_key_leaves_state_none(self, mock_get_auth):
        """Should leave api_key_info as None when the key is expired."""
        expired_info = _make_expired_key_info()
        mock_auth_svc = AsyncMock()
        mock_auth_svc.validate_api_key = AsyncMock(return_value=expired_info)
        mock_get_auth.return_value = mock_auth_svc

        app = _create_test_app()
        client = TestClient(app)

        response = client.get("/test", headers={"X-API-Key": "ink_expired_key"})
        assert response.status_code == 200
        data = response.json()
        # Expired key should NOT be set
        assert data["api_key_info"] is None
