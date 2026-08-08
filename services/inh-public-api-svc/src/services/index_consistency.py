"""Postgres/Weaviate index-consistency detector (#221).

Two production documents were found with ``status=processed`` and a
non-zero ``chunk_count`` in PostgreSQL, real chunk text (``GET
/v1/chunks/{id}`` returns it), yet ZERO objects in their workspace's
Weaviate collection/tenant — they can never be found by any search mode.
Corroborating signal from that incident: both documents' ``document_chunks``
rows have ``content_hash``/``source_uri`` NULL and a byte-identical
``ingested_at`` despite being created three months apart.

That signal is not incidental — it is proof the write never went through
the real ingestion pipeline. ``store_processed_document``
(inh-ingestion-svc/src/services/database.py) ALWAYS computes
``content_hash = sha256(chunk content)`` and stamps ``ingested_at =
datetime.now(UTC)`` at the moment of that specific run, and the Temporal
workflow (``document_ingestion.py``) deliberately marks the document
``failed`` — not ``processed`` — when the Weaviate write fails, precisely to
avoid a PG-only "ghost" document. Grepping both services for every write to
``processed_documents``/``document_chunks`` turns up exactly ONE app-level
writer of chunk rows (``store_processed_document``); nothing in the shipped
code can produce a NULL ``content_hash`` or a shared fixed ``ingested_at``.
So this divergence was produced OUTSIDE the application (a direct/backfill
SQL write against production), which no in-process code path can prevent —
only a periodic consistency check can catch it. This module is that check.

Both REST and MCP surfaces that expose this check (if/when added) should call
through here so they can never drift, mirroring ``services/deletion.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.services.lineage import build_lineage
from src.services.search import (
    SearchService,
    _get_user_tenant_name,
    _get_workspace_collection_name,
    _require_safe_name,
)
from src.utils import get_logger

if TYPE_CHECKING:
    from src.services.database import DatabaseService

logger = get_logger(__name__)

# The one status the ingestion pipeline considers "done" — see
# inh-ingestion-svc's DocumentStatus.PROCESSED. A pending/processing/failed
# document has no vectors by design (still in flight, or the workflow's own
# Weaviate-failure branch already marked it failed) and must never be
# flagged as an index-consistency defect.
PROCESSED_STATUS = "processed"

# Page size for walking a workspace's documents; matches the pagination
# contract of DatabaseService.get_documents (page/page_size), just chosen
# larger to keep the scan's round-trip count low for typical workspaces.
_DOCUMENT_PAGE_SIZE = 100


@dataclass
class OrphanedDocument:
    """A processed document with Postgres chunks but no Weaviate vectors.

    Fields match exactly what issue #221 asks an operator to be able to read
    off the report: document id, name, chunk_count, ingested_at,
    content_hash — the last two answer "how many documents share the
    backfill's fixed timestamp with a null content_hash" directly from the
    report, no extra query needed.
    """

    document_id: str
    name: str
    chunk_count: int
    ingested_at: str | None
    content_hash: str | None


@dataclass
class ConsistencyReport:
    """Result of scanning one workspace for Postgres/Weaviate divergence."""

    workspace_id: str
    documents_checked: int = 0
    orphaned: list[OrphanedDocument] = field(default_factory=list)

    @property
    def orphaned_count(self) -> int:
        return len(self.orphaned)


async def _has_vectors(
    search_service: SearchService,
    *,
    workspace_id: str,
    user_id: str,
    document_id: str,
) -> bool:
    """Return True iff at least one Weaviate object exists for ``document_id``.

    Reuses the exact collection/tenant naming and safe-name guard SearchService
    itself uses for a real query (single source of truth, no drift risk), and
    tolerates the same "nothing indexed yet" states
    (``SearchService._is_missing_collection`` / "tenant not found") search
    already treats as empty — a workspace/tenant that was never created reads
    as zero vectors rather than raising.
    """
    collection_name = _get_workspace_collection_name(workspace_id)
    tenant_name = _get_user_tenant_name(user_id)
    _require_safe_name(collection_name, "collection")
    _require_safe_name(tenant_name, "tenant")

    # document_id is a UUID-like opaque string in this codebase (never
    # user-authored free text), but escape defensively the same way
    # SearchService._build_graphql escapes the query string, since this
    # value is interpolated into a GraphQL literal below.
    escaped_id = document_id.replace("\\", "\\\\").replace('"', '\\"')
    graphql_query = f"""
    {{
        Aggregate {{
            {collection_name}(
                tenant: "{tenant_name}"
                where: {{
                    path: ["document_id"]
                    operator: Equal
                    valueText: "{escaped_id}"
                }}
            ) {{
                meta {{ count }}
            }}
        }}
    }}
    """

    client = await search_service._get_client()
    response = await client.post("/v1/graphql", json={"query": graphql_query})

    if response.status_code != 200:
        body = response.text
        # Same "no collection ingested yet for this workspace" tolerance as
        # SearchService.delete_document_vectors — nothing to find means zero
        # vectors, not an error.
        if collection_name in body and "could not find class" in body.lower():
            return False
        response.raise_for_status()

    data = response.json()
    if data.get("errors"):
        message = data["errors"][0].get("message", "unknown")
        if (
            SearchService._is_missing_collection(message, collection_name)
            or "tenant not found" in message
        ):
            return False
        raise RuntimeError(f"Weaviate Aggregate query failed for {document_id}: {message}")

    aggregate = data.get("data", {}).get("Aggregate", {}).get(collection_name) or []
    if not aggregate:
        return False
    count = aggregate[0].get("meta", {}).get("count", 0) or 0
    return count > 0


async def check_workspace_index_consistency(
    database: "DatabaseService",
    search_service: SearchService,
    workspace_id: str,
) -> ConsistencyReport:
    """Find processed documents in ``workspace_id`` with Postgres chunks but
    zero Weaviate vectors (#221).

    A document only qualifies for the (comparatively expensive) per-document
    Weaviate check when it is ``status == "processed"`` AND
    ``chunk_count > 0`` — the exact precondition the issue's ghost documents
    satisfy, and the only state in which "zero vectors" is ever a defect
    rather than expected (in-flight or already-failed documents have no
    vectors by design).

    For each flagged document, ``ingested_at``/``content_hash`` are read via
    the shared ``build_lineage`` helper (the same projection
    ``GET /v1/documents/{id}/lineage`` uses) so the report's provenance
    fields can never drift from what an operator would see calling that
    endpoint directly.
    """
    report = ConsistencyReport(workspace_id=workspace_id)
    page = 1

    while True:
        documents, total = await database.get_documents(
            workspace_id, page=page, page_size=_DOCUMENT_PAGE_SIZE
        )
        if not documents:
            break

        for document in documents:
            report.documents_checked += 1
            if document.status != PROCESSED_STATUS or document.chunk_count <= 0:
                continue

            fields = await database.get_document_upload_fields(document.id, workspace_id)
            if not fields:
                # Deleted between listing and this check — nothing to flag.
                continue

            has_vectors = await _has_vectors(
                search_service,
                workspace_id=workspace_id,
                user_id=fields["user_id"],
                document_id=document.id,
            )
            if has_vectors:
                continue

            chunks = await database.get_document_chunks_by_doc_id(document.id)
            lineage = build_lineage(document, chunks)
            logger.warning(
                "Index consistency: processed document has no Weaviate vectors",
                document_id=document.id,
                workspace_id=workspace_id,
                chunk_count=document.chunk_count,
                content_hash=lineage.content_hash,
                ingested_at=lineage.ingested_at,
            )
            report.orphaned.append(
                OrphanedDocument(
                    document_id=document.id,
                    name=document.name,
                    chunk_count=document.chunk_count,
                    ingested_at=lineage.ingested_at,
                    content_hash=lineage.content_hash,
                )
            )

        if page * _DOCUMENT_PAGE_SIZE >= total:
            break
        page += 1

    return report
