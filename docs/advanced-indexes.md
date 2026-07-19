# Advanced retrieval indexes (eval-gated) — #47

> **Status: SCAFFOLDING ONLY.** All three methods below are **EXPERIMENTAL,
> OFF BY DEFAULT, and NOT IMPLEMENTED.** The flags exist and the dispatch point
> is wired, but no graph / rerank / hierarchy logic has been added. Enabling a
> flag today only emits a "enabled but not implemented (scaffolding)" log line
> and changes nothing about the results.

The `inh-public-api-svc` search service ships three **standard** retrieval modes
(`semantic`, `hybrid`, `keyword` — see `SearchRequest.search_mode`). This
document describes three **advanced** retrieval methods that are planned on top
of those modes, why they are off by default, and the policy that governs when —
if ever — one of them may be turned on by default.

## The three advanced methods

| Method | Settings flag | What it will do (planned) |
| --- | --- | --- |
| **Cross-encoder rerank** | `enable_reranker` | Re-score the assembled top-k results with a cross-encoder for sharper ordering. |
| **GraphRAG index** | `enable_graphrag_index` | Retrieve over a GraphRAG-style entity/relationship graph index, not just chunk vectors/BM25. |
| **Hierarchy index** | `enable_hierarchy_index` | Retrieve over a hierarchical (parent/child / summary) index for better long-document recall. |

All three flags live in `src/config/settings.py` and **default to `False`**.

## Why off by default

The production default is the **measured hybrid baseline** established in #45 and
exercised by the **M4 retrieval evals** (`services/inh-public-api-svc/tests/evals/`,
metrics: recall@k, MRR, nDCG@k). Advanced methods add cost and complexity and can
*regress* quality if added blindly, so none of them ships on until it has *proven*
it helps on that baseline.

As of #139, that baseline is a **hard, ratcheting CI gate**
(`corpus/retrieval_baseline.json`, checked by `tests/evals/eval_gate.py`), not
just a documented number — see
[docs/testing.md § Retrieval-eval gate](testing.md#retrieval-eval-gate-baseline-ratchet-and-trend-history-139).

## Eval-gate policy

**No advanced method may be enabled by default without BOTH:**

1. **A documented eval improvement vs the hybrid baseline (#45).** The method
   must show a measured improvement on the M4 retrieval evals
   (`tests/evals/`) relative to the current hybrid baseline — improvement
   documented (numbers + which corpus/queries), not asserted.
2. **Maintainer approval.** A maintainer must sign off on the result and the
   default-on change (see `docs/maintainers/`).

Until both are met, the flag stays `False` by default and may only be turned on
explicitly in dev for experimentation. The defaults are themselves asserted by
`tests/evals/test_advanced_index_gate.py` so the gate cannot be silently
defeated.

### Per-method eval target (PLACEHOLDER thresholds)

These are **placeholder** acceptance thresholds to be finalized with real
measurements; each is "must not regress, and must clear the bar below" vs the
hybrid baseline on the M4 corpus:

| Method | Placeholder target (vs hybrid baseline #45) |
| --- | --- |
| Cross-encoder rerank | nDCG@10 improvement >= +0.03 (no recall@10 regression) |
| GraphRAG index | recall@10 improvement >= +0.05 (no nDCG@10 regression) |
| Hierarchy index | recall@10 improvement >= +0.05 on long-document queries (no nDCG@10 regression) |

## How to enable in dev (experimentation only)

Set the corresponding environment variable before starting the service, e.g.:

```bash
export ENABLE_RERANKER=true
export ENABLE_GRAPHRAG_INDEX=true
export ENABLE_HIERARCHY_INDEX=true
```

(or the equivalent keys in your `.env`). With a flag on, the service logs
`advanced method '<name>' enabled but not implemented (scaffolding)` and returns
results **unchanged** — this is expected until the method is implemented and
clears the eval gate above.

## Where it is wired

- Flags: `services/inh-public-api-svc/src/config/settings.py`
- No-op dispatch: `SearchService._apply_advanced_methods(results, request)` in
  `services/inh-public-api-svc/src/services/search.py`, called after results are
  assembled in `SearchService.search()`.
- Gate test: `services/inh-public-api-svc/tests/evals/test_advanced_index_gate.py`
