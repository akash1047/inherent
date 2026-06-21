"""Search endpoint."""

import asyncio
import time
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header

from src.config import settings
from src.models.search import SearchRequest, SearchResponse, SearchResult
from src.services.audit_publisher import build_audit_event, publish_audit_event
from src.services.auth import ResolvedAuth, resolve_workspace_search
from src.services.database import get_database
from src.services.search import SearchService, get_search_service
from src.utils import get_logger

router = APIRouter()
logger = get_logger(__name__)


def _build_result_snippets(results: list[SearchResult]) -> list[dict]:
    """Extract top-5 result snippets for the audit event."""
    snippets = []
    for r in results[:5]:
        snippets.append(
            {
                "document_id": r.document_id,
                "filename": r.document_name,
                "snippet": r.content,
                "score": r.score,
                "chunk_index": r.metadata.get("chunk_index") if r.metadata else None,
            }
        )
    return snippets


def _compute_total_tokens(results: list[SearchResult]) -> int:
    """Sum token_count across all matched chunks and their context neighbours."""
    total = 0
    missing = 0
    for r in results:
        tc = (r.metadata or {}).get("token_count")
        if isinstance(tc, int):
            total += tc
        else:
            missing += 1
        for ctx in list(r.context_before or []) + list(r.context_after or []):
            if ctx.token_count:
                total += ctx.token_count
            else:
                missing += 1
    if missing:
        try:
            from src.services.metrics import record_search_chunks_missing_token_count

            record_search_chunks_missing_token_count(missing)
        except Exception as exc:
            logger.debug(
                "search_metric_record_failed", metric="missing_token_count", error=str(exc)
            )
    return total


def _record_search_metrics(request: SearchRequest, workspace_id: str | None) -> None:
    """Increment Prometheus counters for the search request. Best-effort."""
    try:
        from src.services.metrics import record_search_context_request, record_search_request

        record_search_request(
            mode=request.search_mode,
            workspace_id=workspace_id if workspace_id else "multi",
        )
        if request.include_context:
            record_search_context_request(k=request.context_window)
    except Exception as exc:
        logger.debug("search_metric_record_failed", metric="search_request", error=str(exc))


def _schedule_audit(
    background_tasks: BackgroundTasks,
    *,
    auth: ResolvedAuth,
    request: SearchRequest,
    response: SearchResponse,
    source: str,
    workspace_id: str,
) -> None:
    """Build and schedule an audit event for fire-and-forget publishing."""
    event = build_audit_event(
        workspace_id=workspace_id,
        user_id=auth.key_info.user_id,
        api_key_id=auth.key_info.key_id,
        source=source,
        query_type="search",
        query_text=request.query,
        query_filters={"document_ids": request.document_ids} if request.document_ids else None,
        result_count=response.total_results,
        result_snippets=_build_result_snippets(response.results),
        response_time_ms=response.processing_time_ms,
        # PM-S018 / PM-S019 — search mode & context metadata
        search_mode=request.search_mode,
        include_context=request.include_context,
        context_window=request.context_window,
        alpha=request.alpha,
    )
    background_tasks.add_task(publish_audit_event, event)


async def _expand_context_and_total_tokens(
    response: SearchResponse,
    request: SearchRequest,
    ctx_workspace_id: str,
) -> None:
    """Expand context windows (if requested) and set response.total_tokens.

    Mutates *response* in-place.  Best-effort: if the context fetch fails the
    error is swallowed inside ContextWindowBuilder.expand(); total_tokens is
    still computed from whatever data is available.
    """
    if request.include_context and response.results and ctx_workspace_id:
        from src.services.context_window import ContextWindowBuilder

        database = await get_database()
        builder = ContextWindowBuilder(database)
        await builder.expand(
            matches=response.results,
            workspace_id=ctx_workspace_id,
            k=request.context_window,
        )
    response.total_tokens = _compute_total_tokens(response.results)


