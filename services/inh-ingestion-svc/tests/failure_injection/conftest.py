"""Local conftest for failure-injection tests.

The package-level ``tests/conftest.py`` defines an ``autouse=True`` fixture
(``cleanup_test_data``) that depends on ``db_service``, which in turn calls
``pytest.skip("PostgreSQL not available")`` when there is no live database.
That would skip *every* test under ``tests/`` — including these, which are
fully mocked and must run offline.

We override that autouse fixture here with a no-op so these tests execute
(and assert real behavior) without any live PostgreSQL/Weaviate/Redis/etc.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """No-op override of the package-level DB-dependent autouse fixture.

    These tests never touch a real database, so there is nothing to clean
    up and no reason to require (or skip on) PostgreSQL.
    """
    yield
