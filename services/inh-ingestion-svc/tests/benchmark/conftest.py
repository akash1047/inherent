"""Fixtures for the ingestion benchmark suite.

test_benchmark_report.py is pure-logic (no network, no live services) and must
run in the default offline suite. The root ``tests/conftest.py`` installs an
autouse ``cleanup_test_data`` fixture that depends on ``db_service`` (which
skips when PostgreSQL is unavailable); override it here with a no-op so those
tests run unconditionally offline, same pattern as ``tests/evals/conftest.py``.
The live Compose benchmark in test_ingestion_throughput.py doesn't touch the
database directly and is unaffected either way -- it's already gated by its
own `benchmark`/`compose` markers and `_require_stack()` skip guard.
"""

import pytest


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Override the DB-backed root autouse fixture so offline tests here stay offline."""
    yield
