"""JSON benchmark report helpers, shared by ingestion benchmark tests (#36, REQ-EVL-3).

Kept in its own importable (non-test) module, mirroring the public-api
service's ``run_search_benchmark.py`` split between pure helpers and the
pytest file that exercises them against a live stack -- so the merge/write
logic can be unit-tested offline without a running Compose stack.

``git_sha()``/``write_benchmark_report()`` are duplicated near-verbatim in
``services/inh-public-api-svc/tests/benchmark/run_search_benchmark.py``
(separate Python packages, no shared dependency between them). If the report
shape changes here (new fields, atomic write, etc.), make the matching edit
there too -- there is no test that would catch the two drifting apart.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def git_sha() -> str:
    """Return the commit SHA this benchmark ran against.

    Prefers ``GITHUB_SHA`` (set by Actions, cheap and exact) and falls back to
    ``git rev-parse HEAD`` for local runs; ``"unknown"`` if neither works.
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

    Merges into any existing file rather than overwriting it, so multiple
    benchmarks in the same CI run can each contribute a top-level key to one
    shared artifact. A corrupt or missing existing file is treated as an
    empty report rather than failing the benchmark on its own reporting step.
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
