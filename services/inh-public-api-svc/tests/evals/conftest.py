"""Fixtures for the retrieval-quality eval suite.

The eval tests are split into two groups:

- *Offline* tests (``metrics`` unit tests and the ``retrieval_eval`` corpus /
  harness-wiring checks) run with no external services. They must pass in the
  default ``-m 'not compose'`` run.
- A *compose* regression test (``retrieval_eval`` + ``compose``) talks to the
  live local stack and is deselected by default.

A no-op ``cleanup_test_data`` autouse fixture is provided so these tests never
attempt any real teardown against shared infrastructure when run offline,
mirroring the integration-test convention of isolating side effects.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# repo root: tests/evals/conftest.py -> parents[4]
# (evals=0, tests=1, inh-public-api-svc=2, services=3, repo-root=4)
REPO_ROOT = Path(__file__).resolve().parents[4]
SAMPLE_DIR = REPO_ROOT / "docs" / "examples" / "sample-documents"
QRELS_PATH = Path(__file__).resolve().parent / "corpus" / "qrels.jsonl"


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """No-op override so the eval suite runs offline without real teardown.

    The compose regression test uploads fixtures to a throwaway local stack; we
    deliberately do not delete shared data here. This autouse fixture exists to
    mirror integration-test patterns and to make the offline intent explicit:
    nothing in this suite mutates persistent infrastructure that needs cleanup.
    """
    yield


def _load_qrels() -> list[dict]:
    """Parse ``corpus/qrels.jsonl`` into a list of judgment dicts."""
    judgments: list[dict] = []
    with QRELS_PATH.open(encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                judgments.append(json.loads(raw))
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                raise AssertionError(
                    f"qrels.jsonl line {line_no} is not valid JSON: {exc}"
                ) from exc
    return judgments


@pytest.fixture(scope="session")
def golden_corpus() -> dict:
    """Load the golden corpus from ``corpus/qrels.jsonl``.

    Returns a dict with:
        - ``judgments``: list of raw qrel dicts (one per line).
        - ``queries``: ordered ``{query_id: query_text}`` mapping.
        - ``relevance``: ``{query_id: {document_id: relevance}}`` grades.
        - ``relevant``: ``{query_id: set(document_id)}`` of positively-judged ids
          (relevance > 0), convenient for binary metrics.
        - ``category``: ``{query_id: category}`` (defaults to ``"general"`` when
          a judgment omits the optional ``category`` field). Categories cover
          the query archetypes production RAG evals should exercise beyond
          generic doc lookup: ``exact_id`` (identifiers/error codes),
          ``stale_version`` (superseded vs. current docs), ``paraphrase``
          (semantically-equivalent, differently-worded query), ``abstention``
          (no relevant document exists in the corpus -- the correct
          retrieval-layer signal is zero recall/MRR/nDCG, not a fabricated
          match), and ``multi_doc_crowding`` (2+ genuinely relevant documents
          where one has many more chunks than the other, so a naive
          score-sorted top-k can crowd the shorter document out entirely --
          the scenario per-document diversification, #146, exists to fix).
          Permission/tenancy boundaries are deliberately NOT a category here
          -- that's owned by the ``security`` marker suite (auth/tenancy
          isolation), not the ranking-quality corpus.
        - ``sample_dir``: path to the shared sample-document fixtures.
    """
    judgments = _load_qrels()

    queries: dict[str, str] = {}
    relevance: dict[str, dict[str, int]] = {}
    relevant: dict[str, set[str]] = {}
    category: dict[str, str] = {}

    for j in judgments:
        qid = j["query_id"]
        queries.setdefault(qid, j["query"])
        category.setdefault(qid, j.get("category", "general"))
        rel = int(j["relevance"])
        relevance.setdefault(qid, {})[j["document_id"]] = rel
        if rel > 0:
            relevant.setdefault(qid, set()).add(j["document_id"])

    return {
        "judgments": judgments,
        "queries": queries,
        "relevance": relevance,
        "relevant": relevant,
        "category": category,
        "sample_dir": SAMPLE_DIR,
    }
