# Org-Readiness Requirements

**Status:** Draft · **Owner:** maintainers · **Last updated:** 2026-06-20

## 1. Goal

Make Inherent ready to drop into an organization that has **no existing context
stack**. The org should be able to self-host Inherent and get a
**permission-aware vector memory layer that their agents can query continuously**
while answering — with retrieval that is durable, citeable, fresh, and safe to
expose to autonomous agents.

In one sentence: *turn the current RAG backend into a trustworthy agent memory
substrate an org can run and trust on day one.*

### Target user

- An SME / org with internal documents but no retrieval/RAG infrastructure.
- Operators who self-host via Docker Compose and want a one-command path to a
  working stack.
- Agent developers who connect agents to Inherent over **REST and MCP** and
  expect stable, versioned tool contracts.

### What "ready" means (definition of done for the goal)

1. A fresh checkout reaches a working upload → ingest → search loop with **one
   command** and a documented bootstrap (no private services).
2. Ingestion is **durable and observable** — no silently stranded documents,
   every document has a visible lifecycle status, failures are recoverable.
3. Retrieval is **measurable** against a baseline, **permission-safe** at the
   chunk level, **fresh-aware**, and **citeable**.
4. Agents can use Inherent through **stable, versioned MCP/REST memory tools**
   with parity between the two surfaces.
5. The memory layer is **safe against poisoned/injected documents**.
6. Quality is **gated by evals and a release acceptance matrix**, not anecdote.

## 2. How to read this document

Each requirement has an ID (`REQ-<area>-<n>`), the GitHub issues that implement
it, and the acceptance signal that closes it. This is the source-of-truth
checklist the delivery loop iterates against. Areas are ordered by dependency:
foundation first, trust/agent surface last.

Issue legend: ✅ done · 🔲 open (all are currently open).

---

## 3. Requirements by capability area

### A. Foundation & onboarding — *an org can stand it up*

| ID | Requirement | Issues | Acceptance signal |
|----|-------------|--------|-------------------|
| REQ-FND-1 | One-command local setup + readiness check | #19 | `make setup` (or equiv.) installs deps, copies env, starts Compose, waits for health, prints next steps |
| REQ-FND-2 | OSS bootstrap for workspaces and API keys | #5 | Fresh `docker compose up` can mint a local workspace + API key with read/search/write; README quickstart references it; marked dev-only |
| REQ-FND-3 | Fresh-start-safe, non-destructive migrations | #16 | Migrations are append-only/idempotent; never drop core tables on startup; migration history check exists |
| REQ-FND-4 | Single repository-level checks command | #3 | One entrypoint runs lint/format/typecheck/security/tests for both services; CONTRIBUTING points to it |

### B. Durable ingestion core — *nothing gets silently lost*

| ID | Requirement | Issues | Acceptance signal |
|----|-------------|--------|-------------------|
| REQ-ING-1 | Durable upload→ingestion handoff (outbox) | #6 | MQ publish failure cannot strand a file; status recoverable after restart; failed publishes retried/visible; tests cover storage-ok + MQ-fail |
| REQ-ING-2 | End-to-end document lifecycle status | #7 | `pending/processing/failed/processed(/deleted)` persisted and exposed via document APIs; search only returns ready docs; transition tests |
| REQ-ING-3 | Dead-letter recording + retry in real worker path | #8 | Failed workflows write `dead_letter_jobs` with full context; retry API restarts jobs; ACK/NACK semantics tested |
| REQ-ING-4 | Backpressure & concurrency controls | #18 | Configurable worker limits; ACK only after Temporal accepts; metrics for queue lag/starts/completions/failures |

### C. Content fidelity — *the right formats produce good chunks*

| ID | Requirement | Issues | Acceptance signal |
|----|-------------|--------|-------------------|
| REQ-CNT-1 | Supported file types aligned across README/upload/extraction | #9 | README, MIME allowlist, and extraction agree; XLSX either parsed+tested or rejected; unsupported types fail before upload |
| REQ-CNT-2 | PNG (image) upload support | #61 | PNG accepted and routed through a documented extraction path (e.g. OCR) or explicitly scoped |
| REQ-CNT-3 | Configurable, model-aware chunking | #10 | Chunk strategy/size/overlap from settings/request; token-aware sizing tied to embedding model; `token_count` matches tokenizer; no silent TEI truncation |

### D. Indexing correctness & scale — *the index stays consistent*

| ID | Requirement | Issues | Acceptance signal |
|----|-------------|--------|-------------------|
| REQ-IDX-1 | Idempotent reindex across PostgreSQL + Weaviate | #11 | Reprocessing with fewer chunks removes stale vectors; safe after partial failure; retries don't duplicate; tests for changed/shrunk content |
| REQ-IDX-2 | Fix duplicate-chunk flooding on re-upload | #60 | Re-uploading the same document does not flood search with duplicate chunks (closely tied to REQ-IDX-1) |
| REQ-IDX-3 | Scalable Weaviate tenancy strategy | #12 | Documented tenancy/index layout + scale limits; naming centralized in one contract; ingestion+search share it; migration notes |
| REQ-IDX-4 | Shared versioned contracts for events + index metadata | #17 | Document event/completion/index-metadata + Weaviate naming defined once and consumed by both services |

