"""Activities for editing individual chunks in PostgreSQL and Weaviate."""

import structlog
from temporalio import activity

from src.temporal.models import ChunkEditInput, ChunkEditWeaviateFailureInput

logger = structlog.get_logger(__name__)


@activity.defn
async def update_chunk_postgresql(input: ChunkEditInput) -> bool:
    """Update a single chunk's content in PostgreSQL.

    Recomputes ``token_count`` (with the same estimator as the store path) and
    ``content_hash`` so the #41 verifiable-evidence hash stays consistent with
    the edited content instead of flagging the chunk as tampered (#9).
    """
    import hashlib

    from sqlalchemy import text as sa_text

    from src.temporal.activities.chunk import estimate_tokens
    from src.temporal.shared_services import get_db_service

    db = get_db_service()
    token_count = estimate_tokens(input.content)
    content_hash = hashlib.sha256(input.content.encode("utf-8")).hexdigest()

    with db.engine.connect() as conn:
        result = conn.execute(
            sa_text(
                "UPDATE document_chunks "
                "SET content = :content, token_count = :token_count, "
                "content_hash = :content_hash "
                "WHERE document_id = :doc_id AND chunk_index = :idx"
            ),
            {
                "content": input.content,
                "token_count": token_count,
                "content_hash": content_hash,
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

    Re-raises on any failure (#137 follow-up) instead of catching and
    returning False. A Temporal activity that *returns* is reported as
    complete -- catching the error here meant the workflow's RetryPolicy
    never engaged (a transient TEI-sidecar restart or Weaviate hiccup got no
    retry) AND the workflow fell through to success=True, so the caller was
    told the edit succeeded while the vector silently stayed stale
    indefinitely. Mirrors store_in_weaviate's re-raise fix for the initial
    ingestion path (see CHANGELOG's "Durable ingestion" entry) -- this was
    the same defect on the edit path.
    """
    from src.temporal.shared_services import get_weaviate_service

    weaviate_service = get_weaviate_service()

    if weaviate_service is None or not weaviate_service.is_connected():
        # A not-connected Weaviate is often a transient reconnect window --
        # raise so the workflow's RetryPolicy gets a shot before the caller
        # is told the edit failed (same reasoning as store_in_weaviate).
        raise RuntimeError("Weaviate not connected")

    try:
        await weaviate_service.update_chunk(
            document_id=input.document_id,
            chunk_index=input.chunk_index,
            content=input.content,
            workspace_id=input.workspace_id,
            user_id=input.user_id,
        )
    except Exception as e:
        logger.error(
            "Failed to update chunk in Weaviate",
            document_id=input.document_id,
            chunk_index=input.chunk_index,
            error=str(e),
        )
        raise

    logger.info(
        "Updated chunk in Weaviate",
        document_id=input.document_id,
        chunk_index=input.chunk_index,
    )
    return True


@activity.defn
async def record_chunk_edit_weaviate_failure(input: ChunkEditWeaviateFailureInput) -> bool:
    """Record a terminal chunk-edit-to-Weaviate failure as an ingestion event.

    This is the compensating "mark-failed" signal (#137) for a chunk edit
    whose PostgreSQL write succeeded but whose Weaviate re-embed did not,
    even after the workflow's RetryPolicy is exhausted: a durable, queryable
    row (GET /lineage/{document_id}) recording the PG/vector divergence, so
    it isn't only visible as a one-shot HTTP 5xx the caller may not persist.

    Best-effort and MUST NOT raise: recording this signal is itself fallible
    (#99), and a failure to record it must never mask -- or be conflated
    with -- the real Weaviate error the workflow already captured and is
    about to return to the caller. The workflow still routes this through an
    explicit bounded RetryPolicy rather than calling it bare, so a transient
    DB hiccup gets a couple of chances before we give up on recording it.
    """
    from src.temporal.shared_services import get_db_service

    try:
        db_service = get_db_service()
        await db_service.record_ingestion_event(
            workflow_run_id=input.workflow_id,
            document_id=input.document_id,
            workspace_id=input.workspace_id,
            event_type="chunk_edit_weaviate",
            status="failed",
            metadata={"chunk_index": input.chunk_index, "error": input.error_message},
        )
        return True
    except Exception as e:
        logger.warning(
            "Failed to record chunk-edit failure lineage event (non-fatal)",
            document_id=input.document_id,
            chunk_index=input.chunk_index,
            error=str(e),
        )
        return False
