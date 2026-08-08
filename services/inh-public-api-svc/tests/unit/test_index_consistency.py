"""Unit tests for the Postgres/Weaviate index-consistency detector (#221).

Two production documents were found with ``status=processed`` and a
non-zero ``chunk_count`` in Postgres, yet zero objects in their Weaviate
workspace collection/tenant — invisible to every search mode. Corroborating
signal: their ``document_chunks`` rows have ``content_hash``/``source_uri``
NULL and a byte-identical ``ingested_at`` despite being created months
apart, which the real ingestion pipeline can never produce (it always
computes ``content_hash`` and stamps a fresh, per-run ``ingested_at`` — see
``store_processed_document`` in inh-ingestion-svc) — the write bypassed the
pipeline entirely (a direct/backfill write), and Weaviate never saw it.

Offline: DatabaseService and SearchService are both mocked (following
tests/unit/test_delete_document.py and tests/unit/test_search_missing_collection.py),
so no real Postgres/Weaviate is touched.
"""

from __future__ import annotations

import datetime as _dt
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.models.document import Document, DocumentChunk
from src.services.index_consistency import check_workspace_index_consistency
from src.services.search import SearchService, _get_workspace_collection_name

WS = "ws-1"
COLLECTION = _get_workspace_collection_name(WS)


def _document(
    doc_id: str,
    *,
    status: str = "processed",
    chunk_count: int = 3,
) -> Document:
    return Document(
        id=doc_id,
        name=f"{doc_id}.pdf",
        workspace_id=WS,
        source_type="s3",
        mime_type="application/pdf",
        size_bytes=100,
        chunk_count=chunk_count,
        status=status,
        created_at=_dt.datetime(2026, 4, 1, tzinfo=_dt.timezone.utc),
        updated_at=_dt.datetime(2026, 4, 1, tzinfo=_dt.timezone.utc),
        metadata=None,
    )


def _chunk(
    doc_id: str, *, content_hash: str | None = None, ingested_at: str | None = None
) -> DocumentChunk:
    return DocumentChunk(
        id=f"{doc_id}-c0",
        document_id=doc_id,
        content="chunk text",
        chunk_index=0,
        metadata={"content_hash": content_hash, "ingested_at": ingested_at},
    )


def _upload_fields(doc_id: str, user_id: str = "user-1") -> dict:
    return {
        "document_id": doc_id,
        "workspace_id": WS,
        "user_id": user_id,
        "filename": "stored.pdf",
        "original_filename": f"{doc_id}.pdf",
        "content_type": "application/pdf",
        "size_bytes": 100,
        "storage_backend": "s3",
        "storage_path": f"{WS}/{doc_id}/stored.pdf",
        "storage_bucket": "docs",
        "storage_url": None,
    }


def _mock_database(documents: list[Document], *, chunks_by_doc: dict | None = None) -> AsyncMock:
    """Mimic DatabaseService.get_documents' single-page pagination contract."""
    db = AsyncMock()

    async def _get_documents(workspace_id: str, page: int = 1, page_size: int = 20):
        if page > 1:
            return [], len(documents)
        return documents, len(documents)

    db.get_documents = _get_documents
    db.get_document_upload_fields = AsyncMock(
        side_effect=lambda doc_id, workspace_id: _upload_fields(doc_id)
    )
    chunks_by_doc = chunks_by_doc or {}
    db.get_document_chunks_by_doc_id = AsyncMock(
        side_effect=lambda doc_id: chunks_by_doc.get(doc_id, [])
    )
    return db


def _search_service_with_counts(counts: dict[str, int]) -> SearchService:
    """A SearchService whose Weaviate GraphQL Aggregate call returns a fixed
    per-document object count, following the httpx-client-stub pattern in
    tests/unit/test_search_missing_collection.py."""
    svc = SearchService(database=MagicMock(), weaviate_url="http://fake")
    client = AsyncMock(spec=httpx.AsyncClient)

    async def _post(path, json=None, **_):  # noqa: ANN001
        query = json["query"]
        # The document_id is embedded in the GraphQL where-clause literal.
        matched_doc_id = next((doc_id for doc_id in counts if f'"{doc_id}"' in query), None)
        count = counts.get(matched_doc_id, 0) if matched_doc_id else 0
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"data": {"Aggregate": {COLLECTION: [{"meta": {"count": count}}]}}}
        return resp

    client.post = _post
    svc._client = client
    return svc


class TestIndexConsistencyDetector:
    async def test_processed_document_present_in_index_is_not_flagged(self):
        doc = _document("doc-present")
        db = _mock_database([doc])
        search = _search_service_with_counts({"doc-present": 3})

        report = await check_workspace_index_consistency(db, search, WS)

        assert report.orphaned == []
        assert report.documents_checked == 1

    async def test_processed_document_absent_from_index_is_flagged(self):
        doc = _document("doc-orphaned", chunk_count=2)
        chunk = _chunk("doc-orphaned", content_hash=None, ingested_at="2026-07-04T09:20:37.512957")
        db = _mock_database([doc], chunks_by_doc={"doc-orphaned": [chunk]})
        search = _search_service_with_counts({})  # zero objects anywhere

        report = await check_workspace_index_consistency(db, search, WS)

        assert report.orphaned_count == 1
        flagged = report.orphaned[0]
        assert flagged.document_id == "doc-orphaned"
        assert flagged.chunk_count == 2
        assert flagged.content_hash is None
        assert flagged.ingested_at == "2026-07-04T09:20:37.512957+00:00"

    @pytest.mark.parametrize("status", ["pending", "failed"])
    async def test_non_processed_document_is_never_flagged(self, status):
        doc = _document("doc-in-flight", status=status, chunk_count=0)
        db = _mock_database([doc])
        search = _search_service_with_counts({})

        report = await check_workspace_index_consistency(db, search, WS)

        assert report.orphaned == []

    async def test_processed_document_with_zero_chunks_is_never_flagged(self):
        # status=processed but chunk_count=0 has nothing to search for — not
        # the #221 defect (a doc mid-way through an as-yet-incomplete write).
        doc = _document("doc-empty", chunk_count=0)
        db = _mock_database([doc])
        search = _search_service_with_counts({})

        report = await check_workspace_index_consistency(db, search, WS)

        assert report.orphaned == []

    async def test_empty_workspace_produces_empty_report(self):
        db = _mock_database([])
        search = _search_service_with_counts({})

        report = await check_workspace_index_consistency(db, search, WS)

        assert report.orphaned == []
        assert report.documents_checked == 0

    async def test_mixed_workspace_flags_only_the_orphan(self):
        present = _document("doc-present")
        orphan = _document("doc-orphaned")
        pending = _document("doc-pending", status="pending", chunk_count=0)
        db = _mock_database([present, orphan, pending])
        search = _search_service_with_counts({"doc-present": 5})

        report = await check_workspace_index_consistency(db, search, WS)

        assert report.documents_checked == 3
        assert [o.document_id for o in report.orphaned] == ["doc-orphaned"]
