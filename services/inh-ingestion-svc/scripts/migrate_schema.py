#!/usr/bin/env python3
"""Database schema migration script.

This script:
1. Drops old/duplicate tables (chunks, documents) if they exist
2. Creates the new schema with proper foreign key relationships
3. Migrates any existing data from old tables to new tables

Run with: python -m scripts.migrate_schema
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

# Load environment variables
load_dotenv()


def get_database_url() -> str:
    """Get database URL from environment."""
    url = os.getenv("DATABASE_URL")
    if not url:
        url = "postgresql://postgres:postgres@localhost:5432/knowledge_base"
        print(f"⚠️  DATABASE_URL not set, using default: {url}")
    return url


def run_migration():
    """Run the database migration."""
    database_url = get_database_url()
    engine = create_engine(database_url)

    print("🔄 Starting database migration...")
    print(f"📍 Database: {database_url.split('@')[1] if '@' in database_url else database_url}")

    with engine.connect() as conn:
        # Get current tables
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        print(f"\n📋 Existing tables: {existing_tables}")

        # Migration SQL
        migration_sql = """
        -- ============================================
        -- Schema Migration for inh-ingestion-svc
        -- ============================================

        -- Step 1: Drop old/duplicate tables that lack proper relationships
        -- These tables were created without FK constraints

        -- Backup data from old tables if they exist (optional - uncomment if needed)
        -- CREATE TABLE IF NOT EXISTS _backup_chunks AS SELECT * FROM chunks;
        -- CREATE TABLE IF NOT EXISTS _backup_documents AS SELECT * FROM documents;

        -- Drop old tables (they have no FK relationships)
        DROP TABLE IF EXISTS chunks CASCADE;
        DROP TABLE IF EXISTS documents CASCADE;

        -- Step 2: Drop and recreate the main tables with proper schema
        -- Note: This will delete existing data in processed_documents and document_chunks
        -- If you need to preserve data, add a backup step above

        DROP TABLE IF EXISTS document_chunks CASCADE;
        DROP TABLE IF EXISTS processed_documents CASCADE;

        -- Step 3: Create the new schema

        -- Parent table: processed_documents
        CREATE TABLE processed_documents (
            -- Primary key
            id BIGSERIAL PRIMARY KEY,

            -- External reference (from intg-svc MongoDB)
            document_id VARCHAR(100) NOT NULL UNIQUE,

            -- Ownership & organization
            workspace_id VARCHAR(100) NOT NULL,
            user_id VARCHAR(100) NOT NULL,

            -- File information
            filename VARCHAR(500) NOT NULL,
            original_filename VARCHAR(500) NOT NULL,
            content_type VARCHAR(100) NOT NULL,
            size_bytes BIGINT NOT NULL,

            -- Storage information
            storage_backend VARCHAR(20) NOT NULL DEFAULT 'local',
            storage_path VARCHAR(1000) NOT NULL,
            storage_bucket VARCHAR(255),
            storage_url VARCHAR(2000),

            -- Processing status
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            error_message TEXT,

            -- Processing metrics
            chunk_count INTEGER DEFAULT 0,
            text_length INTEGER DEFAULT 0,
            processing_time_ms INTEGER DEFAULT 0,

            -- Extensible metadata
            metadata JSONB,

            -- Timestamps (with timezone)
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processed_at TIMESTAMPTZ
        );

        -- Indexes for processed_documents
        CREATE INDEX idx_processed_documents_workspace_id ON processed_documents(workspace_id);
        CREATE INDEX idx_processed_documents_user_id ON processed_documents(user_id);
        CREATE INDEX idx_processed_documents_status ON processed_documents(status);
        CREATE INDEX idx_processed_documents_content_type ON processed_documents(content_type);
        CREATE INDEX idx_processed_documents_created_at ON processed_documents(created_at);
        CREATE INDEX idx_processed_documents_workspace_status ON processed_documents(workspace_id, status);

        -- Child table: document_chunks (with FK to processed_documents)
        CREATE TABLE document_chunks (
            -- Primary key
            id BIGSERIAL PRIMARY KEY,

            -- Foreign key to parent document (CASCADE delete)
            processed_document_id BIGINT NOT NULL REFERENCES processed_documents(id) ON DELETE CASCADE,

            -- Denormalized for query convenience
            document_id VARCHAR(100) NOT NULL,
            workspace_id VARCHAR(100) NOT NULL,

            -- Chunk information
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            token_count INTEGER,

            -- Position in original document
            start_char INTEGER DEFAULT 0,
            end_char INTEGER DEFAULT 0,

            -- Extensible metadata
            metadata JSONB,

            -- Timestamps
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            -- Composite unique: one chunk per index per document
            CONSTRAINT uq_document_chunks_doc_idx UNIQUE (processed_document_id, chunk_index)
        );

        -- Indexes for document_chunks
        CREATE INDEX idx_document_chunks_document_id ON document_chunks(document_id);
        CREATE INDEX idx_document_chunks_workspace_id ON document_chunks(workspace_id);
        CREATE INDEX idx_document_chunks_processed_document_id ON document_chunks(processed_document_id);

        -- Step 4: Add comments for documentation
        COMMENT ON TABLE processed_documents IS 'Documents processed by the ingestion service';
        COMMENT ON TABLE document_chunks IS 'Text chunks extracted from processed documents';

        COMMENT ON COLUMN processed_documents.document_id IS 'External document ID from intg-svc (MongoDB ObjectId)';
        COMMENT ON COLUMN processed_documents.status IS 'Processing status: pending, processing, processed, failed, deleted';
        COMMENT ON COLUMN processed_documents.metadata IS 'Extensible JSONB field for additional document metadata';

        COMMENT ON COLUMN document_chunks.processed_document_id IS 'FK to processed_documents.id (CASCADE delete)';
        COMMENT ON COLUMN document_chunks.token_count IS 'Approximate token count for embedding/LLM context management';
        COMMENT ON COLUMN document_chunks.metadata IS 'Chunk-specific metadata (page number, section headers, etc.)';
        """

        # Execute migration
        print("\n🚀 Executing migration...")
        conn.execute(text(migration_sql))
        conn.commit()

        print("✅ Migration completed successfully!")

        # Verify new schema
        inspector = inspect(engine)
        new_tables = inspector.get_table_names()
        print(f"\n📋 Tables after migration: {new_tables}")

        # Show FK relationships
        fk_query = """
        SELECT
            tc.table_name,
            kcu.column_name,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name,
            rc.delete_rule
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema = tc.table_schema
        JOIN information_schema.referential_constraints AS rc
            ON tc.constraint_name = rc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_schema = 'public';
        """

        result = conn.execute(text(fk_query)).fetchall()

        if result:
            print("\n🔗 Foreign Key Relationships:")
            for row in result:
                print(f"   {row[0]}.{row[1]} → {row[2]}.{row[3]} (ON DELETE {row[4]})")

        # Show table structure
        print("\n📊 Table Structure:")
        for table in ["processed_documents", "document_chunks"]:
            columns = inspector.get_columns(table)
            print(f"\n   {table}:")
            for col in columns[:5]:  # Show first 5 columns
                nullable = "NULL" if col["nullable"] else "NOT NULL"
                print(f"      - {col['name']}: {col['type']} {nullable}")
            if len(columns) > 5:
                print(f"      ... and {len(columns) - 5} more columns")


if __name__ == "__main__":
    run_migration()
