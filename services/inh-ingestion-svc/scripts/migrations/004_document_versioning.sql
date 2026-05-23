-- Migration 004: Document Versioning System
-- This migration adds comprehensive document versioning support with:
-- - Immutable version tracking (document_versions)
-- - Version-aware chunk storage (version_chunks)
-- - Compliance-ready audit logging (retrieval_audit_log)
-- - Version lifecycle events (version_events)
--
-- Design Principles:
-- - Additive schema (no breaking changes to existing tables)
-- - Version-aware chunks linked to versions, not documents directly
-- - Temporal range queries via effective_from/effective_until
-- - Content deduplication via hash-based skip
-- - Workspace isolation enforced at every level

-- ============================================
-- STEP 1: Create document_versions table
-- ============================================
-- Core version tracking - every document upload creates a new version
CREATE TABLE IF NOT EXISTS document_versions (
    -- Primary key
    id BIGSERIAL PRIMARY KEY,

    -- API-facing identifier (UUID for external reference)
    version_id VARCHAR(100) NOT NULL UNIQUE,

    -- Reference to MongoDB document
    document_id VARCHAR(100) NOT NULL,

    -- Sequential version number per document
    version_number INTEGER NOT NULL,

    -- Ownership (denormalized for query efficiency)
    workspace_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    tenant_id BIGINT,

    -- Version lifecycle
    -- current: This is the active version
    -- previous: This version was superseded by a newer one
    -- superseded: This version was explicitly replaced (restore, reprocess)
    status VARCHAR(20) NOT NULL DEFAULT 'current',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- Content fingerprint for deduplication
    -- SHA-256 hash of normalized content
    content_hash VARCHAR(64) NOT NULL,

    -- Metrics
    chunk_count INTEGER NOT NULL DEFAULT 0,
    text_length INTEGER NOT NULL DEFAULT 0,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    processing_time_ms INTEGER DEFAULT 0,

    -- Storage reference (where the original file is stored)
    storage_backend VARCHAR(20) NOT NULL,
    storage_path VARCHAR(1000) NOT NULL,
    storage_bucket VARCHAR(255),

    -- Change context
    -- initial: First version of document
    -- update: New content uploaded
    -- restore: Restored from previous version
    -- reprocess: Re-ingested with new settings
    change_type VARCHAR(50) NOT NULL DEFAULT 'initial',
    change_summary TEXT,
    created_by VARCHAR(100) NOT NULL,

    -- Temporal range for point-in-time queries
    -- effective_from: When this version became active
    -- effective_until: When this version was superseded (NULL = current)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    effective_until TIMESTAMPTZ,

    -- Composite unique constraint: one version number per document
    CONSTRAINT uq_document_version UNIQUE (document_id, version_number),

    -- Status must be valid
    CONSTRAINT chk_version_status CHECK (status IN ('current', 'previous', 'superseded')),

    -- Change type must be valid
    CONSTRAINT chk_change_type CHECK (change_type IN ('initial', 'update', 'restore', 'reprocess'))
);

-- Critical indexes for version queries
-- Primary lookup: Get all versions for a document
CREATE INDEX IF NOT EXISTS idx_versions_document_id ON document_versions(document_id);

-- Fast lookup for current version
CREATE INDEX IF NOT EXISTS idx_versions_current ON document_versions(document_id)
    WHERE status = 'current' AND is_active = TRUE;

-- Point-in-time queries: Find version active at a specific timestamp
CREATE INDEX IF NOT EXISTS idx_versions_pit ON document_versions(workspace_id, effective_from, effective_until)
    WHERE is_active = TRUE;

-- Workspace isolation
CREATE INDEX IF NOT EXISTS idx_versions_workspace ON document_versions(workspace_id);
CREATE INDEX IF NOT EXISTS idx_versions_workspace_doc ON document_versions(workspace_id, document_id);

