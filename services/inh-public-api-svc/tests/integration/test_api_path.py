"""Verify public API path is /v1/* only (no /api/v1 shim)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import create_app


@pytest.fixture
def client():
    """TestClient with the app lifespan's DB init stubbed out.

    The lifespan startup calls ``get_database()`` which opens a real asyncpg
    connection. Offline (no Postgres on :5432) that raises and aborts startup,
    so we patch the symbol the lifespan imports. These tests only exercise
    routing, not the database.
    """
    app = create_app()
    with patch("src.main.get_database", new_callable=AsyncMock):
        with TestClient(app) as test_client:
            yield test_client


def test_health_endpoint_exists(client: TestClient) -> None:
    """GET /health should return 200 (health endpoints are at root, not under /v1)."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_endpoint_not_under_v1(client: TestClient) -> None:
    """GET /v1/health should return 404 (health endpoints are at root, not under /v1)."""
    response = client.get("/v1/health")
    assert response.status_code == 404


def test_v1_documents_path_is_mounted(client: TestClient) -> None:
    """GET /v1/documents should be routed (returns 401 without auth, not 404)."""
    # No auth header → 401 Unauthorized; proves the path is routed, not 404
    response = client.get("/v1/documents")
    assert response.status_code == 401


def test_legacy_api_v1_documents_returns_404(client: TestClient) -> None:
    """GET /api/v1/documents should return 404."""
    response = client.get("/api/v1/documents")
    assert response.status_code == 404


def test_v1_search_path_is_mounted(client: TestClient) -> None:
    """POST /v1/search should be routed (returns 401 without auth, not 404)."""
    # No auth header → 401 Unauthorized; proves the path is routed, not 404
    response = client.post("/v1/search", json={"query": "test"})
    assert response.status_code == 401


def test_legacy_api_v1_search_returns_404(client: TestClient) -> None:
    """POST /api/v1/search should return 404."""
    response = client.post("/api/v1/search", json={"query": "test"})
    assert response.status_code == 404
