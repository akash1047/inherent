"""Unit tests for Prometheus metrics definitions in src/services/metrics.py."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

from src.services.metrics import (
    CHUNKS_CREATED_TOTAL,
    DOCUMENTS_PROCESSED_TOTAL,
    HTTP_REQUEST_COUNT,
    HTTP_REQUEST_LATENCY,
    POSTGRES_QUERY_DURATION,
    TEMPORAL_WORKER_RUNNING,
    WEAVIATE_WRITE_DURATION,
    WORKFLOW_DURATION,
    WORKFLOW_RUNS_TOTAL,
    get_metrics,
)

# ---------------------------------------------------------------------------
# Metric type tests
# ---------------------------------------------------------------------------


def test_http_request_count_is_counter():
    assert isinstance(HTTP_REQUEST_COUNT, Counter)


def test_http_request_latency_is_histogram():
    assert isinstance(HTTP_REQUEST_LATENCY, Histogram)


def test_workflow_runs_total_is_counter():
    assert isinstance(WORKFLOW_RUNS_TOTAL, Counter)


def test_workflow_duration_is_histogram():
    assert isinstance(WORKFLOW_DURATION, Histogram)


def test_chunks_created_total_is_counter():
    assert isinstance(CHUNKS_CREATED_TOTAL, Counter)


def test_documents_processed_total_is_counter():
    assert isinstance(DOCUMENTS_PROCESSED_TOTAL, Counter)


def test_postgres_query_duration_is_histogram():
    assert isinstance(POSTGRES_QUERY_DURATION, Histogram)


def test_weaviate_write_duration_is_histogram():
    assert isinstance(WEAVIATE_WRITE_DURATION, Histogram)


def test_temporal_worker_running_is_gauge():
    assert isinstance(TEMPORAL_WORKER_RUNNING, Gauge)


# ---------------------------------------------------------------------------
# get_metrics() output tests
# ---------------------------------------------------------------------------


def test_get_metrics_returns_bytes():
    result = get_metrics()
    assert isinstance(result, bytes)


def test_get_metrics_contains_expected_metric_names():
    result = get_metrics().decode("utf-8")
    expected_names = [
        "http_requests_total",
        "http_request_duration_seconds",
        "ingestion_workflow_runs_total",
        "ingestion_workflow_duration_seconds",
        "ingestion_chunks_created_total",
        "ingestion_documents_processed_total",
        "postgres_query_duration_seconds",
        "weaviate_write_duration_seconds",
        "temporal_worker_running",
    ]
    for name in expected_names:
        assert name in result, f"Expected metric name '{name}' not found in output"


def test_get_metrics_output_is_valid_prometheus_format():
    result = get_metrics().decode("utf-8")
    lines = [line for line in result.splitlines() if line.strip()]
    for line in lines:
        is_comment = line.startswith("#")
        is_metric = " " in line
        assert is_comment or is_metric, f"Line does not conform to Prometheus text format: {line!r}"
