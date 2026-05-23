-- Migration 001: Consolidated Schema with Proper Relationships
-- This migration consolidates and improves the database schema
--
-- Changes:
-- 1. Drop legacy tables (documents, chunks) if not needed
-- 2. Add foreign key relationship between document_chunks and processed_documents
-- 3. Add missing columns and indexes
-- 4. Use proper ENUM types for status and storage_backend

-- ============================================
-- STEP 1: Drop legacy tables (if unused)
-- ============================================
-- Uncomment if you want to remove legacy tables
-- DROP TABLE IF EXISTS chunks CASCADE;
-- DROP TABLE IF EXISTS documents CASCADE;

-- ============================================
-- STEP 2: Create ENUM types (if not exist)
-- ============================================
DO $$
BEGIN
    -- Create document_status enum if not exists
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'document_status') THEN
        CREATE TYPE document_status AS ENUM ('pending', 'processing', 'processed', 'failed', 'deleted');
    END IF;

    -- Create storage_backend enum if not exists
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'storage_backend') THEN
        CREATE TYPE storage_backend AS ENUM ('local', 'gcs', 's3', 'azure');
    END IF;
END $$;

-- ============================================
-- STEP 3: Recreate processed_documents table with improvements
-- ============================================
-- First, backup existing data if needed
CREATE TABLE IF NOT EXISTS processed_documents_backup AS SELECT * FROM processed_documents;

-- Drop existing tables to recreate with proper structure
DROP TABLE IF EXISTS document_chunks CASCADE;
DROP TABLE IF EXISTS processed_documents CASCADE;

-- Create the parent table: processed_documents
CREATE TABLE processed_documents (
    -- Primary key (use BIGINT for scalability)
    id BIGSERIAL PRIMARY KEY,

    -- External reference from intg-svc (MongoDB ObjectId)
    document_id VARCHAR(100) NOT NULL UNIQUE,

    -- Ownership & Organization
    workspace_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,

    -- File Information
    filename VARCHAR(500) NOT NULL,
    original_filename VARCHAR(500) NOT NULL,
    content_type VARCHAR(100) NOT NULL,
    size_bytes BIGINT NOT NULL,

    -- Storage Information
    storage_backend VARCHAR(20) NOT NULL DEFAULT 'local',
    storage_path VARCHAR(1000) NOT NULL,
    storage_bucket VARCHAR(255),
    storage_url VARCHAR(2000),

    -- Processing Status
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_message TEXT,

    -- Processing Metrics
    chunk_count INTEGER DEFAULT 0,
    text_length INTEGER DEFAULT 0,
    processing_time_ms INTEGER DEFAULT 0,

    -- Extensible Metadata (JSONB for flexibility)
    metadata JSONB,

    -- Timestamps with timezone
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,

    -- Constraints
    CONSTRAINT chk_status CHECK (status IN ('pending', 'processing', 'processed', 'failed', 'deleted')),
    CONSTRAINT chk_storage_backend CHECK (storage_backend IN ('local', 'gcs', 's3', 'azure')),
    CONSTRAINT chk_size_bytes CHECK (size_bytes > 0)
);

-- Create indexes for common queries
CREATE INDEX idx_processed_documents_workspace_id ON processed_documents(workspace_id);
CREATE INDEX idx_processed_documents_user_id ON processed_documents(user_id);
CREATE INDEX idx_processed_documents_status ON processed_documents(status);
CREATE INDEX idx_processed_documents_content_type ON processed_documents(content_type);
CREATE INDEX idx_processed_documents_created_at ON processed_documents(created_at DESC);
CREATE INDEX idx_processed_documents_workspace_status ON processed_documents(workspace_id, status);

-- Partial index for pending/processing documents (for queue-like queries)
CREATE INDEX idx_processed_documents_pending ON processed_documents(created_at)
    WHERE status IN ('pending', 'processing');

