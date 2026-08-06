"""Search latency + throughput benchmarks (#36).

Two flavours:

* Pure-unit tests of the percentile/summary helpers — NOT compose-marked, so
  they run offline in the default suite and give us coverage of the math.
* Live-stack benchmarks marked ``benchmark`` + ``compose`` — deselected by
  default, run only against a running local stack (``make dev``). SLOs are kept
  intentionally LOOSE: they guard against gross regressions, not tight perf, so
  CI/local runs don't flake.

Run the live benchmarks with::

    make dev
    uv run pytest tests/benchmark -m 'benchmark and compose'
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import time

import httpx
import pytest

from tests.benchmark.run_search_benchmark import (
    BenchmarkSummary,
    git_sha,
    percentile,
    run_one_search,
    summarize,
    write_benchmark_report,
)

# Where the live benchmark tests write their JSON summary (REQ-EVL-3), picked
# up by CI as an artifact the same way eval-report.json is (EVAL_REPORT env).
BENCHMARK_REPORT = os.environ.get("BENCHMARK_REPORT", "search-benchmark-report.json")

# Loose SLOs — generous so neither CI nor local laptops flake.
P95_LATENCY_SLO_MS = 2000.0
MIN_THROUGHPUT_QPS = 1.0

# Benchmark sizing (kept small to stay fast yet statistically meaningful).
LATENCY_REQUESTS = 50
THROUGHPUT_REQUESTS = 20
THROUGHPUT_CONCURRENCY = 5

QUERY = "what retrieval modes does Inherent support"


# ---------------------------------------------------------------------------
# Pure-unit coverage of the helper math (offline, no stack required).
# ---------------------------------------------------------------------------


def test_percentile_basic_ordering() -> None:
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(data, 0) == 10.0
    assert percentile(data, 100) == 50.0
    assert percentile(data, 50) == 30.0


def test_percentile_is_order_independent() -> None:
    shuffled = [50.0, 10.0, 40.0, 20.0, 30.0]
    assert percentile(shuffled, 50) == 30.0


def test_percentile_interpolates_between_ranks() -> None:
    # For [1,2,3,4], rank for p25 = 0.75 -> 1 + 0.75*(2-1) = 1.75
    assert percentile([1.0, 2.0, 3.0, 4.0], 25) == pytest.approx(1.75)


def test_percentile_single_value() -> None:
    assert percentile([42.0], 95) == 42.0


def test_percentile_rejects_empty() -> None:
    with pytest.raises(ValueError):
        percentile([], 50)


def test_percentile_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        percentile([1.0, 2.0], 150)


def test_summarize_computes_expected_fields() -> None:
    latencies = [float(x) for x in range(1, 101)]  # 1..100 ms
    summary = summarize(latencies, wall_time_s=2.0)
    assert isinstance(summary, BenchmarkSummary)
    assert summary.count == 100
    assert summary.min_ms == 1.0
    assert summary.max_ms == 100.0
    # p50 of 1..100 (linear interp over rank 49.5) -> 50.5
    assert summary.p50_ms == pytest.approx(50.5)
    assert summary.p95_ms == pytest.approx(95.05)
    # 100 requests over 2 s -> 50 QPS
    assert summary.qps == pytest.approx(50.0)


def test_summarize_rejects_empty() -> None:
    with pytest.raises(ValueError):
        summarize([], wall_time_s=1.0)


def test_git_sha_prefers_github_sha_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_SHA", "deadbeef")
    assert git_sha() == "deadbeef"


def test_write_benchmark_report_creates_file(tmp_path) -> None:
    report_path = tmp_path / "report.json"
    write_benchmark_report(report_path, "search_latency", {"p50_ms": 12.5})

    written = json.loads(report_path.read_text())
    assert written["search_latency"]["p50_ms"] == 12.5
    assert "git_sha" in written["search_latency"]


def test_write_benchmark_report_merges_existing_keys(tmp_path) -> None:
    report_path = tmp_path / "report.json"
    write_benchmark_report(report_path, "search_latency", {"p50_ms": 12.5})
    write_benchmark_report(report_path, "search_throughput", {"qps": 42.0})

    written = json.loads(report_path.read_text())
    assert written["search_latency"]["p50_ms"] == 12.5
    assert written["search_throughput"]["qps"] == 42.0


def test_write_benchmark_report_survives_corrupt_existing_file(tmp_path) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text("not valid json{{{")

    write_benchmark_report(report_path, "search_latency", {"p50_ms": 5.0})

    written = json.loads(report_path.read_text())
    assert written["search_latency"]["p50_ms"] == 5.0


# ---------------------------------------------------------------------------
# Live-stack benchmarks (deselected by default).
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
@pytest.mark.compose
def test_search_latency_p50_p95(client: httpx.Client, api_url: str, headers: dict) -> None:
    """Serial latency sweep over ~50 queries; assert a loose p95 SLO."""
    latencies = [run_one_search(client, api_url, headers, QUERY) for _ in range(LATENCY_REQUESTS)]
    summary = summarize(latencies, wall_time_s=1.0)  # wall not used for this assert
    print(
        f"\nsearch latency over {summary.count} queries: "
        f"p50={summary.p50_ms:.1f}ms p95={summary.p95_ms:.1f}ms "
        f"p99={summary.p99_ms:.1f}ms min={summary.min_ms:.1f}ms max={summary.max_ms:.1f}ms"
    )
    write_benchmark_report(
        BENCHMARK_REPORT,
        "search_latency",
        {
            "count": summary.count,
            "p50_ms": summary.p50_ms,
            "p95_ms": summary.p95_ms,
            "p99_ms": summary.p99_ms,
            "min_ms": summary.min_ms,
            "max_ms": summary.max_ms,
        },
    )
    assert (
        summary.p95_ms < P95_LATENCY_SLO_MS
    ), f"p95 latency {summary.p95_ms:.1f}ms exceeded loose SLO {P95_LATENCY_SLO_MS}ms"


@pytest.mark.benchmark
@pytest.mark.compose
def test_search_throughput(client: httpx.Client, api_url: str, headers: dict) -> None:
    """Concurrent throughput check; assert a loose minimum QPS."""
    latencies: list[float] = []
    start = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=THROUGHPUT_CONCURRENCY) as pool:
        futures = [
            pool.submit(run_one_search, client, api_url, headers, QUERY)
            for _ in range(THROUGHPUT_REQUESTS)
        ]
        for fut in concurrent.futures.as_completed(futures):
            latencies.append(fut.result())
    wall = time.monotonic() - start

    summary = summarize(latencies, wall_time_s=wall)
    print(
        f"\nsearch throughput: {summary.qps:.2f} QPS over {summary.count} requests "
        f"at concurrency {THROUGHPUT_CONCURRENCY} (wall {wall:.2f}s)"
    )
    write_benchmark_report(
        BENCHMARK_REPORT,
        "search_throughput",
        {
            "count": summary.count,
            "qps": summary.qps,
            "concurrency": THROUGHPUT_CONCURRENCY,
        },
    )
    assert (
        summary.qps > MIN_THROUGHPUT_QPS
    ), f"throughput {summary.qps:.2f} QPS below loose floor {MIN_THROUGHPUT_QPS} QPS"
