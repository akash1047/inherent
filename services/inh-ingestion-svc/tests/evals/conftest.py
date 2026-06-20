"""Fixtures for the offline extraction/chunking quality evals.

The evals operate purely on the bundled sample documents and the in-process
extraction/chunking helpers, so they must NOT depend on PostgreSQL, Weaviate,
or any other live service. The root ``tests/conftest.py`` installs an autouse
``cleanup_test_data`` fixture that depends on ``db_service`` (which skips when
PostgreSQL is unavailable); we override it here with a no-op so these evals run
unconditionally offline.
"""

from pathlib import Path

import pytest

# Repo root: tests/evals/conftest.py -> tests -> inh-ingestion-svc -> services -> repo
_REPO_ROOT = Path(__file__).resolve().parents[4]
SAMPLE_DOCS_DIR = _REPO_ROOT / "docs" / "examples" / "sample-documents"


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Override the DB-backed root autouse fixture so evals stay fully offline."""
    yield


@pytest.fixture(scope="session")
def sample_docs_dir() -> Path:
    """Directory holding the bundled sample documents used as eval fixtures."""
    assert SAMPLE_DOCS_DIR.is_dir(), f"Sample documents dir missing: {SAMPLE_DOCS_DIR}"
    return SAMPLE_DOCS_DIR
