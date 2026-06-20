# ADR 0001 — Inherent as an Agent Memory Substrate

- **Status:** Accepted (initial draft)
- **Date:** 2026-06-20
- **Deciders:** maintainers
- **Closes:** #46
- **Related:** [org-readiness requirements](../maintainers/org-readiness-requirements.md)

## Context

Inherent today is an ingestion + retrieval RAG backend: it ingests documents,
chunks and embeds them, stores them in PostgreSQL + Weaviate, and serves search
over REST and an MCP server. The strategic direction is larger than the current
README — Inherent should become the **memory layer that an organization's agents
query continuously** — but that direction needs a written boundary so
implementation work stays focused and does not drift into building a generic
chat product, a browser/web-agent runtime, or speculative advanced-retrieval
features that no eval justifies.

This ADR defines what Inherent *is*, the guarantees it makes, what it is
explicitly *not* in the near term, and how the open issue backlog maps onto a
phased architecture.

## Decision

**Inherent is a self-hostable agent memory substrate: a permission-aware,
provenance-tracked, freshness-aware, citeable retrieval layer that an
organization's agents can query continuously over REST and MCP.**

It is the *memory* an agent reads from and writes provenance to — not the agent
runtime, not the chat UI, not the orchestration layer.

### Positioning

- For SMEs/orgs with internal documents but **no existing context stack**.
- Self-hosted via Docker Compose; one-command path to a working stack.
- Consumed by **agents** through stable, versioned REST + MCP tool contracts —
  not primarily by humans through a chat interface.
- The retrieval surface is *data for agents to reason over*, kept strictly
  separate from instructions the agent executes.

### Core guarantees (the north star)

These are the properties that make the substrate trustworthy enough to point an
autonomous agent at. Every feature is judged against whether it preserves them.

1. **Permission-aware** — retrieval enforces tenant/workspace/principal
   authorization and provenance at the *chunk* level, including context-window
   expansion. No caller can read another's data through any path. (#41, #32, #14)
2. **Fresh** — sources, documents, and chunks carry freshness metadata; stale
   evidence is detectable and refreshable. (#42)
3. **Cited** — responses expose stable evidence IDs and spans; claims can be
   verified against returned evidence. (#39)
4. **Auditable** — what was considered and what was returned is recorded;
   quality verdicts and reason codes are machine-readable. (#43, audit in #41)
5. **Safe** — retrieved content is treated as untrusted; poisoning and
   prompt-injection are defended at ingestion and query time. (#44)
6. **Measurable & low-cost** — retrieval quality and cost are gated by evals
   against a documented baseline before any heavier method becomes default.
   (#45, #33, #35, #36, #37, #47)
7. **Durable** — ingestion never silently strands documents; every document has
   a visible lifecycle; reprocessing is idempotent. (#6, #7, #8, #11, #16)

### Non-goals (near term)

Naming these explicitly prevents scope creep:

- **Not** a generic chat UI or assistant product. Inherent serves agents and
  APIs; any UI is a thin operator/demo concern, not the product.
- **Not** a browser/web-agent runtime. Web-backed source ingestion may arrive
  later as a *source type*, but autonomous browsing/acting is out of scope.
- **Not** an agent orchestration / planning framework. Inherent exposes memory
  primitives; orchestration lives in the caller's agent.
- **No advanced retrieval on by default.** GraphRAG, hierarchical (RAPTOR-style)
  summaries, and cross-encoder/late-interaction reranking stay feature-flagged
  off until an eval shows they beat the hybrid baseline. (#47)
- **Not** a multi-model embedding marketplace. One configured, model-aware
  embedding path; swapping models is a deliberate, eval-gated change. (#10)

### North-star architecture

```text
            sources (PDF, DOCX, HTML, JSON, TXT, CSV, code, images…)
                                  │
                                  ▼
        ┌───────────────────────────────────────────────┐
        │  inh-ingestion-svc                             │
        │  durable handoff → extract → chunk (model-     │
        │  aware) → embed (TEI) → index (idempotent)     │
        │  + provenance/ACL + freshness + trust signals  │
        └───────────────┬───────────────────────────────┘
                        │  versioned event + index contracts (#17)
        ┌───────────────┴───────────────┐
        ▼                               ▼
  ┌───────────┐                   ┌───────────┐
  │PostgreSQL │  documents,       │ Weaviate  │  vectors + ACL/
  │           │  status, ACL,     │           │  provenance/freshness
  │           │  dead-letter      │           │  metadata
  └─────┬─────┘                   └─────┬─────┘
        └───────────────┬───────────────┘
                        ▼
        ┌───────────────────────────────────────────────┐
        │  inh-public-api-svc  (REST + MCP, shared core) │
        │  hybrid retrieval baseline → permission +      │
        │  freshness filters → quality gate / fallback → │
        │  citations + trust/risk metadata               │
        └───────────────┬───────────────────────────────┘
                        ▼
                  org agents (continuous queries)
```

The defining architectural commitment: **REST and MCP share the same core
services** (auth, search, citation, freshness) so the two surfaces cannot drift
in security or behavior. (#14, #40, #30)

### Phased milestones

Mapped in full in the [org-readiness requirements](../maintainers/org-readiness-requirements.md).
Summary of MVP → next → later:

| Phase | Theme | Capabilities |
|-------|-------|--------------|
| **MVP** | Run it + don't lose it | One-command setup, OSS bootstrap, fresh-safe migrations, durable ingestion, lifecycle status, idempotent reindex, Compose integration test |
| **Next** | Relevant + safe | Hybrid retrieval baseline + golden evals, concurrent multi-workspace search, chunk-level ACL/provenance, freshness, citations, poisoning defenses, MCP parity + memory tools |
| **Later** | Govern + extend | Eval governance + release acceptance matrix, adaptive quality gates, eval-gated advanced indexes (graph/hierarchy/rerank) |

## Backlog → architecture map

- **Foundation / run-it:** #3, #5, #16, #19 (+ #15 proof)
- **Durable ingestion:** #6, #7, #8, #18, #31; idempotency #11, #60; contracts #17
- **Content fidelity:** #9, #10, #61; scale #12; evals #34
- **Retrieval:** baseline #45, multi-workspace #13, quality gates #43,
  advanced #47; evals #33, #35, #36
- **Agent surface:** #14, #40, #30
- **Trust & security:** #41, #42, #39, #44, #32
- **Evals & QA governance:** #29, #37, #38
- **DX:** #20, #21, #22, #27, #28

## Consequences

- **Positive:** contributors have one boundary to check work against; "is this
  in scope?" has a written answer; advanced retrieval cannot land without eval
  evidence; security/freshness/citation are first-class, not afterthoughts.
- **Negative / cost:** chunk-level ACL, provenance, and freshness add storage
  and write-path complexity to ingestion and metadata to the index; the
  shared-core requirement constrains how REST and MCP can evolve independently.
- **Revisit when:** an eval shows an advanced-retrieval method beats baseline; a
  real customer need pushes a current non-goal (e.g. web sources) into scope; or
  the embedding-model strategy needs to change.
