"""Compose-backed ingestion-to-search integration test (#15).

Exercises the real local stack end to end: upload a fixture through the public
API, wait for ingestion to finish, and assert that ``/v1/search`` returns the
indexed content.

This test is marked ``compose`` and is deselected by the default pytest run
(see ``addopts`` in pyproject). Run it against a live stack with::

    make dev            # or: make quickstart
    uv run pytest -m compose

Configuration (all have local defaults; override via env):
    PUBLIC_API_URL            default http://localhost:18000
    INTEGRATION_API_KEY       default ink_dev_local_key_001
    INTEGRATION_WORKSPACE_ID  default ws_local_001
    INTEGRATION_TIMEOUT       seconds to wait for ingestion (default 180)
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
import pytest

pytestmark = [pytest.mark.compose, pytest.mark.integration, pytest.mark.slow]

API_URL = os.environ.get("PUBLIC_API_URL", "http://localhost:18000").rstrip("/")
API_KEY = os.environ.get("INTEGRATION_API_KEY", "ink_dev_local_key_001")
WORKSPACE_ID = os.environ.get("INTEGRATION_WORKSPACE_ID", "ws_local_001")
TIMEOUT = int(os.environ.get("INTEGRATION_TIMEOUT", "180"))

# repo root: tests/integration/<file> -> parents[4]
SAMPLE_DOC = Path(
    os.environ.get(
        "INTEGRATION_SAMPLE_DOC",
        str(Path(__file__).resolve().parents[4] / "docs/examples/sample-documents/sample.txt"),
    )
)

HEADERS = {"X-API-Key": API_KEY, "X-Workspace-Id": WORKSPACE_ID}


def _require_stack(client: httpx.Client) -> None:
    """Skip (don't fail) when no healthy stack is reachable."""
    try:
        resp = client.get(f"{API_URL}/health", timeout=5)
    except httpx.HTTPError as exc:
        pytest.skip(f"public API not reachable at {API_URL}: {exc}")
    if resp.status_code != 200:
        pytest.skip(f"public API unhealthy at {API_URL}: HTTP {resp.status_code}")


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    with httpx.Client(timeout=30) as c:
        _require_stack(c)
        yield c


def _search(client: httpx.Client) -> dict:
    resp = client.post(
        f"{API_URL}/v1/search",
        headers={**HEADERS, "Content-Type": "application/json"},
        json={"query": "what retrieval modes does Inherent support", "limit": 5},
    )
    assert resp.status_code == 200, f"search failed: {resp.status_code} {resp.text}"
    return resp.json()


def test_ingestion_to_search_roundtrip(client: httpx.Client) -> None:
    assert SAMPLE_DOC.exists(), f"fixture missing: {SAMPLE_DOC}"

    # 1. Upload the fixture.
    with SAMPLE_DOC.open("rb") as fh:
        upload = client.post(
            f"{API_URL}/v1/documents",
            headers=HEADERS,
            files={"file": (SAMPLE_DOC.name, fh, "text/plain")},
        )
    assert upload.status_code == 201, f"upload failed: {upload.status_code} {upload.text}"
    document_id = upload.json()["document_id"]
    assert document_id

    # 2. Poll search until the uploaded document is indexed and retrievable.
    #    Search becoming non-empty for our document IS the signal that the full
    #    ingest pipeline (extract -> chunk -> embed -> index) completed. We poll
    #    search rather than the document-status endpoint so this test does not
    #    depend on status persistence during the pending phase (see #7).
    deadline = time.monotonic() + TIMEOUT
    found = False
    last_body: dict = {}
    while time.monotonic() < deadline:
        last_body = _search(client)
        if document_id in {r["document_id"] for r in last_body["results"]}:
            found = True
            break
        time.sleep(3)

    assert found, (
        f"uploaded document {document_id} did not become searchable within "
        f"{TIMEOUT}s (last total_results={last_body.get('total_results')})"
    )
