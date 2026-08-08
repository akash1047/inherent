---
search:
  exclude: true
---

# Runbook: Postgres/Weaviate Index Consistency (#221)

A document can report `status: processed` with a non-zero `chunk_count` in
PostgreSQL — and even return real text from `GET /v1/chunks/{id}` — while
having zero objects in its workspace's Weaviate collection/tenant. It never
appears in search (`semantic`, `hybrid`, `keyword`, any `min_score`). This is
worse than a visible failure: the dashboard shows the document as ready, and
nothing tells the caller their evidence is unreachable.

## How this happens

The shipped ingestion pipeline cannot produce this state on its own:

- `store_processed_document`
  (`services/inh-ingestion-svc/src/services/database.py`) always computes
  `document_chunks.content_hash = sha256(chunk content)` and stamps
  `ingested_at = datetime.now(UTC)` at the moment of that specific run —
  never `NULL`, never shared across two unrelated ingests.
- The Temporal workflow
  (`services/inh-ingestion-svc/src/temporal/workflows/document_ingestion.py`)
  deliberately marks the document `failed` — not `processed` — when the
  Weaviate write fails, specifically to avoid a Postgres-only "ghost"
  document (see the comment above the `wv_result.success` check).
- Grepping both services for every writer of `processed_documents` /
  `document_chunks` turns up exactly one app-level writer of chunk rows.
  Nothing in the shipped code path can leave `content_hash` NULL or stamp a
  fixed, shared `ingested_at`.

So the divergence is produced OUTSIDE the application — a direct/backfill SQL
write against production that inserted document + chunk metadata without
running the embedding step. The corroborating signal is exactly that
fingerprint: `content_hash IS NULL`, `source_uri IS NULL`, and an
`ingested_at` shared byte-for-byte by documents created months apart. No
code-level pipeline fix can prevent an out-of-band SQL write; the durable
defense is detecting the divergence, not preventing it at the ingestion
layer.

## 1. Detect: which documents are affected

```bash
uv --project services/inh-public-api-svc run python \
    scripts/check_index_consistency.py --workspace-id <workspace_id>

# Or scan every workspace with at least one processed document:
uv --project services/inh-public-api-svc run python \
    scripts/check_index_consistency.py --all-workspaces
```

Run from the repository root. The script is read-only against both stores.
For each flagged document it prints `document_id`, `name`, `chunk_count`,
`ingested_at`, and `content_hash` — enough to answer directly, from the
output, how many documents share a given backfill's timestamp with a null
`content_hash` (printed as its own "Backfill-signature summary" section).
Exit code is `1` when anything is flagged (safe to wire into a monitoring
job), `0` when the workspace(s) are clean.

Under the hood this calls
`src/services/index_consistency.py::check_workspace_index_consistency` —
the same function REST/MCP surfaces should call if this check is ever
exposed as an API, so behavior can't drift between the script and a future
endpoint.

## 2. Remediate: reindex the affected documents

`POST /v1/documents/{id}/refresh` (REST) and the `refresh_stale_source` MCP
tool are the normal re-ingest path, but they re-publish the original
`document.uploaded` event and re-run fetch → extract → chunk → store from
scratch. That is the wrong tool here: a document with this defect's
signature has no verified `storage_path` (nothing confirms the original
bytes are still reachable or still produce the SAME chunks currently on
file), and the chunks currently in Postgres are already known-good — the
issue that surfaced this runbook confirmed `GET /v1/chunks/{id}` already
returns real text for the affected documents. Re-deriving chunks from
scratch is unnecessary risk; only the missing embedding step needs to run.

Use the narrower reindex instead — it embeds the chunks exactly as they
exist in Postgres today, with no fetch/extract/chunk step:

```bash
uv --project services/inh-ingestion-svc run python \
    scripts/reindex_orphaned_document.py --document-id <document_id> \
    [--document-id <document_id> ...]
```

This calls
`src/services/reindex_from_postgres.py::reindex_document_from_postgres`,
which reuses `WeaviateService.store_chunks_with_tenant` — the same
primitive the normal pipeline's `store_in_weaviate` activity calls — so a
document reindexed this way lands in Weaviate identically to one the
pipeline just processed. It clears any partial/stale vectors for the
document first (idempotent — safe to re-run).

Re-run step 1 afterward to confirm the document no longer appears in the
report.

## 3. Prevent recurrence

There is no application-code prevention fix for a direct SQL write against
production — see "How this happens" above. Treat step 1 as a periodic check
(cron/monitoring job on `--all-workspaces`, alerting on nonzero exit) rather
than a one-time cleanup. See
[`docs/developer/learnings.md`](../developer/learnings.md) for the full
retrospective entry.
