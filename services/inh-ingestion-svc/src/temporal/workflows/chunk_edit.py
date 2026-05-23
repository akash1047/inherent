"""Temporal workflow for editing a single chunk.

Updates content in PostgreSQL (truth) and re-embeds in Weaviate (memory).
"""

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from src.temporal.models import ChunkEditInput, ChunkEditResult


@workflow.defn
class ChunkEditWorkflow:
    """Edit a single chunk's content across all stores."""

    @workflow.run
    async def run(self, input: ChunkEditInput) -> ChunkEditResult:
        # 1. Update PostgreSQL (authoritative)
        try:
            await workflow.execute_activity(
                "update_chunk_postgresql",
                input,
                start_to_close_timeout=timedelta(seconds=30),
            )
        except Exception as e:
            return ChunkEditResult(
                document_id=input.document_id,
                chunk_index=input.chunk_index,
                success=False,
                error=f"PostgreSQL update failed: {e}",
            )

        # 2. Update Weaviate (best-effort — PG is source of truth)
        try:
            await workflow.execute_activity(
                "update_chunk_weaviate",
                input,
                start_to_close_timeout=timedelta(seconds=60),
            )
        except Exception:
            pass  # Non-fatal — PG already updated

        return ChunkEditResult(
            document_id=input.document_id,
            chunk_index=input.chunk_index,
            success=True,
        )