-- ============================================
-- STEP 4: Create document_chunks table with proper FK
-- ============================================
CREATE TABLE document_chunks (
    -- Primary key
    id BIGSERIAL PRIMARY KEY,

    -- Foreign key to parent document (THE KEY RELATIONSHIP!)
    processed_document_id BIGINT NOT NULL
        REFERENCES processed_documents(id) ON DELETE CASCADE,

    -- Denormalized fields for query convenience (avoids JOINs for common queries)
    document_id VARCHAR(100) NOT NULL,
    workspace_id VARCHAR(100) NOT NULL,

    -- Chunk Information
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER,

    -- Position in original document
    start_char INTEGER DEFAULT 0,
    end_char INTEGER DEFAULT 0,

    -- Chunk metadata (page number, section, headers, etc.)
    metadata JSONB,

    -- Embedding vector (for semantic search without Weaviate)
    -- Uncomment if you want to store embeddings in PostgreSQL:
    -- embedding vector(384),  -- Requires pgvector extension

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Composite unique constraint: one chunk per index per document
    CONSTRAINT uq_document_chunks_doc_idx UNIQUE (processed_document_id, chunk_index),

    -- Ensure chunk_index is non-negative
    CONSTRAINT chk_chunk_index CHECK (chunk_index >= 0)
);

-- Create indexes for common queries
CREATE INDEX idx_document_chunks_processed_document_id ON document_chunks(processed_document_id);
CREATE INDEX idx_document_chunks_document_id ON document_chunks(document_id);
CREATE INDEX idx_document_chunks_workspace_id ON document_chunks(workspace_id);

-- Index for full-text search on content (optional)
-- CREATE INDEX idx_document_chunks_content_tsvector ON document_chunks USING GIN (to_tsvector('english', content));

-- ============================================
-- STEP 5: Restore data from backup (if applicable)
-- ============================================
-- Insert data back from backup
INSERT INTO processed_documents (
    document_id, workspace_id, user_id, filename, original_filename,
    content_type, size_bytes, storage_backend, storage_path, status,
    chunk_count, text_length, processing_time_ms, metadata, created_at, processed_at
)
SELECT
    document_id, workspace_id, user_id, filename, original_filename,
    content_type, size_bytes, storage_backend, storage_path, status,
    chunk_count, text_length, processing_time_ms, metadata,
    COALESCE(created_at, NOW()), processed_at
FROM processed_documents_backup
ON CONFLICT (document_id) DO NOTHING;

-- Drop backup table after successful migration
DROP TABLE IF EXISTS processed_documents_backup;

-- ============================================
-- STEP 6: Create helper functions
-- ============================================

-- Function to update updated_at timestamp automatically
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger to auto-update updated_at
DROP TRIGGER IF EXISTS trigger_processed_documents_updated_at ON processed_documents;
CREATE TRIGGER trigger_processed_documents_updated_at
    BEFORE UPDATE ON processed_documents
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- STEP 7: Create useful views
-- ============================================

-- View: Documents with chunk summary
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

-- View: Workspace statistics
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

-- ============================================
-- STEP 8: Grant permissions (adjust as needed)
-- ============================================
-- GRANT SELECT, INSERT, UPDATE, DELETE ON processed_documents TO your_app_user;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON document_chunks TO your_app_user;
-- GRANT USAGE, SELECT ON SEQUENCE processed_documents_id_seq TO your_app_user;
-- GRANT USAGE, SELECT ON SEQUENCE document_chunks_id_seq TO your_app_user;

-- ============================================
-- VERIFICATION
-- ============================================
-- Show table structures
SELECT
    tc.table_name,
    kcu.column_name,
    ccu.table_name AS foreign_table_name,
    ccu.column_name AS foreign_column_name
FROM
    information_schema.table_constraints AS tc
    JOIN information_schema.key_column_usage AS kcu
      ON tc.constraint_name = kcu.constraint_name
      AND tc.table_schema = kcu.table_schema
    JOIN information_schema.constraint_column_usage AS ccu
      ON ccu.constraint_name = tc.constraint_name
      AND ccu.table_schema = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY'
AND tc.table_schema = 'public';
