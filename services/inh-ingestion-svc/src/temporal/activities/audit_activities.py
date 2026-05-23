"""Temporal activities for audit log processing.

Three activities form the audit-write pipeline:
1. ``validate_audit_event`` — schema/field validation
2. ``write_audit_log_to_mongo`` — idempotent MongoDB insert
3. ``emit_audit_metric`` — Prometheus counter increment
"""

from __future__ import annotations

from typing import Any

import structlog
from prometheus_client import Counter
from temporalio import activity

from src.config.settings import get_settings

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Prometheus counters
# ---------------------------------------------------------------------------

audit_logs_written_total = Counter(
    "audit_logs_written_total",
    "Total audit logs successfully written to MongoDB",
    ["source", "workspace_id"],
)

audit_logs_invalid_total = Counter(
    "audit_logs_invalid_total",
    "Total audit events that failed validation",
)

# ---------------------------------------------------------------------------
# Required fields for validation
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = frozenset(
    {
        "audit_id",
        "workspace_id",
        "user_id",
        "source",
        "query_type",
        "query_text",
        "result_count",
        "response_time_ms",
        "request_id",
        "query_timestamp",
    }
)

_VALID_SOURCES = frozenset({"api_key", "dashboard", "chat"})


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------


@activity.defn
async def validate_audit_event(event: dict[str, Any]) -> dict[str, Any]:
    """Validate required fields and source enum.

    Returns the event unchanged on success.  Raises ``ValueError`` on failure.
    """
    missing = _REQUIRED_FIELDS - set(event)
    if missing:
        audit_logs_invalid_total.inc()
        raise ValueError(f"Missing required audit fields: {sorted(missing)}")

    source = event.get("source")
    if source not in _VALID_SOURCES:
        audit_logs_invalid_total.inc()
        raise ValueError(f"Invalid source '{source}', must be one of {sorted(_VALID_SOURCES)}")

    logger.info("Audit event validated", audit_id=event.get("audit_id"))
    return event


@activity.defn
async def write_audit_log_to_mongo(event: dict[str, Any]) -> bool:
    """Write the audit event to MongoDB. Returns True on insert, False on duplicate."""
    from src.services.audit_mongo_writer import upsert_audit_log

    settings = get_settings()

    return await upsert_audit_log(
        event,
        mongo_uri=settings.mongodb_uri,
        db_name=settings.mongodb_db_name,
    )


@activity.defn
async def emit_audit_metric(event: dict[str, Any]) -> None:
    """Increment Prometheus counters for the written audit log."""
    source = event.get("source", "unknown")
    workspace_id = event.get("workspace_id", "unknown")
    audit_logs_written_total.labels(source=source, workspace_id=workspace_id).inc()
    logger.info(
        "Audit metric emitted",
        audit_id=event.get("audit_id"),
        source=source,
    )
