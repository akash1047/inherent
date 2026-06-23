"""Standalone search benchmark CLI (#36).

Fires N search queries at concurrency C against a live public API stack,
collects each response's ``processing_time_ms``, and reports latency
percentiles (p50/p95/p99), min/max, and throughput (QPS).

The percentile / summary helpers are importable and pure (no network), so the
math can be unit-tested without a running stack
(see ``test_search_latency_throughput.py``).

Usage::

    uv run python tests/benchmark/run_search_benchmark.py \
        --requests 100 --concurrency 5 \
        --query "what retrieval modes does Inherent support"

Configuration (CLI flags override env, env overrides defaults):
    PUBLIC_API_URL            default http://localhost:18000
    INTEGRATION_API_KEY       default ink_dev_local_key_001
    INTEGRATION_WORKSPACE_ID  default ws_local_001
"""

from __future__ import annotations

import argparse
import concurrent.futures
import math
import os
import time
from dataclasses import dataclass

import httpx

DEFAULT_API_URL = os.environ.get("PUBLIC_API_URL", "http://localhost:18000").rstrip("/")
DEFAULT_API_KEY = os.environ.get("INTEGRATION_API_KEY", "ink_dev_local_key_001")
DEFAULT_WORKSPACE_ID = os.environ.get("INTEGRATION_WORKSPACE_ID", "ws_local_001")
DEFAULT_QUERY = "what retrieval modes does Inherent support"


# ---------------------------------------------------------------------------
# Pure helpers (no network) — unit-testable offline.
# ---------------------------------------------------------------------------


def percentile(values: list[float], pct: float) -> float:
    """Return the ``pct`` percentile (0..100) of ``values``.

    Uses linear interpolation between closest ranks (the "inclusive" method,
    matching ``numpy.percentile``/``statistics.quantiles`` defaults closely
    enough for benchmarking). Raises ``ValueError`` on empty input or an
    out-of-range percentile.
    """
    if not values:
        raise ValueError("percentile() requires at least one value")
    if not 0 <= pct <= 100:
        raise ValueError(f"percentile must be in [0, 100], got {pct}")

    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])

    rank = (pct / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[low])
    frac = rank - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * frac)


@dataclass
class BenchmarkSummary:
    """Aggregated results of a benchmark run."""

    count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    qps: float

    def format(self) -> str:
        return (
            f"requests:   {self.count}\n"
            f"p50:        {self.p50_ms:.2f} ms\n"
            f"p95:        {self.p95_ms:.2f} ms\n"
            f"p99:        {self.p99_ms:.2f} ms\n"
            f"min:        {self.min_ms:.2f} ms\n"
            f"max:        {self.max_ms:.2f} ms\n"
            f"throughput: {self.qps:.2f} QPS"
        )


def summarize(latencies_ms: list[float], wall_time_s: float) -> BenchmarkSummary:
    """Build a :class:`BenchmarkSummary` from per-request latencies (ms).

    ``wall_time_s`` is the total wall-clock duration of the run, used to derive
    QPS. Raises ``ValueError`` on empty input.
    """
    if not latencies_ms:
        raise ValueError("summarize() requires at least one latency sample")
    qps = len(latencies_ms) / wall_time_s if wall_time_s > 0 else 0.0
    return BenchmarkSummary(
        count=len(latencies_ms),
        p50_ms=percentile(latencies_ms, 50),
        p95_ms=percentile(latencies_ms, 95),
        p99_ms=percentile(latencies_ms, 99),
        min_ms=min(latencies_ms),
        max_ms=max(latencies_ms),
        qps=qps,
    )


# ---------------------------------------------------------------------------
# Live-stack benchmark runner.
# ---------------------------------------------------------------------------


def _headers(api_key: str, workspace_id: str) -> dict[str, str]:
    return {
        "X-API-Key": api_key,
        "X-Workspace-Id": workspace_id,
        "Content-Type": "application/json",
    }


def run_one_search(
    client: httpx.Client,
    api_url: str,
    headers: dict[str, str],
    query: str,
    limit: int = 5,
) -> float:
    """Issue one search and return the server-reported ``processing_time_ms``."""
    resp = client.post(
        f"{api_url}/v1/search",
        headers=headers,
        json={"query": query, "limit": limit},
    )
    resp.raise_for_status()
    return float(resp.json()["processing_time_ms"])


def run_benchmark(
    api_url: str,
    api_key: str,
    workspace_id: str,
    query: str,
    requests: int,
    concurrency: int,
    limit: int = 5,
) -> BenchmarkSummary:
    """Fire ``requests`` searches at ``concurrency`` and summarize latencies."""
    headers = _headers(api_key, workspace_id)
    latencies: list[float] = []

    start = time.monotonic()
    with httpx.Client(timeout=30) as client:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [
                pool.submit(run_one_search, client, api_url, headers, query, limit)
                for _ in range(requests)
            ]
            for fut in concurrent.futures.as_completed(futures):
                latencies.append(fut.result())
    wall = time.monotonic() - start

    return summarize(latencies, wall)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search latency/throughput benchmark")
    parser.add_argument("--requests", type=int, default=100, help="number of queries (default 100)")
    parser.add_argument("--concurrency", type=int, default=5, help="concurrent workers (default 5)")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="search query string")
    parser.add_argument("--limit", type=int, default=5, help="results per query (default 5)")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="public API base URL")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="X-API-Key value")
    parser.add_argument("--workspace-id", default=DEFAULT_WORKSPACE_ID, help="X-Workspace-Id value")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    api_url = args.api_url.rstrip("/")
    print(
        f"Benchmarking {api_url}/v1/search "
        f"({args.requests} requests, concurrency {args.concurrency})...\n"
    )
    summary = run_benchmark(
        api_url=api_url,
        api_key=args.api_key,
        workspace_id=args.workspace_id,
        query=args.query,
        requests=args.requests,
        concurrency=args.concurrency,
        limit=args.limit,
    )
    print(summary.format())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
