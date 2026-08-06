"""Offline unit tests for the README baseline-table renderer (``render_baseline_table.py``).

No services required; runs in the default ``-m 'not compose'`` suite alongside
``test_eval_gate.py``. These pin the two properties the CI wiring depends on:
the rendered block is a pure function of the committed baseline, and rewriting
an already-rendered README is a no-op (idempotent) so the ratchet job only
touches README.md when the baseline actually moved.
"""

from __future__ import annotations

import json

import pytest

from tests.evals.render_baseline_table import (
    MARKER_END,
    MARKER_START,
    MissingMarkersError,
    main,
    render_block,
    render_table,
    replace_block,
)

pytestmark = pytest.mark.retrieval_eval


# ---------------------------------------------------------------------------
# render_table
# ---------------------------------------------------------------------------


def test_render_table_emits_one_row_per_mode_in_sorted_order():
    table = render_table(
        {
            "semantic": {"recall@5": 0.5, "mrr": 0.25, "ndcg@5": 0.125},
            "hybrid": {"recall@5": 1.0, "mrr": 0.75, "ndcg@5": 0.5},
        }
    )
    lines = table.splitlines()
    # Header + separator + one row per mode, modes alphabetical so the table
    # ordering is stable across runs (dict order must not leak into the diff).
    assert lines[0] == "| Mode | Recall@5 | MRR | nDCG@5 |"
    assert lines[1] == "| --- | --- | --- | --- |"
    assert lines[2] == "| Hybrid | 1.000 | 0.750 | 0.500 |"
    assert lines[3] == "| Semantic | 0.500 | 0.250 | 0.125 |"
    assert len(lines) == 4


def test_render_table_marks_metrics_the_baseline_does_not_track():
    # A mode missing a metric renders an em dash rather than a fabricated 0.000,
    # which would read as "measured and terrible" instead of "not measured".
    table = render_table({"keyword": {"recall@5": 0.8}})
    assert table.splitlines()[2] == "| Keyword | 0.800 | — | — |"


def test_render_table_handles_an_empty_baseline():
    # A zeroed/absent baseline is exactly the failure mode #139 existed to make
    # visible, so it must render an explicit note, never a bare empty table.
    assert "No retrieval baseline" in render_table({})


# ---------------------------------------------------------------------------
# replace_block
# ---------------------------------------------------------------------------


def _readme(body: str) -> str:
    return f"# Title\n\nintro\n\n{MARKER_START}\n{body}\n{MARKER_END}\n\ntrailing\n"


def test_replace_block_preserves_text_outside_the_markers():
    updated = replace_block(_readme("old content"), "new content")
    assert "# Title" in updated
    assert "intro" in updated
    assert "trailing" in updated
    assert "old content" not in updated
    assert "new content" in updated


def test_replace_block_is_idempotent():
    # The ratchet job commits README.md alongside the baseline; if rendering an
    # unchanged baseline produced a different byte sequence each run, every run
    # would dirty README.md and (via the merge to main) risk re-triggering CI.
    once = replace_block(_readme("old"), "generated")
    twice = replace_block(once, "generated")
    assert once == twice


def test_replace_block_keeps_the_markers_themselves():
    updated = replace_block(_readme("old"), "generated")
    assert updated.count(MARKER_START) == 1
    assert updated.count(MARKER_END) == 1


@pytest.mark.parametrize(
    "text",
    [
        "no markers at all",
        f"{MARKER_START}\nunclosed\n",
        f"{MARKER_END}\nend before start\n{MARKER_START}\n",
    ],
)
def test_replace_block_rejects_malformed_markers(text):
    # Fail loudly rather than silently leaving README.md un-updated -- a silent
    # no-op here reproduces the "gate looks wired but never moves" class of bug
    # this whole eval pipeline exists to prevent.
    with pytest.raises(MissingMarkersError):
        replace_block(text, "generated")


# ---------------------------------------------------------------------------
# render_block
# ---------------------------------------------------------------------------


def test_render_block_is_wrapped_in_a_do_not_edit_notice():
    block = render_block({"hybrid": {"recall@5": 1.0, "mrr": 1.0, "ndcg@5": 1.0}})
    assert "generated" in block.lower()
    # The block body must not embed the markers; replace_block owns those.
    assert MARKER_START not in block
    assert MARKER_END not in block


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_main_rewrites_the_readme_block_from_the_baseline(tmp_path):
    baseline = tmp_path / "retrieval_baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "_comment": "documentation key, not a mode",
                "hybrid": {"recall@5": 0.75, "mrr": 0.5, "ndcg@5": 0.25},
            }
        )
    )
    readme = tmp_path / "README.md"
    readme.write_text(_readme("stale table"))

    assert main(["--baseline", str(baseline), "--readme", str(readme)]) == 0

    updated = readme.read_text()
    assert "| Hybrid | 0.750 | 0.500 | 0.250 |" in updated
    assert "stale table" not in updated
    # `_comment` is a documentation key, not a retrieval mode -- it must not
    # become a table row (load_metrics in eval_gate.py already drops it; this
    # pins that the renderer relies on that and does not re-add it).
    assert "_comment" not in updated


def test_main_is_idempotent_across_runs(tmp_path):
    baseline = tmp_path / "retrieval_baseline.json"
    baseline.write_text(json.dumps({"hybrid": {"recall@5": 0.75, "mrr": 0.5, "ndcg@5": 0.25}}))
    readme = tmp_path / "README.md"
    readme.write_text(_readme("stale"))

    main(["--baseline", str(baseline), "--readme", str(readme)])
    first = readme.read_text()
    main(["--baseline", str(baseline), "--readme", str(readme)])
    assert readme.read_text() == first


def test_main_fails_when_the_readme_has_no_markers(tmp_path):
    baseline = tmp_path / "retrieval_baseline.json"
    baseline.write_text(json.dumps({"hybrid": {"recall@5": 1.0}}))
    readme = tmp_path / "README.md"
    readme.write_text("# Title\n\nno markers here\n")

    # Non-zero exit so the CI step fails loudly instead of committing a README
    # that silently never updates again.
    assert main(["--baseline", str(baseline), "--readme", str(readme)]) == 1
