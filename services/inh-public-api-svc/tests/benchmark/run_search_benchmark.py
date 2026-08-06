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
import json
import math
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

DEFAULT_API_URL = os.environ.get("PUBLIC_API_URL", "http://localhost:18000").rstrip("/")
DEFAULT_API_KEY = os.environ.get("INTEGRATION_API_KEY", "ink_dev_local_key_001")
DEFAULT_WORKSPACE_ID = os.environ.get("INTEGRATION_WORKSPACE_ID", "ws_local_001")
DEFAULT_QUERY = "what retrieval modes does Inherent support"
DEFAULT_BENCHMARK_REPORT = os.environ.get("BENCHMARK_REPORT", "search-benchmark-report.json")


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


def git_sha() -> str:
    """Return the commit SHA this benchmark ran against.

    Prefers ``GITHUB_SHA`` (set by Actions, cheap and exact) and falls back to
    ``git rev-parse HEAD`` for local runs; ``"unknown"`` if neither works (e.g.
    a source tree with no ``.git``, such as an extracted release tarball).
    """
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def write_benchmark_report(report_path: str | Path, key: str, payload: dict) -> None:
    """Merge ``payload`` under ``key`` into the JSON report at ``report_path``.

    Merges into any existing file rather than overwriting it (REQ-EVL-3):
    the latency and throughput benchmarks run in the same pytest session and
    each contributes its own top-level key to one shared report artifact,
    same pattern as the retrieval eval report CI already uploads. A corrupt
    or missing existing file is treated as an empty report rather than
    failing the benchmark on its own reporting step.

    Keep in sync: duplicated near-verbatim (along with ``git_sha()`` above)
    in ``services/inh-ingestion-svc/tests/benchmark/benchmark_report.py`` --
    separate Python packages, no shared dependency between them, and no test
    catches the two drifting apart if one changes without the other.
    """
    path = Path(report_path)
    report: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
        except json.JSONDecodeError:
            loaded = {}
        # A valid-but-non-dict file (e.g. `[]`) parses fine but isn't
        # mergeable -- treat it the same as corrupt rather than letting
        # `report[key] = ...` raise TypeError below (#146 cross-review).
        report = loaded if isinstance(loaded, dict) else {}
    report[key] = {**payload, "git_sha": git_sha()}
    path.write_text(json.dumps(report, indent=2, sort_keys=True))


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
    parser.add_argument(
        "--report",
        default=DEFAULT_BENCHMARK_REPORT,
        help=f"JSON report path to write/merge (default {DEFAULT_BENCHMARK_REPORT})",
    )
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
    write_benchmark_report(
        args.report,
        "cli_search",
        {
            "count": summary.count,
            "p50_ms": summary.p50_ms,
            "p95_ms": summary.p95_ms,
            "p99_ms": summary.p99_ms,
            "min_ms": summary.min_ms,
            "max_ms": summary.max_ms,
            "qps": summary.qps,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
