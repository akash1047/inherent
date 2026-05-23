-- Migration 002: Multi-Tenancy Support
-- This migration adds tenant and workspace metadata tables for multi-tenancy
--
-- Design:
-- - tenants table: Tracks user-level tenants for lifecycle management
-- - workspace_metadata table: Tracks workspace-level metadata and stats
-- - Adds tenant_id to existing tables for query optimization
--
-- Multi-tenancy Model:
-- - Each User = One Tenant
-- - Each Workspace = One Weaviate Collection
-- - Tenants can have multiple workspaces
-- - Each workspace has one owner (user_id)

-- ============================================
-- STEP 1: Create tenants table
-- ============================================
-- Tracks user-level tenants for lifecycle management
CREATE TABLE IF NOT EXISTS tenants (
    id BIGSERIAL PRIMARY KEY,

    -- User identifier (from MongoDB ObjectId)
    user_id VARCHAR(100) NOT NULL UNIQUE,

    -- Tenant status for lifecycle management
    -- active: Tenant is active and can be used
    -- inactive: Tenant has been deactivated (cost optimization)
    -- suspended: Tenant is suspended (billing/policy)
    status VARCHAR(20) NOT NULL DEFAULT 'active',

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Extensible metadata (quotas, features, etc.)
    metadata JSONB DEFAULT '{}',

    -- Constraints
    CONSTRAINT chk_tenant_status CHECK (status IN ('active', 'inactive', 'suspended'))
);

-- Index for status-based queries (e.g., finding inactive tenants)
CREATE INDEX IF NOT EXISTS idx_tenants_status ON tenants(status);
CREATE INDEX IF NOT EXISTS idx_tenants_last_activity ON tenants(last_activity_at);

-- ============================================
-- STEP 2: Create workspace_metadata table
-- ============================================
-- Tracks workspace-level metadata and statistics
CREATE TABLE IF NOT EXISTS workspace_metadata (
    id BIGSERIAL PRIMARY KEY,

    -- Workspace identifier (from MongoDB ObjectId)
    workspace_id VARCHAR(100) NOT NULL UNIQUE,

    -- Owner reference (links to tenants table)
    user_id VARCHAR(100) NOT NULL,

    -- Weaviate collection name for this workspace
    weaviate_collection VARCHAR(200),

    -- Aggregated statistics
    document_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    total_size_bytes BIGINT NOT NULL DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Extensible metadata (settings, quotas, etc.)
    metadata JSONB DEFAULT '{}',

    -- Foreign key to tenants (optional, cascade on user deletion)
    CONSTRAINT fk_workspace_tenant
        FOREIGN KEY (user_id)
        REFERENCES tenants(user_id)
        ON DELETE CASCADE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_workspace_metadata_user_id ON workspace_metadata(user_id);

-- ============================================
-- STEP 3: Add tenant_id to processed_documents
-- ============================================
-- Add tenant_id column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'processed_documents'
        AND column_name = 'tenant_id'
    ) THEN
        ALTER TABLE processed_documents ADD COLUMN tenant_id BIGINT;
    END IF;
END $$;

-- Create index for tenant-based queries
CREATE INDEX IF NOT EXISTS idx_processed_documents_tenant_id
    ON processed_documents(tenant_id);

-- Create composite index for tenant + workspace queries
CREATE INDEX IF NOT EXISTS idx_processed_documents_tenant_workspace
    ON processed_documents(tenant_id, workspace_id);

-- ============================================
-- STEP 4: Add tenant_id to document_chunks
-- ============================================
-- Add tenant_id column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'document_chunks'
        AND column_name = 'tenant_id'
    ) THEN
        ALTER TABLE document_chunks ADD COLUMN tenant_id BIGINT;
    END IF;
END $$;

-- Create index for tenant-based queries
CREATE INDEX IF NOT EXISTS idx_document_chunks_tenant_id
    ON document_chunks(tenant_id);

-- ============================================
-- STEP 5: Create helper functions
-- ============================================

-- Function to update workspace statistics atomically
CREATE OR REPLACE FUNCTION update_workspace_stats(
    p_workspace_id VARCHAR(100),
    p_document_delta INTEGER DEFAULT 0,
    p_chunk_delta INTEGER DEFAULT 0,
    p_size_delta BIGINT DEFAULT 0
)
RETURNS VOID AS $$
BEGIN
    UPDATE workspace_metadata
    SET
        document_count = GREATEST(0, document_count + p_document_delta),
        chunk_count = GREATEST(0, chunk_count + p_chunk_delta),
        total_size_bytes = GREATEST(0, total_size_bytes + p_size_delta),
        updated_at = NOW()
    WHERE workspace_id = p_workspace_id;
END;
$$ LANGUAGE plpgsql;

-- Function to update tenant last activity
CREATE OR REPLACE FUNCTION update_tenant_activity(p_user_id VARCHAR(100))
RETURNS VOID AS $$
BEGIN
    UPDATE tenants
    SET
        last_activity_at = NOW(),
        updated_at = NOW()
    WHERE user_id = p_user_id;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update tenants.updated_at