-- Content hash lookup for deduplication
CREATE INDEX IF NOT EXISTS idx_versions_content_hash ON document_versions(document_id, content_hash);

-- Tenant isolation
CREATE INDEX IF NOT EXISTS idx_versions_tenant ON document_versions(tenant_id);

-- ============================================
-- STEP 2: Create version_chunks table
-- ============================================
-- Versioned chunk storage - chunks belong to versions, not documents
CREATE TABLE IF NOT EXISTS version_chunks (
    -- Primary key
    id BIGSERIAL PRIMARY KEY,

    -- Foreign key to version
    version_id BIGINT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,

    -- Denormalized for query efficiency (avoids JOINs)
    document_id VARCHAR(100) NOT NULL,
    workspace_id VARCHAR(100) NOT NULL,
    version_number INTEGER NOT NULL,

    -- Chunk data
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,

    -- Content hash for diff detection
    content_hash VARCHAR(64) NOT NULL,

    -- Token count for context window management
    token_count INTEGER,

    -- Position in original document
    start_char INTEGER DEFAULT 0,
    end_char INTEGER DEFAULT 0,

    -- Chunk metadata (page number, section, headers, etc.)
    metadata JSONB,

    -- Weaviate reference for linking search results
    weaviate_uuid UUID,

    -- Timestamp
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Unique constraint: one chunk per index per version
    CONSTRAINT uq_version_chunk_idx UNIQUE (version_id, chunk_index),

    -- Ensure chunk_index is non-negative
    CONSTRAINT chk_chunk_index_positive CHECK (chunk_index >= 0)
);

-- Indexes for version_chunks
-- Primary lookup: Get all chunks for a version
CREATE INDEX IF NOT EXISTS idx_version_chunks_version_id ON version_chunks(version_id);

-- Document-level queries
CREATE INDEX IF NOT EXISTS idx_version_chunks_document_id ON version_chunks(document_id);

-- Workspace isolation (CRITICAL for multi-tenancy)
CREATE INDEX IF NOT EXISTS idx_version_chunks_workspace ON version_chunks(workspace_id);

-- Combined index for workspace + document queries
CREATE INDEX IF NOT EXISTS idx_version_chunks_workspace_doc ON version_chunks(workspace_id, document_id);

-- Weaviate reference lookup
CREATE INDEX IF NOT EXISTS idx_version_chunks_weaviate_uuid ON version_chunks(weaviate_uuid)
    WHERE weaviate_uuid IS NOT NULL;

-- ============================================
-- STEP 3: Create retrieval_audit_log table
-- ============================================
-- Compliance audit trail for all retrieval operations
CREATE TABLE IF NOT EXISTS retrieval_audit_log (
    -- Primary key
    id BIGSERIAL PRIMARY KEY,

    -- API-facing identifier
    audit_id VARCHAR(100) NOT NULL UNIQUE,

    -- Context
    workspace_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    api_key_id VARCHAR(100),

    -- Query details
    -- search: Semantic search query
    -- retrieve: Direct document retrieval
    -- diff: Version comparison
    -- restore: Version restoration
    -- list: Version list query
    query_type VARCHAR(50) NOT NULL,
    query_text TEXT,
    query_filters JSONB,

    -- Results
    result_count INTEGER NOT NULL DEFAULT 0,
    documents_accessed JSONB NOT NULL DEFAULT '[]',
    versions_used JSONB NOT NULL DEFAULT '[]',

    -- Timestamps
    query_timestamp TIMESTAMPTZ NOT NULL,
    target_timestamp TIMESTAMPTZ,  -- For point-in-time queries

    -- Request metadata
    request_id VARCHAR(100),
    response_time_ms INTEGER,

    -- Record timestamp
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Query type must be valid
    CONSTRAINT chk_query_type CHECK (query_type IN ('search', 'retrieve', 'diff', 'restore', 'list'))
);

