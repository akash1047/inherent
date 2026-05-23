-- Migration 003: API Keys Table (User-Scoped)
-- This migration creates the api_keys table with user-scoped design
--
-- Design:
-- - API keys are user-scoped (workspace_id is nullable)
-- - Users have one API key that works across all their workspaces
-- - MCP service determines accessible workspaces at runtime
-- - Cross-workspace search becomes possible with a single key
--
-- Security:
-- - Keys are stored as SHA-256 hashes
-- - Only key prefix is stored for display
-- - Supports permissions, rate limiting, and expiration

-- ============================================
-- STEP 1: Create api_keys table
-- ============================================
CREATE TABLE IF NOT EXISTS api_keys (
    id BIGSERIAL PRIMARY KEY,

    -- Key identifiers
    key_id VARCHAR(100) NOT NULL UNIQUE,       -- UUID for external reference
    key_hash VARCHAR(64) NOT NULL UNIQUE,       -- SHA-256 hash of the key
    key_prefix VARCHAR(20) NOT NULL,            -- First chars for display (e.g., "ink_abc1...")

    -- Ownership
    user_id VARCHAR(100) NOT NULL,              -- User who owns this key
    workspace_id VARCHAR(100) DEFAULT NULL,     -- NULL = user-scoped (works across all workspaces)

    -- Key metadata
    name VARCHAR(255) NOT NULL,                 -- User-friendly name
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    permissions JSONB NOT NULL DEFAULT '["read", "search"]',
    rate_limit INTEGER NOT NULL DEFAULT 100,

    -- Timestamps
    expires_at TIMESTAMPTZ DEFAULT NULL,
    last_used_at TIMESTAMPTZ DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT chk_api_key_status CHECK (status IN ('active', 'revoked')),
    CONSTRAINT chk_rate_limit_positive CHECK (rate_limit > 0)
);

-- ============================================
-- STEP 2: Create indexes
-- ============================================
-- Index for looking up keys by hash (used during validation)
CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);

-- Index for listing user's keys
CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);

-- Index for finding active keys
CREATE INDEX IF NOT EXISTS idx_api_keys_status ON api_keys(status);

-- Index for finding expired keys (for cleanup jobs)
CREATE INDEX IF NOT EXISTS idx_api_keys_expires_at ON api_keys(expires_at) WHERE expires_at IS NOT NULL;

-- ============================================
-- STEP 3: Create trigger for updated_at
-- ============================================
CREATE OR REPLACE FUNCTION update_api_keys_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_api_keys_updated_at ON api_keys;
CREATE TRIGGER trigger_api_keys_updated_at
    BEFORE UPDATE ON api_keys
    FOR EACH ROW
    EXECUTE FUNCTION update_api_keys_updated_at();

-- ============================================
-- VERIFICATION
-- ============================================
SELECT
    column_name,
    is_nullable,
    data_type
FROM information_schema.columns
WHERE table_name = 'api_keys'
ORDER BY ordinal_position;

-- Show table structure
SELECT 'api_keys table created successfully' AS status;
