"""Search endpoint."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header

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
            logger.debug("search_metric_record_failed", metric="missing_token_count", error=str(exc))
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

    all_results = []
    total_time = 0.0
    for ws_id in user_workspaces:
        resp = await search_service.search(
            workspace_id=ws_id,
            user_id=auth.key_info.user_id,
            request=request,
        )
        all_results.extend(resp.results)
        total_time += resp.processing_time_ms

    # Sort by score descending and limit
    all_results.sort(key=lambda r: r.score, reverse=True)
    limited = all_results[: request.limit]

    response = SearchResponse(
        results=limited,
        query=request.query,
        total_results=len(limited),
        processing_time_ms=round(total_time, 2),
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