-- Indexes for audit log
-- Workspace isolation for audit queries
CREATE INDEX IF NOT EXISTS idx_audit_workspace ON retrieval_audit_log(workspace_id);

-- Time-based queries (most recent first)
CREATE INDEX IF NOT EXISTS idx_audit_created ON retrieval_audit_log(created_at DESC);

-- User activity queries
CREATE INDEX IF NOT EXISTS idx_audit_user ON retrieval_audit_log(user_id, created_at DESC);

-- Query type filtering
CREATE INDEX IF NOT EXISTS idx_audit_query_type ON retrieval_audit_log(query_type, created_at DESC);

-- Combined workspace + time for compliance reports
CREATE INDEX IF NOT EXISTS idx_audit_workspace_time ON retrieval_audit_log(workspace_id, created_at DESC);

-- ============================================
-- STEP 4: Create version_events table
-- ============================================
-- Version lifecycle events for audit and debugging
CREATE TABLE IF NOT EXISTS version_events (
    -- Primary key
    id BIGSERIAL PRIMARY KEY,

    -- API-facing identifier
    event_id VARCHAR(100) NOT NULL UNIQUE,

    -- Version reference
    version_id BIGINT NOT NULL REFERENCES document_versions(id),
    document_id VARCHAR(100) NOT NULL,

    -- Event type
    -- created: Version was created
    -- activated: Version became the current version
    -- superseded: Version was replaced by newer version
    -- restored: Version content was restored (creates new version)
    event_type VARCHAR(50) NOT NULL,

    -- Event-specific data
    event_data JSONB DEFAULT '{}',

    -- Actor
    actor_user_id VARCHAR(100) NOT NULL,

    -- Timestamp
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Event type must be valid
    CONSTRAINT chk_event_type CHECK (event_type IN ('created', 'activated', 'superseded', 'restored'))
);

-- Indexes for version_events
-- Primary lookup: Events for a version
CREATE INDEX IF NOT EXISTS idx_version_events_version ON version_events(version_id);

-- Document-level event history
CREATE INDEX IF NOT EXISTS idx_version_events_document ON version_events(document_id, created_at DESC);

-- Event type filtering
CREATE INDEX IF NOT EXISTS idx_version_events_type ON version_events(event_type, created_at DESC);

-- ============================================
-- STEP 5: Helper functions
-- ============================================

-- Function to get the current version for a document
CREATE OR REPLACE FUNCTION get_current_version(p_document_id VARCHAR(100))
RETURNS document_versions AS $$
DECLARE
    v_result document_versions%ROWTYPE;
BEGIN
    SELECT * INTO v_result
    FROM document_versions
    WHERE document_id = p_document_id
      AND status = 'current'
      AND is_active = TRUE
    LIMIT 1;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to get version at a specific point in time
CREATE OR REPLACE FUNCTION get_version_at_timestamp(
    p_document_id VARCHAR(100),
    p_timestamp TIMESTAMPTZ
)
RETURNS document_versions AS $$
DECLARE
    v_result document_versions%ROWTYPE;
BEGIN
    SELECT * INTO v_result
    FROM document_versions
    WHERE document_id = p_document_id
      AND is_active = TRUE
      AND effective_from <= p_timestamp
      AND (effective_until IS NULL OR effective_until > p_timestamp)
    LIMIT 1;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to get next version number for a document
CREATE OR REPLACE FUNCTION get_next_version_number(p_document_id VARCHAR(100))
RETURNS INTEGER AS $$
DECLARE
    v_max_version INTEGER;
BEGIN
    SELECT COALESCE(MAX(version_number), 0) INTO v_max_version
    FROM document_versions
    WHERE document_id = p_document_id;

    RETURN v_max_version + 1;
END;
$$ LANGUAGE plpgsql;

