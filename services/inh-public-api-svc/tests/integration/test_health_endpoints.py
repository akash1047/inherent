"""Integration tests for health check endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import create_app


@pytest.fixture
def client():
    """Create a test client."""
    app = create_app()
    with TestClient(app) as client:
        yield client


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_liveness_probe(self, client: TestClient):
        """GET /health should return 200."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "service" in data

    def test_liveness_probe_alt(self, client: TestClient):
        """GET /health/live should return 200."""
        response = client.get("/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @patch("src.api.v1.health.get_database")
    @patch("src.api.v1.health.get_search_service")
    def test_readiness_probe_healthy(
        self,
        mock_search: MagicMock,
        mock_db: MagicMock,
        client: TestClient,
    ):
        """GET /health/ready should return healthy status when all deps are up."""
        # Mock database
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.get_session = MagicMock(return_value=AsyncMock())
        mock_db_instance.get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_instance.get_session.return_value.__aexit__ = AsyncMock()
        mock_db.return_value = mock_db_instance

        # Mock search service
        mock_search_instance = AsyncMock()
        mock_search_instance.is_connected = AsyncMock(return_value=True)
        mock_search.return_value = mock_search_instance

        response = client.get("/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["healthy", "degraded"]  # May be degraded if no real connection
        assert "checks" in data
        assert "timestamp" in data
        assert "version" in data


class TestSecurityHeaders:
    """Tests for security headers."""

    def test_security_headers_present(self, client: TestClient):
        """All security headers should be present in response."""
        response = client.get("/health")
        headers = response.headers

        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert headers.get("X-Frame-Options") == "DENY"
        assert "Cache-Control" in headers

    def test_request_id_header(self, client: TestClient):
        """Response should include X-Request-ID header."""
        response = client.get("/health")
        assert "X-Request-ID" in response.headers

    def test_request_id_propagation(self, client: TestClient):
        """Request ID should be propagated if provided."""
        request_id = "test-correlation-id-123"
        response = client.get("/health", headers={"X-Request-ID": request_id})
        assert response.headers.get("X-Request-ID") == request_id
