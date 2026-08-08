"""trace_id must be present on unhandled-exception (5xx) responses (#222).

Root cause: registering a catch-all handler via ``@app.exception_handler(Exception)``
(what ``setup_exception_handlers`` used to do) makes Starlette treat it as the
handler for ``ServerErrorMiddleware`` -- see ``Starlette.build_middleware_stack``,
which special-cases ``key in (500, Exception)``. ``ServerErrorMiddleware`` is always
the OUTERMOST middleware, wrapping every custom middleware including
``RequestContextMiddleware`` (the one that sets the ``request_id``/``trace_id``
context var). So any exception that isn't one of the specifically-registered types
(``InherentAPIError``, ``RequestValidationError``, ``StarletteHTTPException``) skips
past all custom middleware, and the catch-all handler runs OUTSIDE
``RequestContextMiddleware`` with no request context to read -- ``trace_id`` is
always ``None`` on exactly this path, which is the unhandled/"unexpected error" 500
the reporter saw in production.

These tests assemble the real ``create_app()`` stack (not a hand-built mini app),
the same pattern as ``test_middleware_order.py``, so the real middleware ordering is
under test, not a mock of it.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.models.api_key import APIKeyInfo
from src.services.database import get_database as documents_get_database


def _valid_key_info() -> APIKeyInfo:
    return APIKeyInfo(
        key_id="key-trace-id",
        user_id="user-trace-id",
        workspace_id="ws-trace-id",
        permissions=["read", "search", "write"],
        rate_limit=5000,
    )


async def _raise_unexpected_error():
    """Stand-in dependency that raises a plain (unregistered) exception type.

    Not an ``InherentAPIError``/``RequestValidationError``/``HTTPException`` --
    those already have specific handlers registered on ``ExceptionMiddleware``
    (innermost, inside ``RequestContextMiddleware``) and were never affected by
    this bug. A bare ``RuntimeError`` is what actually falls through to the
    catch-all path.
    """
    raise RuntimeError("simulated unexpected error")


@pytest.fixture
def client():
    """TestClient for the real app, DB init stubbed, DB dependency raising.

    ``raise_server_exceptions=False`` is required: an exception NOT converted to a
    response by the app is otherwise re-raised into the test by Starlette's
    TestClient, instead of returned as a response to assert on.
    """
    app = create_app()
    app.dependency_overrides[documents_get_database] = _raise_unexpected_error
    with patch("src.main.get_database", new_callable=AsyncMock):
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client


def test_unhandled_exception_response_has_trace_id(client: TestClient) -> None:
    """An unhandled exception must still produce a `trace_id` in the problem+json body."""
    with patch(
        "src.middleware.authentication.get_auth_service",
        new_callable=AsyncMock,
        return_value=AsyncMock(validate_api_key=AsyncMock(return_value=_valid_key_info())),
    ):
        response = client.get(
            "/v1/documents",
            headers={"X-API-Key": "ink_valid_test_key", "X-Workspace-Id": "ws-trace-id"},
        )

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body.get("trace_id"), f"trace_id missing/empty on 5xx body: {body}"


def test_unhandled_exception_trace_id_matches_request_id_header(client: TestClient) -> None:
    """The body's trace_id should be the same correlation id echoed in X-Request-ID.

    Proves it's the real per-request id (from RequestContextMiddleware), not a
    coincidentally-truthy placeholder.
    """
    with patch(
        "src.middleware.authentication.get_auth_service",
        new_callable=AsyncMock,
        return_value=AsyncMock(validate_api_key=AsyncMock(return_value=_valid_key_info())),
    ):
        response = client.get(
            "/v1/documents",
            headers={
                "X-API-Key": "ink_valid_test_key",
                "X-Workspace-Id": "ws-trace-id",
                "X-Request-ID": "trace-id-test-fixed-value",
            },
        )

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "trace-id-test-fixed-value"
    assert response.json()["trace_id"] == "trace-id-test-fixed-value"
