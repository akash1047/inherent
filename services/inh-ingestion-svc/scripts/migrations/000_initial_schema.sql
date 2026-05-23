-- Initial Schema for Cloud SQL (Fresh Database)
-- Combined schema from migrations 001, 002, and 003

-- ============================================
-- STEP 1: Create ENUM types
-- ============================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'document_status') THEN
        CREATE TYPE document_status AS ENUM ('pending', 'processing', 'processed', 'failed', 'deleted');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'storage_backend') THEN
        CREATE TYPE storage_backend AS ENUM ('local', 'gcs', 's3', 'azure');
    END IF;
END $$;

-- ============================================
-- STEP 2: Create tenants table
-- ============================================
CREATE TABLE IF NOT EXISTS tenants (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB DEFAULT '{}',
    CONSTRAINT chk_tenant_status CHECK (status IN ('active', 'inactive', 'suspended'))
);

CREATE INDEX IF NOT EXISTS idx_tenants_status ON tenants(status);
CREATE INDEX IF NOT EXISTS idx_tenants_last_activity ON tenants(last_activity_at);

-- ============================================
-- STEP 3: Create workspace_metadata table
-- ============================================
CREATE TABLE IF NOT EXISTS workspace_metadata (
    id BIGSERIAL PRIMARY KEY,
    workspace_id VARCHAR(100) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,
    weaviate_collection VARCHAR(200),
    document_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    total_size_bytes BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_workspace_metadata_user_id ON workspace_metadata(user_id);

-- ============================================
-- STEP 4: Create processed_documents table
-- ============================================
CREATE TABLE IF NOT EXISTS processed_documents (
    id BIGSERIAL PRIMARY KEY,
    document_id VARCHAR(100) NOT NULL UNIQUE,
    workspace_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    tenant_id BIGINT,
    filename VARCHAR(500) NOT NULL,
    original_filename VARCHAR(500) NOT NULL,
    content_type VARCHAR(100) NOT NULL,
    size_bytes BIGINT NOT NULL,
    storage_backend VARCHAR(20) NOT NULL DEFAULT 'local',
    storage_path VARCHAR(1000) NOT NULL,
    storage_bucket VARCHAR(255),
    storage_url VARCHAR(2000),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_message TEXT,
    chunk_count INTEGER DEFAULT 0,
    text_length INTEGER DEFAULT 0,
    processing_time_ms INTEGER DEFAULT 0,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    CONSTRAINT chk_status CHECK (status IN ('pending', 'processing', 'processed', 'failed', 'deleted')),
    CONSTRAINT chk_storage_backend CHECK (storage_backend IN ('local', 'gcs', 's3', 'azure')),
    CONSTRAINT chk_size_bytes CHECK (size_bytes > 0)
);

CREATE INDEX IF NOT EXISTS idx_processed_documents_workspace_id ON processed_documents(workspace_id);
CREATE INDEX IF NOT EXISTS idx_processed_documents_user_id ON processed_documents(user_id);
CREATE INDEX IF NOT EXISTS idx_processed_documents_tenant_id ON processed_documents(tenant_id);
CREATE INDEX IF NOT EXISTS idx_processed_documents_status ON processed_documents(status);
CREATE INDEX IF NOT EXISTS idx_processed_documents_content_type ON processed_documents(content_type);
CREATE INDEX IF NOT EXISTS idx_processed_documents_created_at ON processed_documents(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_processed_documents_workspace_status ON processed_documents(workspace_id, status);
CREATE INDEX IF NOT EXISTS idx_processed_documents_tenant_workspace ON processed_documents(tenant_id, workspace_id);

-- ============================================
-- STEP 5: Create document_chunks table
-- ============================================
CREATE TABLE IF NOT EXISTS document_chunks (
    id BIGSERIAL PRIMARY KEY,
    processed_document_id BIGINT NOT NULL REFERENCES processed_documents(id) ON DELETE CASCADE,
    document_id VARCHAR(100) NOT NULL,
    workspace_id VARCHAR(100) NOT NULL,
    tenant_id BIGINT,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER,
    start_char INTEGER DEFAULT 0,
    end_char INTEGER DEFAULT 0,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_document_chunks_doc_idx UNIQUE (processed_document_id, chunk_index),
    CONSTRAINT chk_chunk_index CHECK (chunk_index >= 0)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_processed_document_id ON document_chunks(processed_document_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_workspace_id ON document_chunks(workspace_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_tenant_id ON document_chunks(tenant_id);

-- ============================================
-- STEP 6: Create api_keys table
-- ============================================
CREATE TABLE IF NOT EXISTS api_keys (
    id BIGSERIAL PRIMARY KEY,
    key_id VARCHAR(100) NOT NULL UNIQUE,
    key_hash VARCHAR(64) NOT NULL UNIQUE,
    key_prefix VARCHAR(20) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    workspace_id VARCHAR(100) DEFAULT NULL,
    name VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    permissions JSONB NOT NULL DEFAULT '["read", "search"]',
    rate_limit INTEGER NOT NULL DEFAULT 100,
    expires_at TIMESTAMPTZ DEFAULT NULL,
    last_used_at TIMESTAMPTZ DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB DEFAULT '{}',
    CONSTRAINT chk_api_key_status CHECK (status IN ('active', 'revoked')),
    CONSTRAINT chk_rate_limit_positive CHECK (rate_limit > 0)
);

CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_status ON api_keys(status);
CREATE INDEX IF NOT EXISTS idx_api_keys_expires_at ON api_keys(expires_at) WHERE expires_at IS NOT NULL;

-- ============================================
-- STEP 7: Create helper functions
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for auto-updating updated_at
DROP TRIGGER IF EXISTS trigger_processed_documents_updated_at ON processed_documents;
CREATE TRIGGER trigger_processed_documents_updated_at
    BEFORE UPDATE ON processed_documents
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trigger_tenants_updated_at ON tenants;
CREATE TRIGGER trigger_tenants_updated_at
    BEFORE UPDATE ON tenants
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trigger_workspace_metadata_updated_at ON workspace_metadata;
CREATE TRIGGER trigger_workspace_metadata_updated_at
    BEFORE UPDATE ON workspace_metadata
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trigger_api_keys_updated_at ON api_keys;
CREATE TRIGGER trigger_api_keys_updated_at
    BEFORE UPDATE ON api_keys
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Helper functions
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

-- ============================================
-- STEP 8: Create views
-- ============================================
CREATE OR REPLACE VIEW v_documents_summary AS
SELECT
    pd.id,
    pd.document_id,
    pd.workspace_id,
    pd.user_id,
    pd.original_filename,
    pd.content_type,
    pd.size_bytes,
    pd.status,
    pd.chunk_count,
    pd.text_length,
    pd.processing_time_ms,
    pd.created_at,
    pd.processed_at,
    COALESCE(
        (SELECT SUM(LENGTH(content)) FROM document_chunks dc WHERE dc.processed_document_id = pd.id),
        0
    ) as actual_content_length
FROM processed_documents pd;

CREATE OR REPLACE VIEW v_workspace_stats AS
SELECT
    workspace_id,
    COUNT(*) as total_documents,
    SUM(CASE WHEN status = 'processed' THEN 1 ELSE 0 END) as processed_documents,
    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending_documents,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_documents,
    SUM(COALESCE(chunk_count, 0)) as total_chunks,
    SUM(COALESCE(size_bytes, 0)) as total_size_bytes,
    AVG(COALESCE(processing_time_ms, 0)) as avg_processing_time_ms
FROM processed_documents
GROUP BY workspace_id;

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

-- ============================================
-- STEP 9: Grant permissions to ingestion_user
-- ============================================
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ingestion_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ingestion_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO ingestion_user;

-- Verification
SELECT 'Schema created successfully' AS status;
SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;
