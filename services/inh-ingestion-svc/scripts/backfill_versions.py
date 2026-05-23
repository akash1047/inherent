#!/usr/bin/env python3
"""Backfill existing documents as version 1 in the new versioning system.

This script migrates data from:
- processed_documents → document_versions (as version 1)
- document_chunks → version_chunks

Run with: python -m scripts.backfill_versions
Or: uv run python -m scripts.backfill_versions
Or via Docker: docker exec -i postgres-local psql -U postgres -d knowledge_base < scripts/backfill_versions.sql
"""

import hashlib
import os
import sys
import uuid

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load environment variables
load_dotenv()


def get_database_url() -> str:
    """Get database URL from environment or use local default."""
    # Force local database for backfill
    return "postgresql://postgres:postgres@localhost:5432/knowledge_base"


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of content."""
    normalized = content.strip().replace("\r\n", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def run_backfill():
    """Run the backfill process."""
    database_url = get_database_url()
    engine = create_engine(database_url)

    print("Starting document versioning backfill...")
    print(f"Database: localhost:5432/knowledge_base")

    with engine.connect() as conn:
        # Check if any versions already exist
        existing_versions = conn.execute(
            text("SELECT COUNT(*) FROM document_versions")
        ).fetchone()[0]

        if existing_versions > 0:
            print(f"\nWarning: {existing_versions} versions already exist.")
            response = input("Continue backfill? (y/N): ")
            if response.lower() != "y":
                print("Backfill cancelled.")
                return

        # Get documents to backfill
        docs_query = """
        SELECT
            pd.id,
            pd.document_id,
            pd.workspace_id,
            pd.user_id,
            pd.tenant_id,
            pd.chunk_count,
            pd.text_length,
            pd.size_bytes,
            pd.storage_backend,
            pd.storage_path,
            pd.storage_bucket,
            pd.created_at,
            pd.processing_time_ms
        FROM processed_documents pd
        WHERE pd.status = 'processed'
          AND NOT EXISTS (
              SELECT 1 FROM document_versions dv
              WHERE dv.document_id = pd.document_id
          )
        ORDER BY pd.id
        """

        docs = conn.execute(text(docs_query)).fetchall()
        print(f"\nDocuments to backfill: {len(docs)}")

        if not docs:
            print("No documents to backfill.")
            return

        # Process each document
        backfilled = 0
        errors = []

        for doc in docs:
            doc_id = doc[1]  # document_id
            try:
                # Get chunks for this document to compute content hash
                chunks_query = """
                SELECT content, chunk_index
                FROM document_chunks
                WHERE document_id = :doc_id
                ORDER BY chunk_index
                """
                chunks = conn.execute(
                    text(chunks_query), {"doc_id": doc_id}
                ).fetchall()

                # Compute content hash from all chunks
                full_content = "\n".join([c[0] for c in chunks])
                content_hash = compute_content_hash(full_content)

                # Generate version_id
                version_id = f"ver_{uuid.uuid4().hex}"

                # Insert into document_versions
                insert_version = """
                INSERT INTO document_versions (
                    version_id,
                    document_id,
                    version_number,
                    workspace_id,
                    user_id,
                    tenant_id,
                    status,
                    is_active,
                    content_hash,
                    chunk_count,
                    text_length,
                    size_bytes,
                    processing_time_ms,
                    storage_backend,
                    storage_path,
                    storage_bucket,
                    change_type,
                    change_summary,
                    created_by,
                    created_at,
                    effective_from
                ) VALUES (
                    :version_id,
                    :document_id,
                    1,
                    :workspace_id,
                    :user_id,
                    :tenant_id,
                    'current',
                    TRUE,
                    :content_hash,
                    :chunk_count,
                    :text_length,
                    :size_bytes,
                    :processing_time_ms,
                    :storage_backend,
                    :storage_path,
                    :storage_bucket,
                    'initial',
                    'Backfilled from existing document',
                    :user_id,
                    :created_at,
                    :created_at
                )
                RETURNING id
                """

                result = conn.execute(
                    text(insert_version),
                    {
                        "version_id": version_id,
                        "document_id": doc_id,
                        "workspace_id": doc[2],
                        "user_id": doc[3],
                        "tenant_id": doc[4],
                        "chunk_count": doc[5] or 0,
                        "text_length": doc[6] or 0,
                        "size_bytes": doc[7],
                        "processing_time_ms": doc[12] or 0,
                        "storage_backend": doc[8],
                        "storage_path": doc[9],
                        "storage_bucket": doc[10],
                        "created_at": doc[11],
                    },
                ).fetchone()

                version_internal_id = result[0]

                # Copy chunks to version_chunks
                if chunks:
                    for chunk in chunks:
                        chunk_content = chunk[0]
                        chunk_index = chunk[1]
                        chunk_hash = compute_content_hash(chunk_content)

                        insert_chunk = """
                        INSERT INTO version_chunks (
                            version_id,
                            document_id,
                            workspace_id,
                            version_number,
                            chunk_index,
                            content,
                            content_hash,
                            token_count,
                            created_at
                        )
                        SELECT
                            :version_id,
                            dc.document_id,
                            dc.workspace_id,
                            1,
                            dc.chunk_index,
                            dc.content,
                            :content_hash,
                            dc.token_count,
                            dc.created_at
                        FROM document_chunks dc
                        WHERE dc.document_id = :doc_id
                          AND dc.chunk_index = :chunk_index
                        """

                        conn.execute(
                            text(insert_chunk),
                            {
                                "version_id": version_internal_id,
                                "doc_id": doc_id,
                                "chunk_index": chunk_index,
                                "content_hash": chunk_hash,
                            },
                        )

                backfilled += 1
                print(f"  Backfilled: {doc_id} ({len(chunks)} chunks)")

            except Exception as e:
                errors.append((doc_id, str(e)))
                print(f"  Error: {doc_id}: {str(e)[:50]}")

        conn.commit()

        print(f"\nBackfill complete!")
        print(f"  Successfully backfilled: {backfilled}")
        print(f"  Errors: {len(errors)}")

        if errors:
            print("\nErrors:")
            for doc_id, err in errors:
                print(f"  {doc_id}: {err}")

        # Verify results
        version_count = conn.execute(
            text("SELECT COUNT(*) FROM document_versions")
        ).fetchone()[0]
        chunk_count = conn.execute(
            text("SELECT COUNT(*) FROM version_chunks")
        ).fetchone()[0]

        print(f"\nVersioning tables now contain:")
        print(f"  document_versions: {version_count} rows")
        print(f"  version_chunks: {chunk_count} rows")


if __name__ == "__main__":
    run_backfill()
