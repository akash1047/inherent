-- Migration 007: Drop document versioning objects
-- This migration removes all versioning-related database objects.
-- The document_chunks table (legacy/non-versioned) remains as the primary chunk store.
--
-- IMPORTANT: Before running this migration, verify no documents have chunks
-- ONLY in version_chunks (not in document_chunks). If any do, backfill them first:
--
--   SELECT DISTINCT vc.document_id
--   FROM version_chunks vc
--   LEFT JOIN document_chunks dc ON dc.document_id = vc.document_id
--   WHERE dc.document_id IS NULL;

-- Drop trigger first
DROP TRIGGER IF EXISTS trigger_log_version_events ON document_versions;
DROP FUNCTION IF EXISTS log_version_event();

-- Drop views
DROP VIEW IF EXISTS v_current_versions;
DROP VIEW IF EXISTS v_version_history;
DROP VIEW IF EXISTS v_workspace_version_stats;

-- Drop helper functions
DROP FUNCTION IF EXISTS get_current_version(VARCHAR);
DROP FUNCTION IF EXISTS get_version_at_timestamp(VARCHAR, TIMESTAMPTZ);
DROP FUNCTION IF EXISTS get_next_version_number(VARCHAR);
DROP FUNCTION IF EXISTS supersede_version(VARCHAR, VARCHAR);

-- Drop tables (FK order matters)
DROP TABLE IF EXISTS version_events CASCADE;
DROP TABLE IF EXISTS retrieval_audit_log CASCADE;
DROP TABLE IF EXISTS version_chunks CASCADE;
DROP TABLE IF EXISTS document_versions CASCADE;
