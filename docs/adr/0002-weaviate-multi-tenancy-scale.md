# ADR 0002 — Weaviate Multi-Tenancy and Scale Strategy

- **Status:** Accepted (initial draft)
- **Date:** 2026-06-20
- **Deciders:** maintainers
- **Closes:** #12
- **Related:** [ADR 0001](0001-agent-memory-substrate.md)

## Context

Inherent stores document chunk vectors in Weaviate and must keep every
workspace's data isolated from every other workspace, and every user's data
isolated within their workspace. Two services touch this storage:

- `inh-ingestion-svc` writes chunks (extract → chunk → embed → index).
- `inh-public-api-svc` reads chunks (search / retrieve).

For isolation to work, both services must compute the **exact same** Weaviate
collection and tenant names from the same workspace and user identifiers. There
is no shared library between the services today, so the naming rules are
duplicated — once in `inh-ingestion-svc/src/services/weaviate.py` and once in
`inh-public-api-svc/src/services/search.py`. Any silent divergence between the
two copies would route reads and writes to different physical locations and
manifest as "ingested documents are not searchable," which is hard to diagnose.

## Decision

### Tenancy model

- **One Weaviate collection per workspace.** The collection name is
  `Workspace_<sanitized_workspace_id>`.
- **One Weaviate tenant per user**, living inside that workspace collection. The
  tenant name is `User_<sanitized_user_id>`.

Sanitization strips every non-alphanumeric character from the raw identifier
(`re.sub(r"[^a-zA-Z0-9]", "", id)`) before applying the `Workspace_` / `User_`
prefix. This keeps names valid as Weaviate class/tenant identifiers regardless
of the formatting of upstream IDs (UUIDs, slugs, emails, etc.).

This gives hard isolation at two levels: workspaces never share a collection,
and Weaviate's native multi-tenancy isolates users within a collection.

### Guarding the drift risk with a golden naming contract

Because the naming logic is duplicated across two services with no shared
package, drift is the primary risk. We guard it with **golden naming contract
tests in BOTH services** that pin the same fixed input → output vectors:

| Raw input        | Function                          | Expected output (golden) |
|------------------|-----------------------------------|--------------------------|
| `ws_local_001`   | workspace-collection naming       | `Workspace_wslocal001`   |
| `local-dev-user` | user-tenant naming                | `User_localdevuser`      |

These vectors correspond to the local dev workspace and user, so they are also
exercised end-to-end by the local smoke test. The ingestion-side contract lives
in `services/inh-ingestion-svc/tests/test_multi_tenancy.py` and the public-api
side in `services/inh-public-api-svc/tests/unit/test_search_service.py`. If
either service's sanitization changes (e.g. someone preserves underscores or
lowercases differently), its golden test fails in CI before the divergence can
ship and break cross-service retrieval.

## Known and assumed scale limits

The current model is deliberately simple and is correct for the present scale,
but it has assumed ceilings worth recording:

- **Collections grow linearly with workspaces.** One collection per workspace
  means thousands of workspaces become thousands of Weaviate collections. Each
  collection carries schema and index overhead; very large collection counts
  pressure Weaviate memory and startup/schema-load time.
- **Tenants grow linearly with users per workspace.** Native multi-tenancy
  scales to many tenants per collection, but tenant activation/load has a
  per-tenant cost; a workspace with a very large user count concentrates that
  cost in a single collection.
- **No sharding by tier or region.** All workspaces live in one Weaviate
  cluster; there is no placement strategy separating large/noisy tenants from
  small ones, nor any per-tier resource isolation.
- **Naming is single-sourced only by tests, not by code.** The contract is
  enforced, but the two implementations must still be edited in lockstep.

These limits are acceptable today (early scale, local-first / single-cluster
deployments) and are documented here so the trigger points for the next phase
are explicit rather than discovered in an incident.

## Future scaling path

When the limits above start to bind, the planned evolution is:

1. **Extract a `shared-contracts` package.** Move the workspace/user naming
   functions (and related schema constants) into a single package imported by
   both services, replacing duplicated-code-plus-golden-tests with a single
   source of truth. The golden vectors above become that package's own test
   suite so the contract survives the refactor.
2. **Collection sharding by tier.** Introduce placement so workspaces map onto
   multiple Weaviate clusters/shards by tier (e.g. free vs. paid, or by region
   for data-residency), keeping per-cluster collection counts bounded and
   isolating large tenants from the long tail.
3. **Revisit per-workspace-collection granularity** for very large fleets
   (e.g. collection-per-tier with workspace as a property/tenant dimension) if
   collection-count overhead dominates, guided by retrieval and indexing evals
   rather than speculation.

## Consequences

- Strong, easy-to-reason-about isolation now, with no premature complexity.
- Cross-service correctness is protected by golden naming contract tests in both
  services; CI catches drift before it reaches production.
- The scaling path is staged: shared contracts first (low risk, removes the
  duplication hazard), then sharding only when scale data justifies it.
