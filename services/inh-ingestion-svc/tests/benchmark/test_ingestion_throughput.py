"""Ingestion throughput benchmark (#36).

Measures end-to-end ingestion throughput as *time-to-searchable*: upload a
small batch of documents through the public API, then poll ``/v1/search`` until
each becomes retrievable (the signal that extract -> chunk -> embed -> index
finished). Reports docs/sec and asserts a LOOSE upper-bound on total time so
it guards against gross regressions without flaking.

Marked ``benchmark`` + ``compose`` so it is deselected by the default pytest
run and only executes against a live local stack (``make dev``). It is
skip-guarded if the public API is not reachable.

Run with::

    make dev
    uv run pytest tests/benchmark -m 'benchmark and compose'

Configuration (all have local defaults; override via env):
    PUBLIC_API_URL             default http://localhost:18000
    INTEGRATION_API_KEY        default ink_dev_local_key_001
    INTEGRATION_WORKSPACE_ID   default ws_local_001
    BENCHMARK_BATCH_SIZE       documents to upload (default 5)
    BENCHMARK_TIMEOUT          seconds budget for the whole batch (default 300)
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import pytest

from tests.benchmark.benchmark_report import write_benchmark_report

try:  # httpx is in ingestion dev deps; fall back to stdlib if absent.
    import httpx

    _HAVE_HTTPX = True
except ImportError:  # pragma: no cover - exercised only without httpx
    _HAVE_HTTPX = False

pytestmark = [pytest.mark.benchmark, pytest.mark.compose]

API_URL = os.environ.get("PUBLIC_API_URL", "http://localhost:18000").rstrip("/")
API_KEY = os.environ.get("INTEGRATION_API_KEY", "ink_dev_local_key_001")
WORKSPACE_ID = os.environ.get("INTEGRATION_WORKSPACE_ID", "ws_local_001")
BATCH_SIZE = int(os.environ.get("BENCHMARK_BATCH_SIZE", "5"))
# Loose SLO: the whole batch must become searchable within this generous budget.
TIMEOUT = int(os.environ.get("BENCHMARK_TIMEOUT", "300"))
# Where this benchmark writes its JSON summary (REQ-EVL-3), picked up by CI as
# an artifact the same way the public-api search benchmarks report theirs.
BENCHMARK_REPORT = Path(os.environ.get("BENCHMARK_REPORT", "ingestion-benchmark-report.json"))

HEADERS = {"X-API-Key": API_KEY, "X-Workspace-Id": WORKSPACE_ID}

# repo root: tests/benchmark/<file> -> parents[4]
SAMPLE_DOC = Path(
    os.environ.get(
        "INTEGRATION_SAMPLE_DOC",
        str(Path(__file__).resolve().parents[4] / "docs/examples/sample-documents/sample.txt"),
    )
)


def _require_stack() -> None:
    """Skip (don't fail) when no healthy public API is reachable."""
    if not _HAVE_HTTPX:
        pytest.skip("httpx not available for the ingestion benchmark")
    try:
        resp = httpx.get(f"{API_URL}/health", timeout=5)
    except httpx.HTTPError as exc:
        pytest.skip(f"public API not reachable at {API_URL}: {exc}")
    if resp.status_code != 200:
        pytest.skip(f"public API unhealthy at {API_URL}: HTTP {resp.status_code}")


def _upload(client: httpx.Client, content: bytes, filename: str) -> str:
    resp = client.post(
        f"{API_URL}/v1/documents",
        headers=HEADERS,
        files={"file": (filename, content, "text/plain")},
    )
    assert resp.status_code == 201, f"upload of {filename} failed: {resp.status_code} {resp.text}"
    document_id = resp.json()["document_id"]
    assert document_id
    return document_id


def _search_ids(client: httpx.Client) -> set[str]:
    resp = client.post(
        f"{API_URL}/v1/search",
        headers={**HEADERS, "Content-Type": "application/json"},
        json={"query": "Inherent knowledge base sample document content", "limit": 50},
    )
    assert resp.status_code == 200, f"search failed: {resp.status_code} {resp.text}"
    return {r["document_id"] for r in resp.json()["results"]}


def test_ingestion_batch_time_to_searchable() -> None:
    """Upload a small batch and measure docs/sec time-to-searchable."""
    _require_stack()
    assert SAMPLE_DOC.exists(), f"fixture missing: {SAMPLE_DOC}"

    base = SAMPLE_DOC.read_bytes()
    run_id = uuid.uuid4().hex[:8]

    with httpx.Client(timeout=30) as client:
        start = time.monotonic()

        # 1. Upload BATCH_SIZE copies under unique filenames so each is a
        #    distinct, deduped document (unique name -> unique content hash via
        #    the prepended marker line).
        pending: set[str] = set()
        for i in range(BATCH_SIZE):
            marker = f"benchmark-run {run_id} copy {i}\n".encode()
            filename = f"bench_{run_id}_{i}.txt"
            pending.add(_upload(client, marker + base, filename))

        # 2. Poll search until every uploaded document is retrievable.
        deadline = start + TIMEOUT
        remaining = set(pending)
        while remaining and time.monotonic() < deadline:
            remaining -= _search_ids(client)
            if remaining:
                time.sleep(3)

        elapsed = time.monotonic() - start

    assert not remaining, (
        f"{len(remaining)}/{BATCH_SIZE} documents did not become searchable "
        f"within loose budget {TIMEOUT}s"
    )

    docs_per_sec = BATCH_SIZE / elapsed if elapsed > 0 else float("inf")
    print(
        f"\ningestion throughput: {BATCH_SIZE} docs searchable in {elapsed:.1f}s "
        f"= {docs_per_sec:.3f} docs/sec"
    )
    write_benchmark_report(
        BENCHMARK_REPORT,
        "ingestion_throughput",
        {
            "batch_size": BATCH_SIZE,
            "elapsed_s": elapsed,
            "docs_per_sec": docs_per_sec,
        },
    )
    assert elapsed < TIMEOUT, f"batch took {elapsed:.1f}s, exceeding loose budget {TIMEOUT}s"
