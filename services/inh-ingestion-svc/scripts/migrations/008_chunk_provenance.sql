-- Migration 008: Add lightweight provenance to document_chunks (#41)
-- Adds two nullable, additive columns so returned evidence is auditable:
--   content_hash — sha256 hex digest (64 chars) of the chunk's content
--   source_uri   — where the chunk's source bytes live (storage_path / storage_url)
--
-- Idempotent & additive (follows the migration-safety conventions in README.md):
--   - IF NOT EXISTS guards make re-runs a no-op.
--   - Both columns are NULLABLE, so existing rows are unaffected and the change
--     is backward-compatible. Pre-existing chunks simply have NULL provenance
--     until re-ingested.
--   - No data is dropped or rewritten.

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS source_uri VARCHAR(2000);