### E. Retrieval quality — *answers are relevant and provable*

| ID | Requirement | Issues | Acceptance signal |
|----|-------------|--------|-------------------|
| REQ-RET-1 | Measurable hybrid retrieval baseline | #45 | Keyword/semantic/hybrid documented with scoring/fusion/filters; query embedding reused per request; golden evals report recall@k, MRR/nDCG, latency, empty-rate |
| REQ-RET-2 | Concurrent, bounded, ranking-safe multi-workspace search | #13 | Bounded concurrent fan-out; embedding computed once; per-workspace failure policy; global top-k; tests for 0/1/many/partial-fail |
| REQ-RET-3 | Adaptive quality gates + fallback planning | #43 | Machine-readable quality verdict + reason codes; bounded fallback retries; explicit insufficient-evidence result; observable in traces |
| REQ-RET-4 | Eval-gated advanced indexes (graph/hierarchy/rerank) | #47 | All off by default behind flags; each defines target query class + eval vs baseline + cost report; no default-on without proven gain |

### F. Agent surface — *agents use it through stable tools*

| ID | Requirement | Issues | Acceptance signal |
|----|-------------|--------|-------------------|
| REQ-AGT-1 | MCP permission checks + REST/MCP search parity | #14 | MCP enforces `search`/`read` permissions; supports mode/filters/limit/min-score/context-window; shared helpers; denied-permission tests |
| REQ-AGT-2 | Memory primitives as REST + MCP tools | #40 | Versioned, documented tools: `search_memory`, `get_citations`, `verify_claim`, `explain_lineage`, `refresh_stale_source`; shared core services; contract tests; agent workflow doc |
| REQ-AGT-3 | REST + MCP contract regression tests | #30 | Schemas/permissions/response shapes/errors regression-tested so client SDKs/agents don't break |

### G. Trust & security — *safe to point autonomous agents at*

| ID | Requirement | Issues | Acceptance signal |
|----|-------------|--------|-------------------|
| REQ-TRU-1 | Chunk-level ACL + provenance enforcement | #41 | Chunks/sources carry tenant/workspace/principal scope, owner, permissions, URI, content hash, version, lineage, span; enforced pre-retrieval, in ranking, and before output; cross-tenant leakage tests incl. context-window |
| REQ-TRU-2 | Freshness-aware memory + refresh policies | #42 | Freshness fields on sources/docs/chunks; stale evidence identifiable in results; configurable policy; Temporal refresh jobs; documented stale-evidence behavior |
| REQ-TRU-3 | Claim-level citations + evidence verification | #39 | Stable evidence IDs + spans in responses; `verify_claim` judges support; weak support → structured warning; citations survive reindex; eval on golden set |
| REQ-TRU-4 | RAG poisoning + prompt-injection defenses | #44 | Source trust + suspicious-content signals at ingestion; risk metadata in results; retrieved text separated from instructions; poisoned/injection test corpus + docs threat model |
| REQ-TRU-5 | Auth/tenancy/permission regression scenarios | #32 | Every access path (REST, MCP, context expansion, Weaviate naming) tested so no workspace/user sees another's data |

### H. Evals & QA governance — *quality is gated, not anecdotal*

| ID | Requirement | Issues | Acceptance signal |
|----|-------------|--------|-------------------|
| REQ-EVL-1 | Golden corpus for retrieval quality | #33 | Maintained query→expected-evidence set across semantic/hybrid/keyword |
| REQ-EVL-2 | Extraction + chunking quality evals by file type | #34 | Fixture-backed scoring of extraction fidelity, chunk coverage/boundaries, token counts, empty/noisy output |
| REQ-EVL-3 | Search-mode ranking regression benchmarks | #35 | Per-mode ranking benchmarks catch embedding/query/filter/score regressions |
| REQ-EVL-4 | Latency + throughput benchmarks | #36 | Repeatable perf evals for ingestion + search across size/concurrency |
| REQ-EVL-5 | Eval result reporting + baseline governance | #37 | Standard compare-to-baseline reporting; intentional changes explained in PRs; resists accidental baseline updates |
| REQ-EVL-6 | Risk-based coverage thresholds for core modules | #38 | Coverage reported in CI with risk-based thresholds on ingestion/auth/storage/retrieval |
| REQ-EVL-7 | OSS release acceptance test matrix | #29 | Explicit release gate proving README claims across ingest/index/retrieve/auth/local-setup |
| REQ-EVL-8 | Compose-backed ingestion→search integration test | #15 | CI job starts real stack, bootstraps key, uploads fixture, waits, asserts `/v1/search` returns it |
| REQ-EVL-9 | Failure-injection coverage for ingestion deps | #31 | Intentional S3/Redis/Temporal/PG/Weaviate/TEI failure tests; failures visible/retryable/recoverable |

