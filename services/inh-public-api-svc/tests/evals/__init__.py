"""Retrieval-quality evaluation suite (M4: #33 golden corpus, #35 ranking regression).

Contains:
- ``metrics``: pure, dependency-free ranking metrics (recall@k, MRR, nDCG@k).
- ``corpus/qrels.jsonl``: golden relevance judgments over the shared sample
  fixtures in ``docs/examples/sample-documents/``.
- offline tests that validate the metrics and the corpus, plus a compose-marked
  regression test that runs the metrics against the live stack.
"""
