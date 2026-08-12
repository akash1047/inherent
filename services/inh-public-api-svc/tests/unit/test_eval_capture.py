"""Capture write-behind (evals v1): never raises, honors opt-out, piggybacks
retention purge, and derives event fields from the search response."""

from unittest.mock import AsyncMock, patch

import pytest

from src.models.search import SearchRequest, SearchResponse, SearchResult
from src.services import eval_capture


def _response(n=1):
    results = [
        SearchResult(
            chunk_id=f"c{i}",
            document_id=f"d{i}",
            document_name=f"doc{i}",
            content="x",
            score=0.9 - i * 0.1,
        )
        for i in range(n)
    ]
    return SearchResponse(
        results=results, query="q", total_results=n, processing_time_ms=12.5, search_mode="hybrid"
    )


def test_new_event_id_format():
    eid = eval_capture.new_event_id()
    assert eid.startswith("ev_") and len(eid) == 35  # "ev_" + 32 hex chars


def test_capture_enabled_honors_optout():
    with patch.object(eval_capture, "settings") as s:
        s.eval_capture_enabled = True
        s.eval_capture_optout_set.return_value = {"ws-blocked"}
        assert eval_capture.capture_enabled("ws-1") is True
        assert eval_capture.capture_enabled("ws-blocked") is False
        s.eval_capture_enabled = False
        assert eval_capture.capture_enabled("ws-1") is False


@pytest.mark.asyncio
async def test_record_query_event_derives_fields_from_the_response():
    db = AsyncMock()
    with patch("src.services.eval_capture.get_database", new=AsyncMock(return_value=db)):
        await eval_capture.record_query_event(
            event_id="ev_x",
            workspace_id="ws-1",
            user_id="u-1",
            request=SearchRequest(query="q", search_mode="hybrid"),
            response=_response(2),
        )
    kwargs = db.insert_eval_event.call_args.kwargs
    assert kwargs["result_doc_ids"] == ["d0", "d1"]
    assert kwargs["result_chunk_ids"] == ["c0", "c1"]
    assert kwargs["top_score"] == pytest.approx(0.9)
    # The purge no longer rides along here (#240): record_query_event is awaited
    # on the request path, so it does the INSERT and nothing else. The purge is
    # queued separately by the search handler and stays write-behind — see
    # test_eval_capture_durability.py.
    db.purge_expired_eval_events.assert_not_awaited()


@pytest.mark.asyncio
async def test_purge_expired_events_uses_the_configured_retention():
    db = AsyncMock()
    with (
        patch("src.services.eval_capture.get_database", new=AsyncMock(return_value=db)),
        patch.object(eval_capture, "settings") as s,
    ):
        s.eval_retention_days = 30
        await eval_capture.purge_expired_events("ws-1")
    db.purge_expired_eval_events.assert_awaited_once_with(workspace_id="ws-1", retention_days=30)


@pytest.mark.asyncio
async def test_purge_expired_events_never_raises():
    """Best-effort like capture: a failed purge cannot surface anywhere."""
    with patch(
        "src.services.eval_capture.get_database",
        new=AsyncMock(side_effect=RuntimeError("db down")),
    ):
        await eval_capture.purge_expired_events("ws-1")


@pytest.mark.asyncio
async def test_record_query_event_never_raises():
    db = AsyncMock()
    db.insert_eval_event.side_effect = RuntimeError("db down")
    # Must swallow: capture failure can never surface into the search path.
    with patch("src.services.eval_capture.get_database", new=AsyncMock(return_value=db)):
        await eval_capture.record_query_event(
            event_id="ev_x",
            workspace_id="ws-1",
            user_id=None,
            request=SearchRequest(query="q"),
            response=_response(0),
        )


@pytest.mark.asyncio
async def test_record_query_event_swallows_db_resolution_failure():
    # Even resolving the database handle (cold/failed init) must not propagate:
    # the handle is acquired inside the task's try block, off the request path.
    with patch(
        "src.services.eval_capture.get_database",
        new=AsyncMock(side_effect=RuntimeError("db init failed")),
    ):
        await eval_capture.record_query_event(
            event_id="ev_x",
            workspace_id="ws-1",
            user_id=None,
            request=SearchRequest(query="q"),
            response=_response(1),
        )
