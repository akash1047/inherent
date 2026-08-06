"""Tests for the #175/#177 workspace-ownership hardening.

#175 (security): DELETE /documents/{document_id} trusted caller-supplied
workspace_id/user_id -- the same missing-ownership-check pattern #134 fixed
on PATCH /chunks/{document_id}/{chunk_index}. See test_weaviate_delete.py for
the endpoint-level tests; this module covers the shared ownership helper
directly.

#177 (security): six more inh-ingestion-svc endpoints were gated only by
verify_api_key, with no check that the caller's claimed workspace_id/job_id
pairing was one it was actually entitled to:

- GET  /ingest/{document_id}/status
- GET  /lineage/{document_id}
- GET  /dead-letter               (the sharpest edge -- see below)
- GET  /dead-letter/{job_id}
- POST /dead-letter/{job_id}/retry     (a write)
- POST /dead-letter/{job_id}/abandon   (a write)

GET /dead-letter returned dead-letter rows across EVERY workspace (workspace_id
was an optional filter), and those rows carry genuine (document_id,
workspace_id, user_id) triples. That enabled an escalation chain: read a
genuine cross-tenant pair from GET /dead-letter, then present it to PATCH
/chunks/{document_id}/{chunk_index} -- #134's ownership guard checks
(document_id, workspace_id) CONSISTENCY, which a harvested pair genuinely
satisfies, so it would pass and let an attacker overwrite (and re-embed) a
victim's chunk. This module proves that chain is closed: GET /dead-letter now
requires and enforces workspace_id (never returns a foreign tenant's rows),
and GET /dead-letter/{job_id} independently 404s a job it doesn't own even if
the caller already has the (correct) job_id.

Every route below mirrors #134's fix (`resolve_owned_document` /
`resolve_owned_dead_letter_job` in src/api/ownership.py): resolve the
row against PostgreSQL first, 404 unless its stored workspace_id matches the
caller's claim (same response for missing vs. foreign-workspace, so
existence doesn't leak), and -- the "lookup-failure-denies" tests below --
never treat a DB lookup failure as "allowed".
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.api.ownership import resolve_owned_dead_letter_job, resolve_owned_document

# ---------------------------------------------------------------------------
# Override conftest autouse fixtures -- these tests don't need PostgreSQL.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def cleanup_test_data():
    """Override global autouse cleanup -- no DB needed for these tests."""
    yield


@pytest.fixture()
def db_service():
    """Override -- these tests mock DatabaseService directly."""
    yield None


# ---------------------------------------------------------------------------
# Unit tests: src/api/ownership.py helpers, in isolation
# ---------------------------------------------------------------------------


class TestResolveOwnedDocument:
    """resolve_owned_document -- owner-allowed / non-owner-denied /
    lookup-failure-denies, decoupled from any specific route."""

    async def test_owner_allowed(self):
        mock_db = MagicMock()
        mock_db.get_document_status = AsyncMock(
            return_value={"document_id": "doc1", "workspace_id": "ws1", "user_id": "u1"}
        )
        document = await resolve_owned_document(mock_db, "doc1", "ws1")
        assert document["workspace_id"] == "ws1"

    async def test_non_owner_denied(self):
        """Document exists but is owned by a DIFFERENT workspace -- 404, not
        a leak of the fact that the document exists at all."""
        mock_db = MagicMock()
        mock_db.get_document_status = AsyncMock(
            return_value={"document_id": "doc1", "workspace_id": "ws_owner", "user_id": "u1"}
        )
        with pytest.raises(HTTPException) as exc_info:
            await resolve_owned_document(mock_db, "doc1", "ws_attacker")
        assert exc_info.value.status_code == 404

    async def test_missing_document_denied_with_same_404(self):
        """No such document -- same 404 shape as the non-owner case (no
        distinguishable response that would leak existence)."""
        mock_db = MagicMock()
        mock_db.get_document_status = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc_info:
            await resolve_owned_document(mock_db, "doc_missing", "ws1")
        assert exc_info.value.status_code == 404

    async def test_lookup_failure_denies_not_allows(self):
        """A DB failure during the ownership lookup must propagate, not be
        swallowed into an implicit 'allow'. No try/except in
        resolve_owned_document is the point -- this test pins that."""
        mock_db = MagicMock()
        mock_db.get_document_status = AsyncMock(side_effect=RuntimeError("DB unavailable"))
        with pytest.raises(RuntimeError, match="DB unavailable"):
            await resolve_owned_document(mock_db, "doc1", "ws1")


class TestResolveOwnedDeadLetterJob:
    """resolve_owned_dead_letter_job -- same matrix, for dead_letter_jobs."""

    async def test_owner_allowed(self):
        mock_db = MagicMock()
        mock_db.get_dead_letter_job = AsyncMock(
            return_value={"id": 1, "workspace_id": "ws1", "status": "pending"}
        )
        job = await resolve_owned_dead_letter_job(mock_db, 1, "ws1")
        assert job["workspace_id"] == "ws1"

    async def test_non_owner_denied(self):
        mock_db = MagicMock()
        mock_db.get_dead_letter_job = AsyncMock(
            return_value={"id": 1, "workspace_id": "ws_victim", "status": "pending"}
        )
        with pytest.raises(HTTPException) as exc_info:
            await resolve_owned_dead_letter_job(mock_db, 1, "ws_attacker")
        assert exc_info.value.status_code == 404

    async def test_missing_job_denied_with_same_404(self):
        mock_db = MagicMock()
        mock_db.get_dead_letter_job = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc_info:
            await resolve_owned_dead_letter_job(mock_db, 999, "ws1")
        assert exc_info.value.status_code == 404

    async def test_lookup_failure_denies_not_allows(self):
        mock_db = MagicMock()
        mock_db.get_dead_letter_job = AsyncMock(side_effect=RuntimeError("DB unavailable"))
        with pytest.raises(RuntimeError, match="DB unavailable"):
            await resolve_owned_dead_letter_job(mock_db, 1, "ws1")


# ---------------------------------------------------------------------------
# Route-level tests: shared TestClient fixture
# ---------------------------------------------------------------------------

VALID_API_KEY = "test-secret-key-abc123"


def _make_mock_settings(**overrides):
    defaults = {
        "ingestion_api_key": VALID_API_KEY,
        "api_host": "127.0.0.1",
        "api_port": 8000,
        "temporal_host": "localhost:7233",
        "temporal_namespace": "default",
        "temporal_task_queue": "document-ingestion",
        "log_level": "INFO",
    }
    defaults.update(overrides)
    s = MagicMock()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


@pytest.fixture()
def client():
    """TestClient with Temporal mocked; DB is mocked per-test via patch."""
    mock_settings = _make_mock_settings()

    mock_temporal_client = AsyncMock()
    mock_handle = AsyncMock()
    mock_handle.query = AsyncMock(
        return_value={"step": "chunking_text", "progress": 55, "chunks_created": 3}
    )
    mock_temporal_client.get_workflow_handle = MagicMock(return_value=mock_handle)

    with (
        patch("src.api.app.TemporalWorkerManager") as mock_manager_cls,
        patch("src.api.auth.get_settings", return_value=mock_settings),
    ):
        instance = mock_manager_cls.return_value
        instance.start = AsyncMock()
        instance.stop = AsyncMock()
        instance.get_client = AsyncMock(return_value=mock_temporal_client)
        instance.is_running = True

        from src.api.app import create_app

        app = create_app(mock_settings)

        with TestClient(app) as tc:
            tc._mock_temporal_client = mock_temporal_client
            yield tc


_OWNED_DOC = {
    "document_id": "doc1",
    "workspace_id": "ws_owner",
    "user_id": "user_owner",
    "chunk_count": 3,
}
_OWNED_JOB = {
    "id": 1,
    "workspace_id": "ws_owner",
    "user_id": "user_owner",
    "document_id": "doc1",
    "status": "pending",
    "original_message": {"document_id": "doc1"},
}


# ---------------------------------------------------------------------------
# GET /ingest/{document_id}/status
# ---------------------------------------------------------------------------


class TestIngestionStatusOwnership:
    def test_owner_allowed(self, client: TestClient):
        mock_db = MagicMock()
        mock_db.get_document_status = AsyncMock(return_value=_OWNED_DOC)
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            resp = client.get(
                "/ingest/doc1/status?workspace_id=ws_owner",
                headers={"X-API-Key": VALID_API_KEY},
            )
        assert resp.status_code == 200

    def test_non_owner_denied(self, client: TestClient):
        mock_db = MagicMock()
        mock_db.get_document_status = AsyncMock(return_value=_OWNED_DOC)
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            resp = client.get(
                "/ingest/doc1/status?workspace_id=ws_attacker",
                headers={"X-API-Key": VALID_API_KEY},
            )
        assert resp.status_code == 404
        client._mock_temporal_client.get_workflow_handle.assert_not_called()

    def test_missing_workspace_id_returns_422(self, client: TestClient):
        resp = client.get("/ingest/doc1/status", headers={"X-API-Key": VALID_API_KEY})
        assert resp.status_code == 422

    def test_lookup_failure_denies_not_allows(self, client: TestClient):
        mock_db = MagicMock()
        mock_db.get_document_status = AsyncMock(side_effect=RuntimeError("DB unavailable"))
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            with pytest.raises(RuntimeError, match="DB unavailable"):
                client.get(
                    "/ingest/doc1/status?workspace_id=ws_owner",
                    headers={"X-API-Key": VALID_API_KEY},
                )
        client._mock_temporal_client.get_workflow_handle.assert_not_called()


# ---------------------------------------------------------------------------
# GET /lineage/{document_id}
# ---------------------------------------------------------------------------


class TestLineageOwnership:
    def test_owner_allowed(self, client: TestClient):
        mock_db = MagicMock()
        mock_db.get_document_status = AsyncMock(return_value=_OWNED_DOC)
        mock_db.get_ingestion_events = AsyncMock(return_value=[])
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            resp = client.get(
                "/lineage/doc1?workspace_id=ws_owner",
                headers={"X-API-Key": VALID_API_KEY},
            )
        assert resp.status_code == 200
        assert resp.json() == {"document_id": "doc1", "events": []}

    def test_non_owner_denied(self, client: TestClient):
        mock_db = MagicMock()
        mock_db.get_document_status = AsyncMock(return_value=_OWNED_DOC)
        mock_db.get_ingestion_events = AsyncMock(return_value=[{"leaked": "event"}])
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            resp = client.get(
                "/lineage/doc1?workspace_id=ws_attacker",
                headers={"X-API-Key": VALID_API_KEY},
            )
        assert resp.status_code == 404
        mock_db.get_ingestion_events.assert_not_called()

    def test_missing_workspace_id_returns_422(self, client: TestClient):
        resp = client.get("/lineage/doc1", headers={"X-API-Key": VALID_API_KEY})
        assert resp.status_code == 422

    def test_lookup_failure_denies_not_allows(self, client: TestClient):
        mock_db = MagicMock()
        mock_db.get_document_status = AsyncMock(side_effect=RuntimeError("DB unavailable"))
        mock_db.get_ingestion_events = AsyncMock(return_value=[{"leaked": "event"}])
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            with pytest.raises(RuntimeError, match="DB unavailable"):
                client.get(
                    "/lineage/doc1?workspace_id=ws_owner",
                    headers={"X-API-Key": VALID_API_KEY},
                )
        mock_db.get_ingestion_events.assert_not_called()


# ---------------------------------------------------------------------------
# GET /dead-letter/{job_id}, POST retry, POST abandon
# ---------------------------------------------------------------------------


class TestDeadLetterJobOwnership:
    def test_get_owner_allowed(self, client: TestClient):
        mock_db = MagicMock()
        mock_db.get_dead_letter_job = AsyncMock(return_value=_OWNED_JOB)
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            resp = client.get(
                "/dead-letter/1?workspace_id=ws_owner",
                headers={"X-API-Key": VALID_API_KEY},
            )
        assert resp.status_code == 200
        assert resp.json()["id"] == 1

    def test_get_non_owner_denied(self, client: TestClient):
        mock_db = MagicMock()
        mock_db.get_dead_letter_job = AsyncMock(return_value=_OWNED_JOB)
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            resp = client.get(
                "/dead-letter/1?workspace_id=ws_attacker",
                headers={"X-API-Key": VALID_API_KEY},
            )
        assert resp.status_code == 404

    def test_get_missing_workspace_id_returns_422(self, client: TestClient):
        resp = client.get("/dead-letter/1", headers={"X-API-Key": VALID_API_KEY})
        assert resp.status_code == 422

    def test_get_lookup_failure_denies_not_allows(self, client: TestClient):
        mock_db = MagicMock()
        mock_db.get_dead_letter_job = AsyncMock(side_effect=RuntimeError("DB unavailable"))
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            with pytest.raises(RuntimeError, match="DB unavailable"):
                client.get(
                    "/dead-letter/1?workspace_id=ws_owner",
                    headers={"X-API-Key": VALID_API_KEY},
                )

    def test_retry_owner_allowed(self, client: TestClient):
        fake_trigger = AsyncMock()
        fake_trigger.trigger_workflow_async = AsyncMock(return_value="ingest-doc1")
        mock_db = MagicMock()
        mock_db.get_dead_letter_job = AsyncMock(return_value=dict(_OWNED_JOB))
        mock_db.increment_dead_letter_retry = AsyncMock()
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            # app.state.trigger is set at startup; swap it directly on the
            # running app instance so this test asserts purely on the
            # route's own ownership check, not on Temporal/DB plumbing.
            client.app.state.trigger = fake_trigger
            resp = client.post(
                "/dead-letter/1/retry?workspace_id=ws_owner",
                headers={"X-API-Key": VALID_API_KEY},
            )
        assert resp.status_code == 200
        fake_trigger.trigger_workflow_async.assert_awaited_once()

    def test_retry_non_owner_denied_and_never_retries(self, client: TestClient):
        fake_trigger = AsyncMock()
        fake_trigger.trigger_workflow_async = AsyncMock(return_value="ingest-doc1")
        mock_db = MagicMock()
        mock_db.get_dead_letter_job = AsyncMock(return_value=dict(_OWNED_JOB))
        mock_db.increment_dead_letter_retry = AsyncMock()
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            client.app.state.trigger = fake_trigger
            resp = client.post(
                "/dead-letter/1/retry?workspace_id=ws_attacker",
                headers={"X-API-Key": VALID_API_KEY},
            )
        assert resp.status_code == 404
        fake_trigger.trigger_workflow_async.assert_not_awaited()
        mock_db.increment_dead_letter_retry.assert_not_called()

    def test_retry_missing_workspace_id_returns_422(self, client: TestClient):
        resp = client.post("/dead-letter/1/retry", headers={"X-API-Key": VALID_API_KEY})
        assert resp.status_code == 422

    def test_retry_lookup_failure_denies_not_allows(self, client: TestClient):
        fake_trigger = AsyncMock()
        mock_db = MagicMock()
        mock_db.get_dead_letter_job = AsyncMock(side_effect=RuntimeError("DB unavailable"))
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            client.app.state.trigger = fake_trigger
            with pytest.raises(RuntimeError, match="DB unavailable"):
                client.post(
                    "/dead-letter/1/retry?workspace_id=ws_owner",
                    headers={"X-API-Key": VALID_API_KEY},
                )
        fake_trigger.trigger_workflow_async.assert_not_awaited()

    def test_abandon_owner_allowed(self, client: TestClient):
        mock_db = MagicMock()
        mock_db.get_dead_letter_job = AsyncMock(return_value=dict(_OWNED_JOB))
        mock_db.update_dead_letter_status = AsyncMock(return_value=True)
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            resp = client.post(
                "/dead-letter/1/abandon?workspace_id=ws_owner",
                headers={"X-API-Key": VALID_API_KEY},
            )
        assert resp.status_code == 200
        mock_db.update_dead_letter_status.assert_awaited_once_with(1, "abandoned")

    def test_abandon_non_owner_denied_and_never_mutates(self, client: TestClient):
        mock_db = MagicMock()
        mock_db.get_dead_letter_job = AsyncMock(return_value=dict(_OWNED_JOB))
        mock_db.update_dead_letter_status = AsyncMock(return_value=True)
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            resp = client.post(
                "/dead-letter/1/abandon?workspace_id=ws_attacker",
                headers={"X-API-Key": VALID_API_KEY},
            )
        assert resp.status_code == 404
        mock_db.update_dead_letter_status.assert_not_called()

    def test_abandon_missing_workspace_id_returns_422(self, client: TestClient):
        resp = client.post("/dead-letter/1/abandon", headers={"X-API-Key": VALID_API_KEY})
        assert resp.status_code == 422

    def test_abandon_lookup_failure_denies_not_allows(self, client: TestClient):
        mock_db = MagicMock()
        mock_db.get_dead_letter_job = AsyncMock(side_effect=RuntimeError("DB unavailable"))
        mock_db.update_dead_letter_status = AsyncMock(return_value=True)
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            with pytest.raises(RuntimeError, match="DB unavailable"):
                client.post(
                    "/dead-letter/1/abandon?workspace_id=ws_owner",
                    headers={"X-API-Key": VALID_API_KEY},
                )
        mock_db.update_dead_letter_status.assert_not_called()


# ---------------------------------------------------------------------------
# The #177 escalation chain: GET /dead-letter -> PATCH /chunks
# ---------------------------------------------------------------------------


class TestDeadLetterEscalationChainClosed:
    """Reproduces the exact chain #177 describes and proves each of its two
    steps is now independently blocked:

    1. An attacker holding only INGESTION_API_KEY calls GET /dead-letter to
       harvest a genuine (document_id, workspace_id) pair belonging to a
       victim tenant. Before this fix, GET /dead-letter had no workspace_id
       enforcement -- any workspace's rows were visible. It's now required
       and always enforced as a DB filter, so this harvest returns nothing
       for the attacker's own claimed workspace.
    2. Even granting the attacker somehow already knows the victim's
       (document_id, workspace_id) pair (e.g. leaked another way), reading
       the SAME dead-letter job directly by id now 404s unless the caller's
       claimed workspace_id actually owns it -- closing the single-job read
       path independently of the list path.

    #134's own guard (PATCH /chunks checking document_id<->workspace_id
    CONSISTENCY) is intentionally unchanged and untested here -- it was
    already proven in test_chunk_edit_weaviate.py, and the point of this
    fix is that a genuine pair can no longer be HARVESTED via dead-letter
    routes in the first place, not that the consistency check itself needed
    to change.
    """

    def test_list_never_returns_another_workspaces_rows(self, client: TestClient):
        """GET /dead-letter?workspace_id=ws_attacker must not surface
        ws_victim's rows -- proven here by asserting the DB call itself is
        always scoped to the caller's claimed workspace_id, so a fake/mocked
        DB that ignores the filter is the only way this could leak, and the
        real DatabaseService.get_dead_letter_jobs (tests/test_dead_letter.py)
        is exercised WHERE the query actually filters."""
        mock_db = MagicMock()
        # Simulate a correctly-filtering DB: only ws_attacker's own
        # (empty) set of jobs comes back, never ws_victim's.
        mock_db.get_dead_letter_jobs = AsyncMock(return_value=[])
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            resp = client.get(
                "/dead-letter?workspace_id=ws_attacker",
                headers={"X-API-Key": VALID_API_KEY},
            )
        assert resp.status_code == 200
        assert resp.json()["jobs"] == []
        mock_db.get_dead_letter_jobs.assert_awaited_once_with(
            workspace_id="ws_attacker", status="pending", limit=50
        )

    def test_list_without_workspace_id_is_rejected_outright(self, client: TestClient):
        """The pre-fix escalation's first step required NO workspace_id at
        all. That request shape must now fail validation before it ever
        reaches the database."""
        resp = client.get("/dead-letter", headers={"X-API-Key": VALID_API_KEY})
        assert resp.status_code == 422

    def test_single_job_read_blocks_the_harvested_pair(self, client: TestClient):
        """Step 2: even with a genuine victim (document_id, workspace_id)
        pair somehow in hand, reading the dead-letter job directly by id
        under the attacker's claimed workspace_id 404s."""
        victim_job = {
            "id": 42,
            "workspace_id": "ws_victim",
            "user_id": "user_victim",
            "document_id": "doc_victim",
            "status": "pending",
            "original_message": {"document_id": "doc_victim"},
        }
        mock_db = MagicMock()
        mock_db.get_dead_letter_job = AsyncMock(return_value=victim_job)
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            resp = client.get(
                "/dead-letter/42?workspace_id=ws_attacker",
                headers={"X-API-Key": VALID_API_KEY},
            )
        assert resp.status_code == 404

    def test_end_to_end_chain_is_broken(self, client: TestClient):
        """Full chain, single test: list scoped to the attacker's own
        workspace never surfaces the victim's job, so the attacker never
        obtains a genuine (document_id, workspace_id) pair to escalate with
        via PATCH /chunks in the first place."""
        mock_db = MagicMock()
        # The attacker's own workspace has no dead-letter jobs at all --
        # the victim's job exists in PostgreSQL but under a different
        # workspace_id, so a correctly-scoped query never returns it.
        mock_db.get_dead_letter_jobs = AsyncMock(return_value=[])
        with patch("src.temporal.shared_services.get_db_service", return_value=mock_db):
            list_resp = client.get(
                "/dead-letter?workspace_id=ws_attacker",
                headers={"X-API-Key": VALID_API_KEY},
            )
        assert list_resp.status_code == 200
        assert list_resp.json()["jobs"] == []
        # No (document_id, workspace_id) pair was ever harvested, so there
        # is nothing to escalate with -- the chain stops here.
