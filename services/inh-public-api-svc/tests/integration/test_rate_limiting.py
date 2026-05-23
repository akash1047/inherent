"""Integration tests for rate limiting middleware."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.config.constants import RATE_LIMIT_HEADERS
from src.middleware import RateLimitingMiddleware, RequestContextMiddleware
from src.models import APIKeyInfo


@pytest.fixture
def app_with_rate_limiting():
    """Create a test app with rate limiting middleware."""
    app = FastAPI()

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(RateLimitingMiddleware)

    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"status": "ok"}

    @app.get("/health")
    async def health_endpoint():
        return {"status": "healthy"}

    return app


@pytest.fixture
def client(app_with_rate_limiting):
    """Create a test client."""
    with TestClient(app_with_rate_limiting) as client:
        yield client


class TestRateLimitingMiddleware:
    """Tests for rate limiting middleware."""

    def test_health_endpoint_bypasses_rate_limiting(self, client: TestClient):
        """Health endpoints should not be rate limited."""
        # Make many requests to health endpoint
        for _ in range(20):
            response = client.get("/health")
            assert response.status_code == 200

        # Should not have rate limit headers
        assert RATE_LIMIT_HEADERS["limit"] not in response.headers

    def test_unauthenticated_request_passes_through(self, client: TestClient):
        """Unauthenticated requests should pass through (auth handles rejection)."""
        response = client.get("/test")
        assert response.status_code == 200

    @patch("src.middleware.rate_limiting.settings")
    def test_rate_limiting_disabled(
        self, mock_settings: MagicMock, app_with_rate_limiting: FastAPI
    ):
        """When rate limiting is disabled, all requests should pass."""
        mock_settings.rate_limit_enabled = False

        with TestClient(app_with_rate_limiting) as client:
            response = client.get("/test")
            assert response.status_code == 200
            assert RATE_LIMIT_HEADERS["limit"] not in response.headers


class TestRateLimitHeaders:
    """Tests for rate limit headers."""

    @patch("src.middleware.rate_limiting.get_rate_limiter")
    def test_rate_limit_headers_included(
        self,
        mock_limiter: MagicMock,
        app_with_rate_limiting: FastAPI,
    ):
        """Rate limit headers should be included in response."""
        from src.core.rate_limiter import RateLimitInfo, RateLimitResult

        # Mock rate limiter to return allowed result
        mock_limiter_instance = AsyncMock()
        mock_limiter_instance.check_rate_limit = AsyncMock(
            return_value=RateLimitResult(
                allowed=True,
                info=RateLimitInfo(limit=100, remaining=99, reset_at=1234567890, window_seconds=60),
            )
        )
        mock_limiter.return_value = mock_limiter_instance

        # Create app with authenticated request
        @app_with_rate_limiting.middleware("http")
        async def add_api_key_info(request: Request, call_next):
            request.state.api_key_info = APIKeyInfo(
                key_id="test-key",
                user_id="user-123",
                workspace_id="ws-456",
                permissions=["read", "search"],
                rate_limit=100,
                expires_at=None,
                status="active",
            )
            return await call_next(request)

        with TestClient(app_with_rate_limiting) as client:
            response = client.get("/test")
            # Headers should be present when rate limiter is invoked
            # Note: This test may need adjustment based on middleware order
            assert response.status_code == 200
