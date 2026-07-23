# ADR 0004 — Per-Document Result Diversification

- **Status:** Accepted (gated, off by default)
- **Date:** 2026-07-23
- **Deciders:** maintainers
- **Related:** [ADR 0003](0003-traffic-mined-retrieval-evals.md), #146, #47

## Context

A search request's ranked results come from over-fetching and truncating (or
just truncating) a score-sorted candidate list per `docs/advanced-indexes.md`
and `src/services/search.py`. A document that chunks into many pieces — a long
reference doc, a deep-dive, a spec — can occupy every slot in a small `limit`
(the common case: the default page size is small) purely because its chunks
all score well against the query, even when a shorter, differently-worded
document is also genuinely relevant and answers the query just as well or
better for some callers.

This is not hypothetical. Added to the golden corpus (`tests/evals/corpus/`)
as `q14` / category `multi_doc_crowding`: `rate-limiting-deep-dive.txt` (5
chunks, all on-topic for "how does Inherent enforce per-API-key rate limits")
and `rate-limit-quick-reference.txt` (1 chunk, differently worded, also
on-topic and judged equally relevant). Measured locally against a live Compose
stack with the production-default settings (`enable_diversification=False`):
the naive top-5 for every mode (semantic/hybrid/keyword) returns **only**
`rate-limiting-deep-dive.txt` — the quick-reference document is not fetched at
all, let alone ranked, because Weaviate returns exactly `limit` rows and every
one of them belongs to the longer document. `recall@5` for that query sits at
`0.5` (1 of 2 relevant documents retrievable) regardless of mode.

## Decision

Add per-document diversification (`SearchService._diversify_by_document`,
`src/services/search.py`) as an **opt-in, off-by-default** post-filter:

1. When `enable_diversification` is on, widen the Weaviate fetch to
   `min(100, limit * diversification_over_fetch_multiplier)` (default
   multiplier `5`) instead of fetching exactly `limit` rows — there must be
   more candidates than the page size for diversification to have anything to
   diversify across.
2. Round-robin one result per `document_id`, in document order (each
   document's own best score, since candidates arrive score-sorted from
   Weaviate) and in within-document score order, until `limit` is reached or
   every candidate is exhausted.
3. When the flag is off (the default), behavior is byte-for-byte identical to
   before this ADR: `results[:limit]`, no wider fetch, no round-robin.

### Why gated, not on by default

This is not scaffolding like the #47 advanced methods (cross-encoder rerank,
GraphRAG, hierarchical index) — it is fully implemented, deterministic, and
requires no new model or index. It is still gated behind the same eval-gate
policy (`enable_diversification`, default `False`; requires a documented eval
improvement + maintainer approval before defaulting on) because:

- It **changes ranking order** for every multi-chunk-per-document query, not
  just crowded ones — a caller depending on today's exact ranking for a
  well-served query could see its position shift even though nothing about
  that query's own relevance changed.
- The compose retrieval-eval gate (`test_compose_retrieval_regression.py`,
  ADR 0003's CI suite) needs to measure it against the full golden corpus over
  time before it earns production-default status, same bar as any #47 method.
- The over-fetch itself has a real cost (up to 5x the Weaviate query size)
  that should be paid only where the caller has opted in, not on every
  request by default.

### Measured evidence (local Compose run, 2026-07-23)

Flag off vs. flag on, `multi_doc_crowding` category specifically:

| Mode | recall@5 (off → on) | nDCG@5 (off → on) |
|---|---|---|
| hybrid | 0.5 → 1.0 | 0.613 → 0.920 |
| keyword | 0.5 → 1.0 | 0.613 → 0.877 |
| semantic | 0.5 → 1.0 | 0.613 → 0.920 |

Pooled per-mode metrics across the **whole** corpus (not just the new query),
flag off vs. on — every metric flat or improved, none regressed:

| Mode | recall@5 | nDCG@5 | MRR |
|---|---|---|---|
| hybrid | 0.846 → 0.885 | 0.720 → 0.744 | 0.795 → 0.795 |
| keyword | 0.808 → 0.885 | 0.714 → 0.744 | 0.821 → 0.821 |
| semantic | 0.846 → 0.962 | 0.681 → 0.734 | 0.695 → 0.710 |

This is exactly the shape of evidence the eval-gate policy asks for — a
documented improvement with no regression — but it is one measurement on one
small golden corpus, not the sustained CI history the policy expects before a
flag defaults on. The committed `retrieval_baseline.json` reflects the
flag-**off** numbers (production default); the flag-on numbers above are
recorded here and in the CHANGELOG, not folded into the gated baseline.

## Boundary: what this is not

- **Not a ranking model change.** No score is recomputed; diversification only
  reorders which already-scored candidates survive truncation.
- **Not a fix for single-document corpora.** With one document in a workspace,
  or a query where only one document is ever relevant, diversification cannot
  help and does not change behavior (a single bucket round-robins with itself,
  equivalent to a plain truncate).
- **Not on by default.** See "why gated" above; flipping the default requires
  the same eval-gate + maintainer approval process as any #47 method.

## Consequences

- Callers with document collections containing long, multi-chunk documents
  alongside shorter authoritative ones (FAQs, quick-reference sheets, policy
  summaries) gain an opt-in way to avoid one document silently monopolizing
  the result page.
- `docs/advanced-indexes.md` and `settings.py` document
  `diversification_over_fetch_multiplier` as the tunable controlling the
  fetch/diversity tradeoff; a higher multiplier surfaces more distinct
  documents at the cost of a larger per-request Weaviate fetch.
- The golden corpus (`tests/evals/corpus/qrels.jsonl`) now carries a
  permanent `multi_doc_crowding` category (`q14`) so future changes to
  chunking, scoring, or diversification itself are measured against this
  scenario going forward, not just the categories ADR-0003's original corpus
  covered.
- Turning this on by default in a future release is a ranking-order change
  for existing callers and should ship as an explicit, changelogged decision
  (with fresh CI-measured evidence, not just this single local run) — not a
  silent default flip.
