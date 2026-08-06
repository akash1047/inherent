"""Config defaults must be single-sourced, not respelled per call site (#202).

The ingestion half of the pair; see this service's sibling in
inh-public-api-svc/tests/unit/test_settings_config_dedup_contract.py for the
full rationale. Both services talk to the same TEI endpoint with the same
embedding width, and both previously re-hardcoded that URL and dimension in
``services/embedder.py`` as literals separate from their own ``Settings``
field defaults -- so each service could drift from settings.py independently,
and the two services could drift from each other.

Also guards a dead constant staying dead: ``temporal/worker.py`` used to
carry ``TASK_QUEUE_NAME = "document-ingestion"``, an unused duplicate of
``settings.temporal_task_queue``. A duplicate that nothing reads is the
cheapest kind to reintroduce and the most misleading to find later -- a
future reader has no way to tell which of the two the worker actually binds
to without tracing it.
"""

from __future__ import annotations

import pytest

import src.temporal.worker as worker_module
from src.config.settings import Settings
from src.services.embedder import _DEFAULT_DIM, _DEFAULT_URL


# Override the package-level DB-dependent autouse fixture (tests/conftest.py)
# with a no-op. These assertions read module constants only -- without this
# override the whole module silently SKIPS wherever PostgreSQL is absent, so
# an anti-drift guard would report green while checking nothing. Same pattern
# as tests/test_temporal_trigger.py and tests/test_contracts.py.
@pytest.fixture(autouse=True)
def cleanup_test_data():
    """No-op override so this module's tests run without a live database."""
    yield

# Golden values, kept identical to the public-api service's copy on purpose:
# these two constants are the cross-service contract.
GOLDEN_EMBEDDING_URL = "http://text-embeddings-inference:80"
GOLDEN_EMBEDDING_DIM = 384


def test_embedder_defaults_derive_from_settings() -> None:
    """embedder.py must not re-hardcode what settings.py already declares."""
    assert _DEFAULT_URL == Settings.model_fields["embedding_service_url"].default
    assert _DEFAULT_DIM == Settings.model_fields["embedding_dim"].default


def test_embedder_defaults_match_golden_values() -> None:
    """Pins the shared default itself, so a silent change is visible."""
    assert _DEFAULT_URL == GOLDEN_EMBEDDING_URL
    assert _DEFAULT_DIM == GOLDEN_EMBEDDING_DIM


def test_task_queue_name_duplicate_stays_removed() -> None:
    """The task queue name has exactly one home: settings.temporal_task_queue.

    Asserts against the field default rather than an instantiated Settings:
    this service's Settings has required fields with no defaults, so
    ``Settings()`` raises unless the full environment is present. The
    contract here is about the declared default anyway, not a runtime value.
    """
    assert not hasattr(worker_module, "TASK_QUEUE_NAME")
    assert Settings.model_fields["temporal_task_queue"].default
