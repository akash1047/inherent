"""A document must be observable in the status API before the store step (#10).

No processed_documents row existed until the store step, so an early
'processing'/'failed' status write hit 0 rows and a document that failed during
fetch/extract/chunk showed 'not found'. The workflow now creates a minimal
'processing' row up front.

Also (#110): this activity is where a workflow run claims the document's
fencing token (active_run_id) -- see store_processed_document /
TestCreatePendingDocumentClaimsFencingToken below.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.database import DatabaseService, DocumentStatus
from src.temporal.activities.status import create_pending_document
from src.temporal.models import CreatePendingDocumentInput


def _input() -> CreatePendingDocumentInput:
    return CreatePendingDocumentInput(
        document_id="doc-1",
        workspace_id="ws",
        user_id="u",
        filename="f.txt",
        original_filename="orig.txt",
        content_type="text/plain",
        size_bytes=10,
        storage_backend="local",
        storage_path="p",
        workflow_run_id="run-abc",
    )


@pytest.mark.asyncio
async def test_activity_delegates_to_db():
    db = MagicMock()
    db.create_pending_document = AsyncMock(return_value=True)
    with patch("src.temporal.shared_services.get_db_service", return_value=db):
        result = await create_pending_document(_input())
    assert result is True
    kwargs = db.create_pending_document.await_args.kwargs
    assert kwargs["document_id"] == "doc-1"
    assert kwargs["workspace_id"] == "ws"
    # (#110) the activity must forward workflow_run_id so the DB layer can
    # claim the fencing token -- without this, create_pending_document could
    # not tell WHICH run is claiming the document.
    assert kwargs["workflow_run_id"] == "run-abc"


@pytest.mark.asyncio
async def test_db_create_pending_returns_true_on_insert():
    session = MagicMock()
    session.execute.return_value = MagicMock(rowcount=1)
    # Use a fully-initialised service so self.processed_documents exists.
    from src.config.settings import Settings

    db = DatabaseService.__new__(DatabaseService)
    DatabaseService.__init__(db, Settings.model_construct())
    db.engine = MagicMock()

    @contextmanager
    def _gs():
        yield session

    db.get_session = _gs

    created = await db.create_pending_document(
        document_id="doc-1",
        workspace_id="ws",
        user_id="u",
        filename="f.txt",
        original_filename="orig.txt",
        content_type="text/plain",
        size_bytes=10,
        storage_backend="local",
        storage_path="p",
        workflow_run_id="run-abc",
    )
    assert created is True
    # (#110) two statements now: the INSERT ... ON CONFLICT DO NOTHING (row
    # create, unchanged from #10) AND an unconditional UPDATE that claims
    # active_run_id -- see TestCreatePendingDocumentClaimsFencingToken for
    # what that second statement actually asserts about its own shape.
    assert session.execute.call_count == 2
    assert DocumentStatus.PROCESSING.value == "processing"


# ---------------------------------------------------------------------------
# Fencing-token claim tests (#110 blocker 1)
# ---------------------------------------------------------------------------


class TestCreatePendingDocumentClaimsFencingToken:
    """create_pending_document must claim active_run_id for THIS run on
    every call -- insert (brand-new document) AND conflict (re-index of an
    existing document) -- since the conflict case is exactly the re-index
    scenario #110 is about. Without the claim, a later store commit from a
    stale, superseded run can't be told apart from a legitimate one."""

    def _db_with_recording_session(self):
        """A DatabaseService whose session.execute() records every statement
        passed to it, so tests can inspect what was actually sent to
        Postgres (values on the INSERT, the WHERE/values on the UPDATE)."""
        from src.config.settings import Settings

        db = DatabaseService.__new__(DatabaseService)
        DatabaseService.__init__(db, Settings.model_construct())
        db.engine = MagicMock()

        executed = []
        session = MagicMock()

        def _execute(stmt, *a, **kw):
            executed.append(stmt)
            return MagicMock(rowcount=1)

        session.execute.side_effect = _execute

        @contextmanager
        def _gs():
            yield session

        db.get_session = _gs
        return db, executed

    @pytest.mark.asyncio
    async def test_insert_branch_stamps_active_run_id(self):
        """A brand-new document (no prior row) claims active_run_id as part
        of the INSERT's own values."""
        db, executed = self._db_with_recording_session()

        await db.create_pending_document(
            document_id="doc-new",
            workspace_id="ws",
            user_id="u",
            filename="f.txt",
            original_filename="orig.txt",
            content_type="text/plain",
            size_bytes=10,
            storage_backend="local",
            storage_path="p",
            workflow_run_id="run-A",
        )

        insert_stmt = executed[0]
        # SQLAlchemy Insert exposes its VALUES as .select_names / compiled
        # params; the simplest robust check is compiling and inspecting the
        # bound parameters.
        compiled = insert_stmt.compile()
        assert compiled.params.get("active_run_id") == "run-A"

    @pytest.mark.asyncio
    async def test_conflict_branch_always_claims_via_explicit_update(self):
        """The re-index case (row already exists, INSERT ON CONFLICT DO
        NOTHING is a no-op): the SECOND statement is an explicit UPDATE that
        unconditionally sets active_run_id to the new run -- this is what
        makes a re-index's run supersede a stale run's claim."""
        db, executed = self._db_with_recording_session()

        await db.create_pending_document(
            document_id="doc-existing",
            workspace_id="ws",
            user_id="u",
            filename="f.txt",
            original_filename="orig.txt",
            content_type="text/plain",
            size_bytes=10,
            storage_backend="local",
            storage_path="p",
            workflow_run_id="run-B",
        )

        assert len(executed) == 2
        update_stmt = executed[1]
        compiled = update_stmt.compile()
        assert compiled.params.get("active_run_id") == "run-B"
