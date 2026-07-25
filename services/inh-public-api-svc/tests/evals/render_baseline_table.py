"""Render the committed retrieval-eval baseline into README.md as a Markdown table.

The baseline (``corpus/retrieval_baseline.json``) is the enforced quality floor
for retrieval — but until now it lived only as a JSON file nobody reads, and the
README advertised the eval capability with no numbers attached. The trend log
(``corpus/retrieval_history.jsonl``) had the same problem: durable, but only
"queryable" by hand.

This module renders the *baseline* (not the history) into a marker-delimited
block in README.md, and the ``eval-baseline-ratchet`` job in
``.github/workflows/integration.yml`` regenerates that block in the same commit
it ratchets the baseline. Rendering the baseline rather than the history is
deliberate on two counts:

* **Churn.** A history line is appended on *every* main-branch run (each carries
  a fresh timestamp, so it is never a no-op). Rendering it would rewrite
  README.md on every run. The baseline only changes when a metric actually
  improves, so a baseline-derived block keeps README.md diffs meaningful.
* **Honesty.** The baseline is a per-metric ``max()`` accumulated across runs
  (see ``eval_gate.ratchet_baseline``), so its values may come from different
  commits. The block therefore reports it as a *floor* and deliberately does not
  stamp it with a single commit SHA, which would misattribute the numbers.

The comparison/render functions are pure and stdlib-only, matching
``eval_gate.py``'s convention, so they unit-test offline in
``test_render_baseline_table.py``.

CLI (what CI actually invokes)::

    uv run python tests/evals/render_baseline_table.py \\
        --baseline tests/evals/corpus/retrieval_baseline.json \\
        --readme ../../README.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tests.evals.eval_gate import MetricsByMode, load_metrics

#: README.md delimiters for the generated block. Everything between them is
#: overwritten on each render; everything outside is preserved untouched.
MARKER_START = "<!-- retrieval-baseline:start -->"
MARKER_END = "<!-- retrieval-baseline:end -->"

#: (baseline key, column header). Fixed order so the table is stable regardless
#: of JSON key ordering; a metric absent from the baseline renders as an em dash.
METRIC_COLUMNS: tuple[tuple[str, str], ...] = (
    ("recall@5", "Recall@5"),
    ("mrr", "MRR"),
    ("ndcg@5", "nDCG@5"),
)

#: Rendered in place of a metric the baseline does not track. Deliberately not
#: "0.000", which would read as "measured, and terrible" rather than "not
#: measured" -- the same distinction find_regressions() draws when it treats a
#: missing metric as a failure rather than a pass.
NOT_TRACKED = "—"

_EMPTY_NOTE = (
    "_No retrieval baseline recorded yet — the eval gate has not completed a "
    "green run on `main`._"
)


class MissingMarkersError(ValueError):
    """Raised when README.md lacks a well-formed generated-block marker pair.

    Raised rather than silently returning the text unchanged: a no-op here would
    leave README.md frozen at stale numbers while CI reported success, which is
    the same "looks wired, never actually moves" failure the retrieval-eval
    ratchet itself was built to eliminate (#158).
    """


def render_table(metrics: MetricsByMode) -> str:
    """Render per-mode baseline metrics as a Markdown table.

    Modes are sorted alphabetically so the rendered table (and therefore the
    README diff) does not change just because JSON key order did.
    """
    if not metrics:
        return _EMPTY_NOTE

    header = "| Mode | " + " | ".join(label for _, label in METRIC_COLUMNS) + " |"
    separator = "| --- |" + " --- |" * len(METRIC_COLUMNS)

    rows = []
    for mode in sorted(metrics):
        cells = []
        for key, _ in METRIC_COLUMNS:
            value = metrics[mode].get(key)
            cells.append(NOT_TRACKED if value is None else f"{value:.3f}")
        rows.append(f"| {mode.capitalize()} | " + " | ".join(cells) + " |")

    return "\n".join([header, separator, *rows])


def render_block(metrics: MetricsByMode) -> str:
    """Render the full generated block body (provenance note + table).

    Returns the body only — ``replace_block`` owns the markers themselves, so
    the two concerns stay separable and independently testable.
    """
    provenance = (
        "<!-- Generated from "
        "services/inh-public-api-svc/tests/evals/corpus/retrieval_baseline.json "
        "by tests/evals/render_baseline_table.py — do not edit by hand. "
        "The eval-baseline-ratchet job regenerates it whenever the baseline "
        "moves. -->"
    )
    return f"{provenance}\n\n{render_table(metrics)}"


def replace_block(text: str, body: str) -> str:
    """Replace the marker-delimited block in ``text`` with ``body``.

    Idempotent: re-rendering an unchanged baseline reproduces byte-identical
    output, so the ratchet job's ``git diff --cached --quiet`` check stays
    meaningful and README.md is only committed when the numbers actually moved.
    """
    start = text.find(MARKER_START)
    end = text.find(MARKER_END)
    if start == -1 or end == -1 or end < start:
        raise MissingMarkersError(
            f"README is missing a well-formed {MARKER_START} ... {MARKER_END} pair; "
            "cannot render the retrieval baseline table."
        )
    return text[: start + len(MARKER_START)] + f"\n{body}\n" + text[end:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="Path to retrieval_baseline.json.")
    parser.add_argument("--readme", required=True, help="Path to the README.md to update.")
    args = parser.parse_args(argv)

    baseline_path = Path(args.baseline)
    if not baseline_path.exists():
        # Distinct from an empty baseline: a *missing* file means broken wiring,
        # and rendering the "no baseline yet" note would quietly overwrite good
        # numbers with worse-looking ones.
        print(f"[baseline-table] baseline not found: {baseline_path}", file=sys.stderr)
        return 1

    readme_path = Path(args.readme)
    try:
        updated = replace_block(readme_path.read_text(), render_block(load_metrics(baseline_path)))
    except MissingMarkersError as exc:
        print(f"[baseline-table] {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"[baseline-table] could not read {readme_path}: {exc}", file=sys.stderr)
        return 1

    readme_path.write_text(updated)
    print(f"[baseline-table] rendered retrieval baseline into {readme_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
