"""Offline unit tests for the benchmark JSON report helpers (#36, REQ-EVL-3).

Pure-logic coverage only -- no network, no Compose stack -- so these run in
the default offline suite unlike the live benchmarks in
test_ingestion_throughput.py (module-marked ``benchmark`` + ``compose``).
"""

from __future__ import annotations

import json

import pytest

from tests.benchmark.benchmark_report import git_sha, write_benchmark_report


def test_git_sha_prefers_github_sha_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_SHA", "deadbeef")
    assert git_sha() == "deadbeef"


def test_write_benchmark_report_creates_file(tmp_path) -> None:
    report_path = tmp_path / "report.json"
    write_benchmark_report(report_path, "ingestion_throughput", {"docs_per_sec": 1.5})

    written = json.loads(report_path.read_text())
    assert written["ingestion_throughput"]["docs_per_sec"] == 1.5
    assert "git_sha" in written["ingestion_throughput"]


def test_write_benchmark_report_merges_existing_keys(tmp_path) -> None:
    report_path = tmp_path / "report.json"
    write_benchmark_report(report_path, "ingestion_throughput", {"docs_per_sec": 1.5})
    write_benchmark_report(report_path, "other_key", {"value": 1})

    written = json.loads(report_path.read_text())
    assert written["ingestion_throughput"]["docs_per_sec"] == 1.5
    assert written["other_key"]["value"] == 1


def test_write_benchmark_report_survives_corrupt_existing_file(tmp_path) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text("not valid json{{{")

    write_benchmark_report(report_path, "ingestion_throughput", {"docs_per_sec": 2.0})

    written = json.loads(report_path.read_text())
    assert written["ingestion_throughput"]["docs_per_sec"] == 2.0
