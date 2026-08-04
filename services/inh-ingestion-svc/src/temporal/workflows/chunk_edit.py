"""Temporal workflow for editing a single chunk.

Updates content in PostgreSQL (truth) and re-embeds in Weaviate (memory).
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from src.temporal.models import ChunkEditInput, ChunkEditResult, ChunkEditWeaviateFailureInput


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

        # 2. Update Weaviate. PG already holds the NEW content at this
        # point, so a Weaviate failure here is a PG/vector divergence
        # (#137), not a cosmetic miss: semantic search would keep matching
        # the OLD text/vector indefinitely with no signal to anyone. Bounded
        # retries (matching store_in_weaviate's policy) give a transient
        # TEI/Weaviate hiccup a chance to clear. update_chunk_weaviate
        # re-raises on failure (it used to swallow into `return False`,
        # which is a *completed* activity to Temporal -- the RetryPolicy
        # below never got to run at all).
        try:
            await workflow.execute_activity(
                "update_chunk_weaviate",
                input,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=2),
                    maximum_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0,
                ),
            )
        except Exception as e:
            error_message = (
                f"PostgreSQL updated but the Weaviate re-embed failed after "
                f"retries: {e}. Search results for this chunk may return "
                "stale content/vector until a retry succeeds."
            )

            # Compensating "mark-failed" (#137): a durable, queryable signal
            # (GET /lineage/{document_id}) that this divergence exists, so
            # it's discoverable even if the caller doesn't act on the 5xx
            # this workflow is about to report. Routed through an explicit
            # bounded RetryPolicy -- never a bare call -- and this
            # recording's own failure is logged-and-swallowed by the
            # activity itself so it can't mask the real error returned below
            # (#99: the compensation is itself fallible).
            try:
                await workflow.execute_activity(
                    "record_chunk_edit_weaviate_failure",
                    ChunkEditWeaviateFailureInput(
                        workflow_id=workflow.info().workflow_id,
                        document_id=input.document_id,
                        workspace_id=input.workspace_id,
                        chunk_index=input.chunk_index,
                        error_message=str(e),
                    ),
                    start_to_close_timeout=timedelta(seconds=10),
                    retry_policy=RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(seconds=1),
                        maximum_interval=timedelta(seconds=3),
                    ),
                )
            except Exception as record_err:
                # The activity itself never raises (see its docstring); this
                # only catches a Temporal-level dispatch failure. Log, don't
                # mask the real error below.
                workflow.logger.error(
                    f"Failed to record chunk-edit failure lineage event: {record_err}"
                )

            return ChunkEditResult(
                document_id=input.document_id,
                chunk_index=input.chunk_index,
                success=False,
                error=error_message,
            )

        return ChunkEditResult(
            document_id=input.document_id,
            chunk_index=input.chunk_index,
            success=True,
        )
