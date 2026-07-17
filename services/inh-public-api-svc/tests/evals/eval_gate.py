"""Baseline-comparison CLI for the retrieval-eval gate (#37 -> hard gate).

Compares a retrieval-eval run's metrics (``eval-report.json``, written by
``test_compose_retrieval_regression.py``) against the committed governance
baseline (``corpus/retrieval_baseline.json``) and fails when any per-mode
metric regresses beyond a small tolerance. Previously the baseline diff was
print-only (reporting, not a gate); this makes "beats baseline" an enforced
CI contract instead of a number a human has to notice.

The comparison/ratchet functions are pure and dependency-free (stdlib only,
matching ``ranking_metrics.py``'s convention) so they are unit-tested offline
in ``test_eval_gate.py`` and also imported directly by
``test_compose_retrieval_regression.py`` for the live-stack hard-gate assertion.

The CLI is what CI actually invokes end to end::

    # Fail (exit 1) if the just-produced report regressed vs the committed
    # baseline; used as a standalone check step.
    uv run python tests/evals/eval_gate.py check \\
        --report eval-report.json --baseline tests/evals/corpus/retrieval_baseline.json

    # Ratchet the committed baseline up to the higher of (current, baseline)
    # per mode/metric; used only after a green gate on `main` (#37/#45 policy:
    # the baseline only ever moves up, never down).
    uv run python tests/evals/eval_gate.py ratchet \\
        --report eval-report.json --baseline tests/evals/corpus/retrieval_baseline.json \\
        --out tests/evals/corpus/retrieval_baseline.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

MetricsByMode = dict[str, dict[str, float]]

DEFAULT_TOLERANCE = 0.02


def load_metrics(path: Path) -> MetricsByMode:
    """Parse a per-mode metrics JSON file.

    Drops documentation keys (anything starting with ``_``, e.g. ``_comment``)
    and any non-dict values. Returns ``{}`` if the file is missing or not valid
    JSON, mirroring the existing best-effort baseline loader in
    ``test_compose_retrieval_regression.py``.
    """
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict)}


@dataclass(frozen=True)
class Regression:
    """A single (mode, metric) that dropped beyond tolerance vs. the baseline."""

    mode: str
    metric: str
    current: float
    baseline: float

    @property
    def delta(self) -> float:
        return self.current - self.baseline


def find_regressions(
    current: MetricsByMode,
    baseline: MetricsByMode,
    tolerance: float = DEFAULT_TOLERANCE,
) -> list[Regression]:
    """Return every (mode, metric) the baseline tracks that regressed beyond ``tolerance``.

    Only metrics present in the *baseline* are checked: a metric the baseline
    doesn't track yet (e.g. a newly added mode) has nothing to regress against.
    A metric the baseline tracks but the current run didn't produce is treated
    as ``0.0`` -- a broken or incomplete eval run must not silently pass the
    gate by omission.
    """
    regressions = []
    for mode, metrics in baseline.items():
        current_mode = current.get(mode, {})
        for metric, baseline_value in metrics.items():
            current_value = current_mode.get(metric, 0.0)
            if current_value < baseline_value - tolerance:
                regressions.append(
                    Regression(mode, metric, current=current_value, baseline=baseline_value)
                )
    return regressions


def ratchet_baseline(current: MetricsByMode, baseline: MetricsByMode) -> MetricsByMode:
    """Return a new baseline that never decreases: ``max(current, baseline)`` per metric.

    Union of modes/metrics from both sides, so a new mode or metric in
    ``current`` is adopted and one that disappeared from ``current`` keeps its
    prior baseline value untouched.
    """
    updated: MetricsByMode = {}
    for mode in sorted(set(current) | set(baseline)):
        current_mode = current.get(mode, {})
        baseline_mode = baseline.get(mode, {})
        updated[mode] = {
            metric: max(current_mode.get(metric, 0.0), baseline_mode.get(metric, 0.0))
            for metric in sorted(set(current_mode) | set(baseline_mode))
        }
    return updated


def format_regressions(regressions: list[Regression]) -> str:
    """Human-readable summary for CI logs / step summaries."""
    if not regressions:
        return "[eval-gate] no regressions vs baseline."
    lines = ["[eval-gate] regressions vs baseline:"]
    for reg in sorted(regressions, key=lambda r: (r.mode, r.metric)):
        lines.append(
            f"  {reg.mode}.{reg.metric}: {reg.current:.3f} "
            f"(baseline {reg.baseline:.3f}, {reg.delta:+.3f})"
        )
    return "\n".join(lines)


def _cmd_check(args: argparse.Namespace) -> int:
    current = load_metrics(Path(args.report))
    baseline = load_metrics(Path(args.baseline))
    regressions = find_regressions(current, baseline, tolerance=args.tolerance)
    print(format_regressions(regressions))
    return 1 if regressions else 0


def _cmd_ratchet(args: argparse.Namespace) -> int:
    current = load_metrics(Path(args.report))
    baseline = load_metrics(Path(args.baseline))
    updated = ratchet_baseline(current, baseline)
    out_path = Path(args.out)
    out_path.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n")
    changed = updated != baseline
    print(f"[eval-gate] wrote ratcheted baseline to {out_path} (changed={changed})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Fail if the report regressed vs baseline.")
    check.add_argument("--report", required=True, help="Path to the current eval-report.json.")
    check.add_argument("--baseline", required=True, help="Path to the committed baseline JSON.")
    check.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    check.set_defaults(func=_cmd_check)

    ratchet = subparsers.add_parser(
        "ratchet", help="Write a baseline that never decreases below the current one."
    )
    ratchet.add_argument("--report", required=True, help="Path to the current eval-report.json.")
    ratchet.add_argument("--baseline", required=True, help="Path to the committed baseline JSON.")
    ratchet.add_argument("--out", required=True, help="Path to write the updated baseline JSON.")
    ratchet.set_defaults(func=_cmd_ratchet)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
