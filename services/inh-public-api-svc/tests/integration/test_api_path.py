"""Verify public API path is /v1/* only (no /api/v1 shim)."""

from fastapi.testclient import TestClient

from src.main import create_app


def test_health_endpoint_exists() -> None:
    """GET /health should return 200 (health endpoints are at root, not under /v1)."""
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200


def test_health_endpoint_not_under_v1() -> None:
    """GET /v1/health should return 404 (health endpoints are at root, not under /v1)."""
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/v1/health")
        assert response.status_code == 404


def test_v1_documents_path_is_mounted() -> None:
    """GET /v1/documents should be routed (returns 401 without auth, not 404)."""
    app = create_app()
    with TestClient(app) as client:
        # No auth header → 401 Unauthorized; proves the path is routed, not 404
        response = client.get("/v1/documents")
        assert response.status_code == 401


def test_legacy_api_v1_documents_returns_404() -> None:
    """GET /api/v1/documents should return 404."""
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/documents")
        assert response.status_code == 404


def test_v1_search_path_is_mounted() -> None:
    """POST /v1/search should be routed (returns 401 without auth, not 404)."""
    app = create_app()
    with TestClient(app) as client:
        # No auth header → 401 Unauthorized; proves the path is routed, not 404
        response = client.post("/v1/search", json={"query": "test"})
        assert response.status_code == 401


def test_legacy_api_v1_search_returns_404() -> None:
    """POST /api/v1/search should return 404."""
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/api/v1/search", json={"query": "test"})
        assert response.status_code == 404
