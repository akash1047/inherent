"""Middleware ordering regression (#149 follow-up).

Starlette's ``add_middleware`` prepends to the stack and builds it with
``reversed(...)``, so the LAST middleware added is the OUTERMOST one and runs
first on the request. ``create_app`` previously registered Authentication
before RateLimiting/AuditLogging, which — under those real Starlette
semantics — made RateLimiting run *before* Authentication on every request.
Every request therefore looked unauthenticated to the rate limiter regardless
of whether it carried a valid key, which is the true root cause of the
cascading 429s under load: the per-key bucket/limit was dead code.

These tests assemble the real ``create_app()`` stack (not a hand-built mini
app) so a future reordering mistake is caught here instead of only in
production traffic.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.core.rate_limiter import RateLimitInfo, RateLimitResult
from src.main import create_app
from src.models.api_key import APIKeyInfo


@pytest.fixture
def client():
    """TestClient for the real app with DB init stubbed (see test_api_path.py)."""
    app = create_app()
    with patch("src.main.get_database", new_callable=AsyncMock):
        with TestClient(app) as test_client:
            yield test_client


def _valid_key_info() -> APIKeyInfo:
    return APIKeyInfo(
        key_id="key-mw-order",
        user_id="user-mw-order",
        workspace_id="ws-mw-order",
        permissions=["read", "search", "write"],
        rate_limit=5000,
    )


def test_valid_key_is_bucketed_by_key_not_by_ip(client: TestClient) -> None:
    """A valid API key must reach RateLimitingMiddleware with api_key_info set,
    proving AuthenticationMiddleware's dispatch runs before RateLimitingMiddleware's
    in the assembled app -- not just in isolated middleware unit tests.

    The limiter is forced to deny (429) so the request never reaches the real
    route handler -- only the middleware-ordering question is under test here,
    not the handler's own (DB-backed) behavior.
    """
    limiter = AsyncMock()
    limiter.check_rate_limit = AsyncMock(
        return_value=RateLimitResult(
            allowed=False,
            info=RateLimitInfo(limit=5000, remaining=0, reset_at=0, window_seconds=60),
        )
    )

    with (
        patch(
            "src.middleware.authentication.get_auth_service",
            new_callable=AsyncMock,
            return_value=AsyncMock(validate_api_key=AsyncMock(return_value=_valid_key_info())),
        ),
        patch("src.middleware.rate_limiting.get_rate_limiter", return_value=limiter),
    ):
        response = client.get(
            "/v1/documents",
            headers={"X-API-Key": "ink_valid_test_key", "X-Workspace-Id": "ws-mw-order"},
        )

    assert response.status_code == 429
    limiter.check_rate_limit.assert_awaited_once()
    kwargs = limiter.check_rate_limit.await_args.kwargs
    assert kwargs["key"] == "key:key-mw-order"
    assert kwargs["limit"] == 5000


def test_no_key_request_is_bucketed_by_ip(client: TestClient) -> None:
    """No key -> Authentication leaves api_key_info unset -> IP bucket (unchanged
    behavior), confirming the ordering fix didn't break the unauthenticated path."""
    limiter = AsyncMock()
    limiter.check_rate_limit = AsyncMock(
        return_value=RateLimitResult(
            allowed=False,
            info=RateLimitInfo(limit=30, remaining=0, reset_at=0, window_seconds=60),
        )
    )

    with patch("src.middleware.rate_limiting.get_rate_limiter", return_value=limiter):
        response = client.get("/v1/documents")

    assert response.status_code == 429
    limiter.check_rate_limit.assert_awaited_once()
    kwargs = limiter.check_rate_limit.await_args.kwargs
    assert kwargs["key"].startswith("ip:")
    assert kwargs["limit"] == 30
