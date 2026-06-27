-- Migration 010: Add document-level content_hash to processed_documents (#75)
-- Adds a single nullable column plus a lookup index so the upload handler can
-- dedup re-uploads by CONTENT, not just by filename.
--
-- Dedup / search-flood policy (#75):
--   Dedup previously keyed only on (workspace_id, original_filename). Re-uploading
--   identical content under a DIFFERENT filename created a brand-new document_id,
--   duplicate chunks, and duplicate embeddings — which then flooded top-k search
--   results with the same content and pushed out genuinely distinct documents.
--   The public API now computes sha256(file_bytes) at upload time and reuses the
--   existing document_id when the same content already exists in the workspace,
--   regardless of filename. content_hash is the document-level dedup key.
--
-- Idempotent & additive (follows the migration-safety conventions in README.md):
--   - IF NOT EXISTS guards make re-runs a no-op.
--   - The column is nullable: pre-existing rows (and the ingestion service, which
--     never sets it) simply have content_hash = NULL and are matched by filename
--     dedup as before. New uploads backfill it going forward.
--   - No data is dropped or rewritten.

ALTER TABLE processed_documents
    ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);

-- Composite index for the (workspace_id, content_hash) dedup lookup. Partial on
-- NOT NULL so legacy rows without a hash do not bloat the index.
CREATE INDEX IF NOT EXISTS idx_processed_documents_workspace_content_hash
    ON processed_documents(workspace_id, content_hash)
    WHERE content_hash IS NOT NULL;
