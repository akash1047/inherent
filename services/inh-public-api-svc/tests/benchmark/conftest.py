"""Shared fixtures for the search benchmark suite (#36).

Provides a live-stack httpx client, request headers, and a skip-if-no-stack
guard mirroring the compose integration tests. Benchmarks are marked
``benchmark`` + ``compose`` so they are deselected by the default pytest run
and only execute against a running local stack.

Configuration (all have local defaults; override via env):
    PUBLIC_API_URL            default http://localhost:18000
    INTEGRATION_API_KEY       default ink_dev_local_key_001
    INTEGRATION_WORKSPACE_ID  default ws_local_001
"""

from __future__ import annotations

import os

import httpx
import pytest

API_URL = os.environ.get("PUBLIC_API_URL", "http://localhost:18000").rstrip("/")
API_KEY = os.environ.get("INTEGRATION_API_KEY", "ink_dev_local_key_001")
WORKSPACE_ID = os.environ.get("INTEGRATION_WORKSPACE_ID", "ws_local_001")

HEADERS = {
    "X-API-Key": API_KEY,
    "X-Workspace-Id": WORKSPACE_ID,
    "Content-Type": "application/json",
}


def _require_stack(client: httpx.Client) -> None:
    """Skip (don't fail) when no healthy public API is reachable."""
    try:
        resp = client.get(f"{API_URL}/health", timeout=5)
    except httpx.HTTPError as exc:
        pytest.skip(f"public API not reachable at {API_URL}: {exc}")
    if resp.status_code != 200:
        pytest.skip(f"public API unhealthy at {API_URL}: HTTP {resp.status_code}")


@pytest.fixture(scope="module")
def api_url() -> str:
    return API_URL


@pytest.fixture(scope="module")
def headers() -> dict[str, str]:
    return dict(HEADERS)


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    with httpx.Client(timeout=30) as c:
        _require_stack(c)
        yield c