-- Function to supersede a version
CREATE OR REPLACE FUNCTION supersede_version(
    p_document_id VARCHAR(100),
    p_new_status VARCHAR(20) DEFAULT 'previous'
)
RETURNS VOID AS $$
BEGIN
    UPDATE document_versions
    SET
        status = p_new_status,
        effective_until = NOW()
    WHERE document_id = p_document_id
      AND status = 'current'
      AND is_active = TRUE;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- STEP 6: Create useful views
-- ============================================

-- View: Current versions with latest stats
CREATE OR REPLACE VIEW v_current_versions AS
SELECT
    dv.id,
    dv.version_id,
    dv.document_id,
    dv.version_number,
    dv.workspace_id,
    dv.user_id,
    dv.content_hash,
    dv.chunk_count,
    dv.text_length,
    dv.size_bytes,
    dv.change_type,
    dv.change_summary,
    dv.created_at,
    dv.effective_from
FROM document_versions dv
WHERE dv.status = 'current'
  AND dv.is_active = TRUE;

-- View: Version history with document info
CREATE OR REPLACE VIEW v_version_history AS
SELECT
    dv.document_id,
    dv.version_number,
    dv.version_id,
    dv.status,
    dv.change_type,
    dv.change_summary,
    dv.chunk_count,
    dv.text_length,
    dv.size_bytes,
    dv.created_by,
    dv.created_at,
    dv.effective_from,
    dv.effective_until,
    dv.workspace_id
FROM document_versions dv
WHERE dv.is_active = TRUE
ORDER BY dv.document_id, dv.version_number DESC;

-- View: Workspace version statistics
CREATE OR REPLACE VIEW v_workspace_version_stats AS
SELECT
    workspace_id,
    COUNT(DISTINCT document_id) as total_documents,
    COUNT(*) as total_versions,
    SUM(CASE WHEN status = 'current' THEN 1 ELSE 0 END) as current_versions,
    AVG(version_number) as avg_versions_per_doc,
    SUM(chunk_count) as total_chunks,
    SUM(size_bytes) as total_size_bytes
FROM document_versions
WHERE is_active = TRUE
GROUP BY workspace_id;

-- ============================================
-- STEP 7: Triggers for automatic timestamp management
-- ============================================

-- Trigger function for version events
CREATE OR REPLACE FUNCTION log_version_event()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO version_events (
            event_id,
            version_id,
            document_id,
            event_type,
            event_data,
            actor_user_id,
            created_at
        ) VALUES (
            'evt_' || gen_random_uuid()::text,
            NEW.id,
            NEW.document_id,
            'created',
            jsonb_build_object(
                'version_number', NEW.version_number,
                'change_type', NEW.change_type
            ),
            NEW.created_by,
            NOW()
        );
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.status = 'current' AND NEW.status != 'current' THEN
            INSERT INTO version_events (
                event_id,
                version_id,
                document_id,
                event_type,
                event_data,
                actor_user_id,
                created_at
            ) VALUES (
                'evt_' || gen_random_uuid()::text,
                NEW.id,
                NEW.document_id,
                'superseded',
                jsonb_build_object(
                    'version_number', NEW.version_number,
                    'new_status', NEW.status
                ),
                NEW.user_id,
                NOW()
            );
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for version events
DROP TRIGGER IF EXISTS trigger_log_version_events ON document_versions;
CREATE TRIGGER trigger_log_version_events
    AFTER INSERT OR UPDATE ON document_versions
    FOR EACH ROW
    EXECUTE FUNCTION log_version_event();

-- ============================================
-- VERIFICATION
-- ============================================
-- Show new table structures
SELECT
    'document_versions' AS table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'document_versions'
ORDER BY ordinal_position;

SELECT
    'version_chunks' AS table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'version_chunks'
ORDER BY ordinal_position;

SELECT
    'retrieval_audit_log' AS table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'retrieval_audit_log'
ORDER BY ordinal_position;

SELECT
    'version_events' AS table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'version_events'
ORDER BY ordinal_position;