async def _search_workspaces_concurrently(
    search_service: SearchService,
    *,
    user_id: str,
    workspace_ids: list[str],
    request: SearchRequest,
) -> tuple[list[SearchResult], float]:
    """Fan out a search across the user's authorised workspaces (#13).

    Behaviour:
    - The query embedding is computed ONCE and reused across every workspace,
      instead of re-embedding per workspace.
    - Workspaces are searched concurrently with ``asyncio.gather`` bounded by an
      ``asyncio.Semaphore`` sized from ``search_max_workspace_concurrency`` so a
      user with many workspaces cannot exhaust the Weaviate connection pool.
    - Per-workspace failure isolation (partial-result policy): if one workspace
      search raises, the error is logged and that workspace contributes zero
      results; the remaining workspaces still return. The request only fails if
      every workspace fails in a way that is surfaced here — single failures
      degrade to partial results rather than a 5xx.

    Returns the merged (unsorted, unlimited) results and the parallel wall-clock
    time in milliseconds (measured around the gather, NOT a sum of per-workspace
    times).
    """
    # Embed once, reuse across all workspaces (#13).
    query_vector = search_service.embed_query_vector(request)

    semaphore = asyncio.Semaphore(settings.search_max_workspace_concurrency)

    async def _search_one(ws_id: str) -> list[SearchResult]:
        async with semaphore:
            try:
                resp = await search_service.search(
                    workspace_id=ws_id,
                    user_id=user_id,
                    request=request,
                    query_vector=query_vector,
                )
                return resp.results
            except Exception as exc:  # noqa: BLE001 — partial-result isolation
                logger.warning(
                    "multi_workspace_search_partial_failure",
                    workspace_id=ws_id,
                    error=str(exc),
                )
                return []

    start = time.time()
    per_workspace_results = await asyncio.gather(*(_search_one(ws_id) for ws_id in workspace_ids))
    wall_clock_ms = (time.time() - start) * 1000

    merged: list[SearchResult] = []
    for ws_results in per_workspace_results:
        merged.extend(ws_results)
    return merged, wall_clock_ms


@router.post("/search", response_model=SearchResponse)
async def search_documents(
    request: SearchRequest,
    auth: Annotated[ResolvedAuth, Depends(resolve_workspace_search)],
    search_service: Annotated[SearchService, Depends(get_search_service)],
    background_tasks: BackgroundTasks,
    x_source: Annotated[str | None, Header(alias="X-Source")] = None,
) -> SearchResponse:
    """
    Perform semantic search across documents in the workspace.

    Requires an API key with 'search' permission.
    Workspace can be specified via ``X-Workspace-Id`` header.
    If the user has multiple workspaces and no header is provided,
    searches across all accessible workspaces.
    """
    # Determine audit source from header
    valid_sources = {"dashboard", "chat"}
    source = x_source if x_source in valid_sources else "api_key"

    workspace_id = auth.workspace_id

    if workspace_id:
        response = await search_service.search(
            workspace_id=workspace_id,
            user_id=auth.key_info.user_id,
            request=request,
        )
        # PM-S019: expand context windows and compute total_tokens
        await _expand_context_and_total_tokens(response, request, workspace_id)
        _record_search_metrics(request, workspace_id)
        _schedule_audit(
            background_tasks,
            auth=auth,
            request=request,
            response=response,
            source=source,
            workspace_id=workspace_id,
        )
        return response

    # Multi-workspace: search across all user workspaces, merge results
    database = await get_database()
    user_workspaces = await database.get_user_workspace_ids(auth.key_info.user_id)
    if not user_workspaces:
        response = SearchResponse(
            results=[],
            query=request.query,
            total_results=0,
            processing_time_ms=0.0,
            search_mode=request.search_mode,
        )
        # PM-S019: no results, total_tokens stays 0; context expansion skipped
        await _expand_context_and_total_tokens(response, request, "")
        _record_search_metrics(request, None)
        _schedule_audit(
            background_tasks,
            auth=auth,
            request=request,
            response=response,
            source=source,
            workspace_id="multi",
        )
        return response

    # #13: concurrent, bounded fan-out with per-workspace failure isolation.
    # Permission scoping (#45): user_workspaces == get_user_workspace_ids, the
    # caller's authorised set, so merged results cannot cross authorization.
    all_results, wall_clock_ms = await _search_workspaces_concurrently(
        search_service,
        user_id=auth.key_info.user_id,
        workspace_ids=user_workspaces,
        request=request,
    )

    # Deterministic global top-k: sort by descending score with a stable
    # tiebreaker on (chunk_id, document_id) so equal scores rank consistently
    # across requests, then truncate to the requested limit (#13).
    all_results.sort(key=lambda r: (-r.score, r.chunk_id, r.document_id))
    limited = all_results[: request.limit]

    response = SearchResponse(
        results=limited,
        query=request.query,
        total_results=len(limited),
        # Parallel wall-clock, not the sum of per-workspace times (#13).
        processing_time_ms=round(wall_clock_ms, 2),
        search_mode=request.search_mode,
    )
    # PM-S019: for multi-workspace, use primary workspace when unambiguous
    ctx_ws = user_workspaces[0] if len(user_workspaces) == 1 else ""
    await _expand_context_and_total_tokens(response, request, ctx_ws)
    _record_search_metrics(request, None)
    _schedule_audit(
        background_tasks,
        auth=auth,
        request=request,
        response=response,
        source=source,
        workspace_id=user_workspaces[0] if len(user_workspaces) == 1 else "multi",
    )
    return response
