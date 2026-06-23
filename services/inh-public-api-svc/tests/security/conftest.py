"""Conftest for the offline security regression suite (#32).

The security tests mock the database / search layers and never touch the live
stack. The autouse ``cleanup_test_data`` fixture is intentionally a no-op so the
suite stays self-contained and offline — it exists so any future fixture that
*does* allocate state has a single, obvious teardown hook to extend.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """No-op cleanup so the security suite runs fully offline.

    Yields control to the test, then performs no teardown (there is no live
    state to clean up). Present as the canonical extension point.
    """
    yield
    # Intentionally no teardown — these tests are offline and stateless.
