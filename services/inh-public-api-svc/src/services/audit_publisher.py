"""Audit event publisher for search queries.

Builds audit events from search results and publishes them to the
``audit.log.write`` Redis Stream in a fire-and-forget fashion.
Failures are logged but never raised — audit publishing must never
block or fail a user search request.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from src.config import settings
from src.utils import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Truncation helpers
# ---------------------------------------------------------------------------

MAX_QUERY_TEXT_LENGTH = 2000
MAX_SNIPPET_LENGTH = 200
MAX_RESULT_SNIPPETS = 5


def truncate_snippet(text: str, max_length: int = MAX_SNIPPET_LENGTH) -> str:
    """Truncate a text snippet to *max_length* characters."""
    if len(text) <= max_length:
        return text
    return text[:max_length]


# ---------------------------------------------------------------------------
# Event builder
# ---------------------------------------------------------------------------


def build_audit_event(
    *,
    workspace_id: str,
    user_id: str,
    api_key_id: str,
    source: str,
    query_type: str,
    query_text: str,
    query_filters: dict[str, Any] | None = None,
    result_count: int,
    result_snippets: list[dict[str, Any]] | None = None,
    returned_chunk_ids: list[str] | None = None,
    llm_response: str | None = None,
    response_time_ms: float,
    request_id: str | None = None,
    # Optional search-mode / context fields (PM-S018 / PM-S019)
    search_mode: str | None = None,
    include_context: bool | None = None,
    context_window: int | None = None,
    alpha: float | None = None,
    risk_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Construct an audit event dict ready for MQ publishing.

    Applies safety limits:
    - ``query_text`` capped at 2000 chars
    - Each snippet's ``snippet`` field capped at 200 chars
    - At most 5 result snippets kept

    The optional keyword arguments ``search_mode``, ``include_context``,
    ``context_window``, and ``alpha`` are included only when provided (i.e.
    not ``None``), so existing callers that omit them are unaffected.
    """
    audit_id = str(uuid.uuid4())

    # Truncate query
    safe_query = query_text[:MAX_QUERY_TEXT_LENGTH] if query_text else ""

    # Truncate and cap snippets
    safe_snippets: list[dict[str, Any]] = []
    if result_snippets:
        for snip in result_snippets[:MAX_RESULT_SNIPPETS]:
            entry = dict(snip)
            if "snippet" in entry:
                entry["snippet"] = truncate_snippet(str(entry["snippet"]))
            safe_snippets.append(entry)

    event: dict[str, Any] = {
        "audit_id": audit_id,
        "workspace_id": workspace_id,
        "user_id": user_id,
        "api_key_id": api_key_id,
        "source": source,
        "query_type": query_type,
        "query_text": safe_query,
        "query_filters": query_filters or {},
        "result_count": result_count,
        "result_snippets": safe_snippets,
        # Provenance (#41): the chunk_ids of the evidence actually returned, so
        # an audit record can be tied back to specific chunks.
        "returned_chunk_ids": list(returned_chunk_ids) if returned_chunk_ids else [],
        "llm_response": llm_response,
        "response_time_ms": response_time_ms,
        "request_id": request_id or str(uuid.uuid4()),
        "query_timestamp": datetime.now(UTC).isoformat(),
    }

    # Conditionally include optional search metadata
    if search_mode is not None:
        event["search_mode"] = search_mode
    if include_context is not None:
        event["include_context"] = include_context
    if context_window is not None:
        event["context_window"] = context_window
    if alpha is not None:
        event["alpha"] = alpha
    # RAG-poisoning visibility (#44): counts of returned chunks by risk level so
    # an auditor can spot when risky evidence is surfacing in answers.
    if risk_counts is not None:
        event["risk_counts"] = risk_counts

    return event


def count_results_by_risk(results: list[Any]) -> dict[str, int]:
    """Tally returned search results by their content_risk level (#44).

    Buckets every result into one of "none" | "low" | "medium" | "high". A
    missing/unknown ``content_risk`` counts as "none" so the totals always sum
    to the number of returned results.
    """
    counts = {"none": 0, "low": 0, "medium": 0, "high": 0}
    for r in results:
        level = getattr(r, "content_risk", None) or "none"
        if level not in counts:
            level = "none"
        counts[level] += 1
    return counts


# ---------------------------------------------------------------------------
# Publisher (fire-and-forget)
# ---------------------------------------------------------------------------


async def publish_audit_event(event: dict[str, Any]) -> None:
    """Publish an audit event to the audit log topic.

    This function is intentionally fire-and-forget: it catches **all**
    exceptions, logs a warning, and never raises. It is designed to be
    used as a FastAPI ``BackgroundTasks`` callback.
    """
    try:
        from src.services.mq import get_mq_service

        mq = await get_mq_service()
        await mq.publish(settings.audit_log_topic, event)
        logger.info(
            "Audit event published",
            audit_id=event.get("audit_id"),
            topic=settings.audit_log_topic,
        )
    except Exception:
        logger.warning(
            "Failed to publish audit event (swallowed)",
            audit_id=event.get("audit_id"),
            exc_info=True,
        )
