"""Config defaults must be single-sourced, not respelled per call site (#202).

Three values in this service were each written down twice, so a deployment
that changed one and not the other would silently disagree with itself:

- the Postgres database name, spelled "knowledge_base" in BOTH the
  ``database_url`` default and ``cloud_sql_database``. Change the local
  default to point at a renamed database and the Cloud SQL path keeps
  naming the old one.
- the TEI endpoint URL and the embedding dimension, declared as
  ``Settings`` field defaults AND re-hardcoded as ``_DEFAULT_URL`` /
  ``_DEFAULT_DIM`` literals in ``services/embedder.py``. The embedder's
  fallback is what gets used when the env var is absent, so a corrected
  ``Settings`` default would not reach the code path that actually needs
  it. A wrong ``_DEFAULT_DIM`` in particular does not fail loudly -- it
  produces vectors of the wrong width against the configured collection.

This mirrors the anti-drift pattern already used for the S3 region (#132,
test_settings_region_contract.py) and Weaviate naming (#12): the golden
value lives in ONE place and every other site derives from it.

The two assertion styles below are deliberate and catch different faults:

- comparing the embedder's constant to the ``Settings`` field default
  catches someone re-hardcoding a literal in embedder.py that no longer
  matches settings.py -- the drift this change exists to prevent.
- comparing the ``Settings`` field default to a golden literal catches a
  silent change to the shared default itself. That may well be intended,
  but it must be a deliberate edit to this test, not a side effect.

The companion half for inh-ingestion-svc lives in that service's
tests/test_settings_config_dedup_contract.py -- both embedders read the
same TEI service, so each side needs its own guard.
"""

from __future__ import annotations

from src.config.constants import DEFAULT_DATABASE_NAME
from src.config.settings import Settings
from src.services.embedder import _DEFAULT_DIM, _DEFAULT_URL

# Golden values. Changing these is allowed; changing them by accident is not.
GOLDEN_DATABASE_NAME = "knowledge_base"
GOLDEN_EMBEDDING_URL = "http://text-embeddings-inference:80"
GOLDEN_EMBEDDING_DIM = 384


def test_database_name_is_single_sourced() -> None:
    """Both database-name call sites must derive from DEFAULT_DATABASE_NAME.

    Asserts against the declared field defaults, NOT an instantiated
    ``Settings()``. Anywhere the real environment is present -- CI's compose
    stack, any deployment -- ``DATABASE_URL`` is set and legitimately points
    somewhere else, so instantiating here would test the environment rather
    than the deduplication this guards.
    """
    # The Cloud SQL field IS the shared constant, not a copy of its text.
    assert Settings.model_fields["cloud_sql_database"].default == DEFAULT_DATABASE_NAME
    # The local URL embeds it rather than respelling it.
    assert Settings.model_fields["database_url"].default.endswith(f"/{DEFAULT_DATABASE_NAME}")


def test_database_name_matches_golden_value() -> None:
    """A deliberate rename must come here; an accidental one fails."""
    assert DEFAULT_DATABASE_NAME == GOLDEN_DATABASE_NAME


def test_embedder_defaults_derive_from_settings() -> None:
    """embedder.py must not re-hardcode what settings.py already declares."""
    assert _DEFAULT_URL == Settings.model_fields["embedding_service_url"].default
    assert _DEFAULT_DIM == Settings.model_fields["embedding_dim"].default


def test_embedder_defaults_match_golden_values() -> None:
    """Pins the shared default itself, so a silent change is visible."""
    assert _DEFAULT_URL == GOLDEN_EMBEDDING_URL
    assert _DEFAULT_DIM == GOLDEN_EMBEDDING_DIM
