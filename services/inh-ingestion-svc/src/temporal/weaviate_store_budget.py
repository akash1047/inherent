"""StartToClose budget for ``store_in_weaviate`` (#228).

The activity embeds every chunk of a document in one shot. A flat 60s
budget is enough for small docs at idle load and not enough once TEI
queue time climbs (2026-08-10 bulk-upload incident: queue_time p50
18.3s, 70/83 documents timed out after five attempts).

Scale the budget with chunk count so large documents get enough wall
clock without giving every tiny doc a 15-minute hang. Pure function so
workflow code and unit tests share one formula (Temporal sandbox-safe:
stdlib only).

The per-batch component must cover the embedder's **worst-case** batch
wall clock under ``EMBEDDING_BATCH_MAX_RETRIES`` × ``EMBEDDING_TIMEOUT_S``
plus jitter sleeps (#229 review): otherwise StartToClose cancels mid
per-batch retry and Temporal re-embeds the whole document.
"""

from __future__ import annotations

from datetime import timedelta

# Matches embedder defaults (EMBEDDING_BATCH_SIZE / TEI max-client-batch).
_DEFAULT_BATCH_SIZE = 32
# Matches embedder EMBEDDING_MAX_CONCURRENCY default (kept low for bulk safety).
_DEFAULT_EMBED_CONCURRENCY = 2
# Matches embedder EMBEDDING_BATCH_MAX_RETRIES / EMBEDDING_TIMEOUT_S defaults.
_DEFAULT_BATCH_ATTEMPTS = 3
_DEFAULT_BATCH_HTTP_TIMEOUT_S = 30
# Sum of exponential backoff sleeps across failed attempts (capped ~8s each).
_BATCH_RETRY_SLEEP_BUDGET_S = 10
# Worst-case wall clock for one concurrent "wave" of batches (each batch
# retries serially; concurrent batches finish in ~max of their times).
_SECONDS_PER_WAVE = (
    _DEFAULT_BATCH_ATTEMPTS * _DEFAULT_BATCH_HTTP_TIMEOUT_S + _BATCH_RETRY_SLEEP_BUDGET_S
)  # 100
# Weaviate batch write + fencing + lineage after embeddings finish.
_FIXED_OVERHEAD_SECONDS = 30
# Hard cap so a pathological multi-thousand-chunk doc cannot pin a worker
# slot indefinitely; ops should raise concurrency/model capacity instead.
_MAX_SECONDS = 900


def weaviate_store_timeout_seconds(
    chunk_count: int,
    *,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    max_concurrency: int = _DEFAULT_EMBED_CONCURRENCY,
) -> int:
    """Return StartToClose seconds for embedding + Weaviate store.

    ``chunk_count`` is the number of staged chunks for the document.
    Empty/zero counts still get one synthetic batch wave so a no-op store
    cannot hang on a misconfigured zero timeout.

    Wall-clock model under parallel dispatch::

        waves = ceil(batches / max_concurrency)
        seconds = waves * (attempts * http_timeout + sleep_budget) + overhead
    """
    n = max(0, int(chunk_count))
    size = max(1, int(batch_size))
    concurrency = max(1, int(max_concurrency))
    batches = max(1, (n + size - 1) // size) if n > 0 else 1
    waves = max(1, (batches + concurrency - 1) // concurrency)
    raw = waves * _SECONDS_PER_WAVE + _FIXED_OVERHEAD_SECONDS
    # One-wave minimum is the effective floor (100 + 30 = 130 with defaults).
    return min(_MAX_SECONDS, raw)


def weaviate_store_timeout(chunk_count: int) -> timedelta:
    """Timedelta form used at ``workflow.execute_activity`` call sites."""
    return timedelta(seconds=weaviate_store_timeout_seconds(chunk_count))
