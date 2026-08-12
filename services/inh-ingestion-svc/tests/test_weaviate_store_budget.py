"""Unit tests for store_in_weaviate StartToClose budget (#228)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.temporal.weaviate_store_budget import (
    _FIXED_OVERHEAD_SECONDS,
    _SECONDS_PER_WAVE,
    weaviate_store_timeout,
    weaviate_store_timeout_seconds,
)


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """No-op override of the package-level DB-dependent autouse fixture."""
    yield


def test_one_batch_covers_full_retry_worst_case():
    # 1 batch, concurrency 2 → 1 wave: 100 + 30 = 130
    # Must exceed EMBEDDING_BATCH_MAX_RETRIES × EMBEDDING_TIMEOUT_S (3×30=90)
    # so StartToClose does not cancel mid per-batch retry (#229 review).
    assert weaviate_store_timeout_seconds(1) == _SECONDS_PER_WAVE + _FIXED_OVERHEAD_SECONDS
    assert weaviate_store_timeout_seconds(1) >= 90 + _FIXED_OVERHEAD_SECONDS
    assert weaviate_store_timeout_seconds(0) == weaviate_store_timeout_seconds(1)


def test_scales_with_waves_not_raw_batches_when_concurrent():
    # 44 chunks → 2 batches; concurrency 2 → 1 wave → same as one batch.
    assert weaviate_store_timeout_seconds(44) == _SECONDS_PER_WAVE + _FIXED_OVERHEAD_SECONDS
    # Force serial waves: concurrency 1 → 2 waves.
    assert weaviate_store_timeout_seconds(44, max_concurrency=1) == (
        2 * _SECONDS_PER_WAVE + _FIXED_OVERHEAD_SECONDS
    )


def test_many_batches_scale_then_cap():
    # 535 chunks → 17 batches; concurrency 2 → 9 waves: 9*100+30=930 → cap 900
    assert weaviate_store_timeout_seconds(535) == 900
    assert weaviate_store_timeout_seconds(10_000) == 900


def test_never_below_one_wave_budget():
    assert weaviate_store_timeout_seconds(1, batch_size=10_000) == (
        _SECONDS_PER_WAVE + _FIXED_OVERHEAD_SECONDS
    )


def test_timedelta_wrapper():
    assert weaviate_store_timeout(1) == timedelta(
        seconds=_SECONDS_PER_WAVE + _FIXED_OVERHEAD_SECONDS
    )