CREATE OR REPLACE FUNCTION update_tenants_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_tenants_updated_at ON tenants;
CREATE TRIGGER trigger_tenants_updated_at
    BEFORE UPDATE ON tenants
    FOR EACH ROW
    EXECUTE FUNCTION update_tenants_updated_at();

-- Trigger to auto-update workspace_metadata.updated_at
DROP TRIGGER IF EXISTS trigger_workspace_metadata_updated_at ON workspace_metadata;
CREATE TRIGGER trigger_workspace_metadata_updated_at
    BEFORE UPDATE ON workspace_metadata
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- STEP 6: Create useful views
-- ============================================

-- View: Tenant summary with workspace counts
CREATE OR REPLACE VIEW v_tenant_summary AS
SELECT
    t.id AS tenant_id,
    t.user_id,
    t.status,
    t.created_at,
    t.last_activity_at,
    COUNT(wm.id) AS workspace_count,
    COALESCE(SUM(wm.document_count), 0) AS total_documents,
    COALESCE(SUM(wm.chunk_count), 0) AS total_chunks,
    COALESCE(SUM(wm.total_size_bytes), 0) AS total_size_bytes
FROM tenants t
LEFT JOIN workspace_metadata wm ON t.user_id = wm.user_id
GROUP BY t.id, t.user_id, t.status, t.created_at, t.last_activity_at;

-- View: Workspace summary with document details
CREATE OR REPLACE VIEW v_workspace_summary AS
SELECT
    wm.id,
    wm.workspace_id,
    wm.user_id,
    wm.weaviate_collection,
    wm.document_count,
    wm.chunk_count,
    wm.total_size_bytes,
    wm.created_at,
    wm.updated_at,
    t.status AS tenant_status,
    (
        SELECT COUNT(*)
        FROM processed_documents pd
        WHERE pd.workspace_id = wm.workspace_id
        AND pd.status = 'processed'
    ) AS processed_document_count,
    (
        SELECT COUNT(*)
        FROM processed_documents pd
        WHERE pd.workspace_id = wm.workspace_id
        AND pd.status = 'failed'
    ) AS failed_document_count
FROM workspace_metadata wm
LEFT JOIN tenants t ON wm.user_id = t.user_id;

-- View: Idle tenants (for cleanup jobs)
CREATE OR REPLACE VIEW v_idle_tenants AS
SELECT
    t.*,
    NOW() - t.last_activity_at AS idle_duration
FROM tenants t
WHERE t.status = 'active'
AND t.last_activity_at < NOW() - INTERVAL '30 days'
ORDER BY t.last_activity_at ASC;

-- ============================================
-- STEP 7: Backfill tenant_id for existing data
-- ============================================
-- This creates tenant records for existing users and updates tenant_id
-- Run this after the migration to link existing data

-- Create tenants for existing unique user_ids in processed_documents
INSERT INTO tenants (user_id, status, created_at, last_activity_at)
SELECT DISTINCT
    user_id,
    'active',
    MIN(created_at),
    MAX(COALESCE(processed_at, created_at))
FROM processed_documents
WHERE user_id IS NOT NULL
GROUP BY user_id
ON CONFLICT (user_id) DO NOTHING;

-- Update tenant_id in processed_documents
UPDATE processed_documents pd
SET tenant_id = t.id
FROM tenants t
WHERE pd.user_id = t.user_id
AND pd.tenant_id IS NULL;

-- Update tenant_id in document_chunks
UPDATE document_chunks dc
SET tenant_id = t.id
FROM tenants t
WHERE dc.workspace_id IN (
    SELECT pd.workspace_id
    FROM processed_documents pd
    WHERE pd.user_id = t.user_id
)
AND dc.tenant_id IS NULL;

-- Create workspace_metadata for existing workspaces
INSERT INTO workspace_metadata (
    workspace_id,
    user_id,
    document_count,
    chunk_count,
    total_size_bytes,
    created_at
)
SELECT
    workspace_id,
    MIN(user_id) AS user_id,
    COUNT(*) AS document_count,
    SUM(chunk_count) AS chunk_count,
    SUM(size_bytes) AS total_size_bytes,
    MIN(created_at) AS created_at
FROM processed_documents
WHERE workspace_id IS NOT NULL
GROUP BY workspace_id
ON CONFLICT (workspace_id) DO UPDATE SET
    document_count = EXCLUDED.document_count,
    chunk_count = EXCLUDED.chunk_count,
    total_size_bytes = EXCLUDED.total_size_bytes,
    updated_at = NOW();

-- ============================================
-- VERIFICATION
-- ============================================
-- Show new table structures
SELECT
    'tenants' AS table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'tenants'
ORDER BY ordinal_position;

SELECT
    'workspace_metadata' AS table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'workspace_metadata'
ORDER BY ordinal_position;

-- Show tenant count
SELECT COUNT(*) AS tenant_count FROM tenants;
SELECT COUNT(*) AS workspace_count FROM workspace_metadata;
