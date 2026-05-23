"""Activities for editing individual chunks in PostgreSQL and Weaviate."""

import structlog
from temporalio import activity

from src.temporal.models import ChunkEditInput

logger = structlog.get_logger(__name__)


@activity.defn
async def update_chunk_postgresql(input: ChunkEditInput) -> bool:
    """Update a single chunk's content in PostgreSQL.

    Also recalculates token_count based on the new content.
    """
    from sqlalchemy import text as sa_text

    from src.temporal.shared_services import get_db_service

    db = get_db_service()
    token_count = len(input.content.split())

    with db.engine.connect() as conn:
        result = conn.execute(
            sa_text(
                "UPDATE document_chunks "
                "SET content = :content, token_count = :token_count "
                "WHERE document_id = :doc_id AND chunk_index = :idx"
            ),
            {
                "content": input.content,
                "token_count": token_count,
                "doc_id": input.document_id,
                "idx": input.chunk_index,
            },
        )
        conn.commit()

    if result.rowcount == 0:
        raise RuntimeError(f"Chunk {input.chunk_index} not found for document {input.document_id}")

    logger.info(
        "Updated chunk in PostgreSQL",
        document_id=input.document_id,
        chunk_index=input.chunk_index,
        token_count=token_count,
    )
    return True


@activity.defn
async def update_chunk_weaviate(input: ChunkEditInput) -> bool:
    """Update a single chunk's content and embedding in Weaviate.

    Re-embeds the new content so semantic search stays accurate.
    """
    from src.temporal.shared_services import get_weaviate_service

    weaviate_service = get_weaviate_service()

    if weaviate_service is None or not weaviate_service.is_connected():
        logger.warning("Weaviate not connected, skipping chunk update")
        return False

    try:
        await weaviate_service.update_chunk(
            document_id=input.document_id,
            chunk_index=input.chunk_index,
            content=input.content,
            workspace_id=input.workspace_id,
            user_id=input.user_id,
        )
        logger.info(
            "Updated chunk in Weaviate",
            document_id=input.document_id,
            chunk_index=input.chunk_index,
        )
        return True
    except Exception as e:
        logger.error(
            "Failed to update chunk in Weaviate (non-fatal)",
            document_id=input.document_id,
            chunk_index=input.chunk_index,
            error=str(e),
        )
        return False