### I. Developer experience — *contributors can move*

| ID | Requirement | Issues | Acceptance signal |
|----|-------------|--------|-------------------|
| REQ-DX-1 | Root pre-commit covering both services | #20 | Root `.pre-commit-config.yaml` runs hygiene + Ruff/Black/mypy/Bandit; documented |
| REQ-DX-2 | Normalized dev dependency groups + tool versions | #21 | One documented dep-management pattern, aligned versions, CI/docs updated |
| REQ-DX-3 | Pytest markers + documented test profiles | #22 | Markers + commands for unit/integration/e2e/smoke; CI shows the split |
| REQ-DX-4 | Better CI feedback (cache, names, summaries) | #27 | Clear matrix names, uv cache, per-service step summaries, separated failure points |
| REQ-DX-5 | Issue templates for dev tasks + local setup failures | #28 | Scoped templates capturing OS/Docker/service/command/expected/actual/logs |

### J. Architecture — *the product boundary is written down*

| ID | Requirement | Issues | Acceptance signal |
|----|-------------|--------|-------------------|
| REQ-ARC-1 | Agent memory substrate ADR | #46 | ADR defining the product boundary (ingestion, permissions, provenance, freshness, retrieval, evals, audit, agent tools) and naming advanced/web-agent work as later-stage |

---

## 4. Delivery sequence (milestones)

The org-readiness goal is reached by completing milestones in order. Each
milestone is independently shippable and leaves the stack more usable.

### Milestone 0 — Define the boundary
- REQ-ARC-1 (#46)
- *Outcome:* written scope so the rest of the work stays focused.

### Milestone 1 — An org can run it (foundation)
- REQ-FND-1..4 (#19, #5, #16, #3)
- REQ-EVL-8 (#15) as the proof it works end-to-end
- *Outcome:* fresh checkout → one command → bootstrap → upload → search.

### Milestone 2 — Nothing gets lost (durable ingestion)
- REQ-ING-1..4 (#6, #7, #8, #18)
- REQ-IDX-1, REQ-IDX-2 (#11, #60) — idempotent reindex + dup-chunk fix
- REQ-EVL-9 (#31) failure injection
- *Outcome:* durable, observable, recoverable ingestion.

### Milestone 3 — Good content in (fidelity)
- REQ-CNT-1..3 (#9, #61, #10)
- REQ-IDX-3, REQ-IDX-4 (#12, #17)
- REQ-EVL-2 (#34)
- *Outcome:* supported formats produce stable, model-aware chunks at scale.

### Milestone 4 — Relevant, measurable retrieval
- REQ-RET-1, REQ-RET-2 (#45, #13)
- REQ-EVL-1, REQ-EVL-3, REQ-EVL-4 (#33, #35, #36)
- *Outcome:* a measured baseline and concurrent, ranking-safe search.

### Milestone 5 — Safe for agents (trust)
- REQ-TRU-1..5 (#41, #42, #39, #44, #32)
- REQ-RET-3 (#43) quality gates
- *Outcome:* permission-safe, fresh, citeable, poison-resistant memory.

### Milestone 6 — Agent-native surface
- REQ-AGT-1..3 (#14, #40, #30)
- *Outcome:* agents query continuously over stable, versioned MCP/REST tools.

### Milestone 7 — Quality governance + advanced retrieval
- REQ-EVL-5..7 (#37, #38, #29)
- REQ-RET-4 (#47)
- REQ-DX-1..5 (#20, #21, #22, #27, #28)
- *Outcome:* eval-gated quality bar and release acceptance matrix.

---

## 5. Cross-cutting acceptance for "organization-ready"

A release is org-ready when **all** of the following hold:

- [ ] Fresh clone → working upload/search in one documented command (M1).
- [ ] No silently stranded documents; every document has a visible status (M2).
- [ ] Reprocessing never leaves stale or duplicate search results (M2/M3).
- [ ] Retrieval has a documented baseline with golden-corpus metrics (M4).
- [ ] No workspace/user/principal can ever read another's chunks (M5).
- [ ] Responses carry citations, freshness, and trust/risk metadata (M5).
- [ ] Agents use the same contract over REST and MCP with permissions (M6).
- [ ] A release acceptance matrix + evals gate every change (M7).

---

## 6. Issue index (all 43 open issues)

Foundation: #3 #5 #16 #19 ·
Ingestion: #6 #7 #8 #18 #31 ·
Content: #9 #10 #61 #34 ·
Indexing: #11 #12 #17 #60 ·
Retrieval: #13 #43 #45 #47 #35 #33 #36 ·
Agent API: #14 #30 #40 ·
Trust/Security: #32 #39 #41 #42 #44 ·
Evals/QA: #29 #37 #38 #15 ·
DX: #20 #21 #22 #27 #28 ·
Architecture: #46
