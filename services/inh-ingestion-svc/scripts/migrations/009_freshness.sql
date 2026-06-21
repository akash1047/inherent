-- Migration 009: Add freshness metadata to document_chunks (#42)
-- Adds a single nullable/defaulted column so returned evidence can be aged:
--   ingested_at — when the chunk was (re)ingested. processed_documents already
--                 tracks processed_at; chunks previously only had created_at.
--
-- Freshness / stale-evidence policy (#42):
--   The public API promotes ingested_at onto each SearchResult and computes
--   is_stale = ingested_at < (now - freshness_max_age_days). Stale evidence is
--   NOT filtered out — it is still returned, flagged with is_stale=true, so
--   callers can decide how to treat aged sources (a "refresh" path can re-ingest).
--
-- Idempotent & additive (follows the migration-safety conventions in README.md):
--   - IF NOT EXISTS guard makes re-runs a no-op.
--   - DEFAULT NOW() means new inserts are stamped automatically; existing rows
--     are backfilled to their migration time, which is a safe, monotonic proxy
--     (pre-existing chunks are treated as ingested "now" until re-ingested).
--   - No data is dropped or rewritten beyond the additive default backfill.

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMPTZ DEFAULT NOW();
