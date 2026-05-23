-- Migration 005: Ingestion Staging Table
-- Purpose: Staging area for large intermediate data during Temporal workflows.
-- Activities write extracted text and chunks here instead of passing them
-- through gRPC (which has a 4MB limit). Each workflow run gets its own
-- staging rows, cleaned up on completion.

CREATE TABLE IF NOT EXISTS ingestion_staging (
    workflow_run_id TEXT NOT NULL,
    data_key TEXT NOT NULL,          -- 'extracted_text' or 'chunks'
    text_data TEXT,                   -- for extracted text
    json_data JSONB,                 -- for structured data (chunks array)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (workflow_run_id, data_key)
);

-- Index for cleanup of stale rows from crashed workflows
CREATE INDEX IF NOT EXISTS idx_staging_created ON ingestion_staging(created_at);
