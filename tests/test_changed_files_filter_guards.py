"""Repo-level guard: the changed-files path filter treats an empty diff as software.

`.github/workflows/{ci,e2e-smoke}.yml` decide whether to run their expensive
merge-gate jobs by grepping `changed.txt` -- the `git diff --name-only` of the
PR against its base -- for any path outside a docs/non-software allowlist.

`grep -vq` exits 1 when nothing matches, and a zero-line file also matches
nothing, so an EMPTY `changed.txt` produced the same exit as a genuine
docs-only PR: `software=false`, every dependent job skipped, and -- since
GitHub counts a skipped job as a passing required check -- all three
PR-blocking checks green. Reproduced in #302 (run 32231695208), fixed in #303
by testing `[ ! -s changed.txt ]` first so an empty diff falls through to
`software=true` and runs the full suite.

Fail-open, not fail-loud, on purpose: a PR whose net diff is legitimately
empty must stay mergeable, and running the suite on it costs minutes rather
than passing a gate on a claim about files that do not exist.

These tests pin the YAML text rather than executing the workflow (this repo
has no local GitHub Actions runner), matching the pattern in
`tests/test_e2e_smoke_workflow_guards.py` and its siblings. They assert only
that the empty-file check is present and precedes the grep -- deliberately not
that any particular alternative is absent, so a future rewrite is free to
reach the same property another way.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Both workflows carry a byte-identical filter; ci.yml's comment says it is
# "kept in sync with the identical filter in e2e-smoke.yml", so a guard that
# covered only one would let them drift.
WORKFLOWS = (".github/workflows/ci.yml", ".github/workflows/e2e-smoke.yml")

EMPTY_CHECK = "[ ! -s changed.txt ]"
GREP = "grep -vqE"


def _text(workflow: str) -> str:
    return (REPO_ROOT / workflow).read_text()


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_empty_changed_files_counts_as_software_affecting(workflow: str) -> None:
    text = _text(workflow)
    assert EMPTY_CHECK in text, (
        f"{workflow}: the path filter must test `{EMPTY_CHECK}` -- without it an "
        "empty changed.txt is indistinguishable from a docs-only PR and every "
        "required check reports skipped-hence-passing (#303)"
    )


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_empty_check_short_circuits_before_the_grep(workflow: str) -> None:
    """`[ ! -s ... ] || grep ...` -- order matters, and so does the `||`.

    Behind the grep (or joined with `&&`) the check cannot rescue the empty
    case, which is the whole bug.
    """
    text = _text(workflow)
    empty_at = text.index(EMPTY_CHECK)
    grep_at = text.index(GREP, empty_at - 200 if empty_at > 200 else 0)
    assert empty_at < grep_at, (
        f"{workflow}: `{EMPTY_CHECK}` must come before `{GREP}` in the filter (#303)"
    )
    between = text[empty_at + len(EMPTY_CHECK) : grep_at]
    assert "||" in between, (
        f"{workflow}: join the empty check to the grep with `||` so an empty "
        f"changed.txt short-circuits to software=true (#303); found {between!r}"
    )


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_empty_diff_selects_the_software_true_branch(workflow: str) -> None:
    """The rescued branch must be the one that RUNS the suite, not the one that skips."""
    text = _text(workflow)
    branch = text[text.index(EMPTY_CHECK) :]
    true_at = branch.index('echo "software=true"')
    false_at = branch.index('echo "software=false"')
    assert true_at < false_at, (
        f"{workflow}: the empty-diff check must fall through to software=true "
        "(fail open into running the suite), not software=false (#303)"
    )
