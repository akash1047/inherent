"""Offline unit tests for the baseline-comparison CLI in ``eval_gate.py``.

Hand-computed expected values so the gate logic is pinned exactly. No services
required; runs in the default ``-m 'not compose'`` suite. The live-stack wiring
(compose test calling ``find_regressions`` against real metrics) lives in
``test_compose_retrieval_regression.py``.
"""

from __future__ import annotations

import json

import pytest

from tests.evals.eval_gate import (
    Regression,
    find_regressions,
    format_regressions,
    load_doc_keys,
    load_metrics,
    main,
    ratchet_baseline,
)

pytestmark = pytest.mark.retrieval_eval


# ---------------------------------------------------------------------------
# load_metrics
# ---------------------------------------------------------------------------


def test_load_metrics_drops_documentation_keys(tmp_path):
    path = tmp_path / "metrics.json"
    path.write_text(
        json.dumps(
            {
                "_comment": "not a mode",
                "hybrid": {"recall@5": 0.5},
            }
        )
    )
    assert load_metrics(path) == {"hybrid": {"recall@5": 0.5}}


def test_load_metrics_missing_file_returns_empty(tmp_path):
    assert load_metrics(tmp_path / "does-not-exist.json") == {}


def test_load_metrics_invalid_json_returns_empty(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not json")
    assert load_metrics(path) == {}


# ---------------------------------------------------------------------------
# load_doc_keys
# ---------------------------------------------------------------------------


def test_load_doc_keys_returns_only_underscore_keys(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps({"_comment": "policy", "hybrid": {"recall@5": 0.5}})
    )
    assert load_doc_keys(path) == {"_comment": "policy"}


def test_load_doc_keys_missing_file_returns_empty(tmp_path):
    assert load_doc_keys(tmp_path / "nope.json") == {}


# ---------------------------------------------------------------------------
# ratchet CLI (main) preserves documentation keys
# ---------------------------------------------------------------------------


def test_cli_ratchet_preserves_comment_and_ratchets(tmp_path):
    """The ratchet CLI must keep the baseline's _comment and raise metrics.

    Regression guard for the doc-key-stripping bug: the first ratchet used to
    drop _comment (which documents the hard-gate policy) entirely.
    """
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"_comment": "policy note", "hybrid": {"recall@5": 0.50}})
    )
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"hybrid": {"recall@5": 0.70}}))
    out = tmp_path / "out.json"

    exit_code = main(
        ["ratchet", "--report", str(report), "--baseline", str(baseline), "--out", str(out)]
    )

    assert exit_code == 0
    written = json.loads(out.read_text())
    assert written["_comment"] == "policy note"
    assert written["hybrid"]["recall@5"] == 0.70


# ---------------------------------------------------------------------------
# find_regressions
# ---------------------------------------------------------------------------


def test_no_regression_when_current_matches_baseline():
    baseline = {"hybrid": {"recall@5": 0.5}}
    current = {"hybrid": {"recall@5": 0.5}}
    assert find_regressions(current, baseline) == []


def test_no_regression_when_current_improves():
    baseline = {"hybrid": {"recall@5": 0.5}}
    current = {"hybrid": {"recall@5": 0.9}}
    assert find_regressions(current, baseline) == []


def test_no_regression_within_tolerance():
    baseline = {"hybrid": {"recall@5": 0.50}}
    current = {"hybrid": {"recall@5": 0.49}}
    assert find_regressions(current, baseline, tolerance=0.02) == []


def test_regression_flagged_beyond_tolerance():
    baseline = {"hybrid": {"recall@5": 0.50}}
    current = {"hybrid": {"recall@5": 0.40}}
    regressions = find_regressions(current, baseline, tolerance=0.02)
    assert regressions == [Regression("hybrid", "recall@5", current=0.40, baseline=0.50)]


def test_regression_delta_is_negative():
    reg = Regression("hybrid", "recall@5", current=0.40, baseline=0.50)
    assert reg.delta == pytest.approx(-0.10)


def test_missing_baseline_metric_cannot_regress():
    """A metric absent from baseline (e.g. newly added) has nothing to regress against."""
    baseline: dict[str, dict[str, float]] = {}
    current = {"hybrid": {"recall@5": 0.0}}
    assert find_regressions(current, baseline) == []


def test_missing_current_metric_counts_as_zero():
    """A metric the baseline tracks but the current run didn't produce is treated as 0.0.

    This catches a broken/incomplete eval run silently passing the gate.
    """
    baseline = {"hybrid": {"recall@5": 0.50}}
    current: dict[str, dict[str, float]] = {"hybrid": {}}
    regressions = find_regressions(current, baseline, tolerance=0.02)
    assert regressions == [Regression("hybrid", "recall@5", current=0.0, baseline=0.50)]


def test_missing_current_metric_at_zero_baseline_is_not_a_regression():
    baseline = {"hybrid": {"recall@5": 0.0}}
    current: dict[str, dict[str, float]] = {"hybrid": {}}
    assert find_regressions(current, baseline) == []


def test_multiple_modes_and_metrics_checked_independently():
    baseline = {
        "hybrid": {"recall@5": 0.50, "mrr": 0.60},
        "keyword": {"recall@5": 0.20},
    }
    current = {
        "hybrid": {"recall@5": 0.55, "mrr": 0.30},
        "keyword": {"recall@5": 0.20},
    }
    regressions = find_regressions(current, baseline, tolerance=0.02)
    assert regressions == [Regression("hybrid", "mrr", current=0.30, baseline=0.60)]


# ---------------------------------------------------------------------------
# ratchet_baseline
# ---------------------------------------------------------------------------


def test_ratchet_takes_the_higher_value_per_metric():
    baseline = {"hybrid": {"recall@5": 0.50, "mrr": 0.80}}
    current = {"hybrid": {"recall@5": 0.60, "mrr": 0.70}}
    assert ratchet_baseline(current, baseline) == {"hybrid": {"recall@5": 0.60, "mrr": 0.80}}


def test_ratchet_never_decreases_below_baseline():
    """Even a large drop in current must not lower the committed baseline."""
    baseline = {"hybrid": {"recall@5": 0.50}}
    current = {"hybrid": {"recall@5": 0.0}}
    assert ratchet_baseline(current, baseline) == {"hybrid": {"recall@5": 0.50}}


def test_ratchet_adds_new_modes_and_metrics():
    baseline: dict[str, dict[str, float]] = {}
    current = {"semantic": {"ndcg@5": 0.42}}
    assert ratchet_baseline(current, baseline) == {"semantic": {"ndcg@5": 0.42}}


def test_ratchet_is_idempotent():
    baseline = {"hybrid": {"recall@5": 0.50}}
    current = {"hybrid": {"recall@5": 0.50}}
    assert ratchet_baseline(current, baseline) == baseline


# ---------------------------------------------------------------------------
# format_regressions
# ---------------------------------------------------------------------------


def test_format_regressions_empty_is_a_pass_message():
    message = format_regressions([])
    assert "no regressions" in message.lower()


def test_format_regressions_lists_each_one():
    regressions = [
        Regression("hybrid", "recall@5", current=0.40, baseline=0.50),
        Regression("keyword", "mrr", current=0.10, baseline=0.30),
    ]
    message = format_regressions(regressions)
    assert "hybrid.recall@5" in message
    assert "keyword.mrr" in message
    assert "0.40" in message
    assert "0.50" in message
