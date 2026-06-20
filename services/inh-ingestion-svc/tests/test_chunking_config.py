"""Tests for configurable, model-aware chunking (milestone #10).

Covers:
- The chunk activity uses settings/input values, NOT the old hardcoded
  literals (strategy="sentences", max_chunk_size=1000, chunk_overlap=200).
- The workflow resolves chunking config from input overrides else settings.
- A consistent, model-aware token estimate is applied to stored chunks.
- Oversized text is split so each chunk stays under the embedding token budget.

No live stack: staging and settings are mocked.
"""

import asyncio

import pytest

from src.config.settings import Settings, get_settings
from src.temporal.activities import chunk as chunk_mod
from src.temporal.activities.chunk import (
    _chunk_text_inner,
    _token_budget_char_cap,
    estimate_tokens,
)
from src.temporal.models import ChunkTextInput


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """No-op override of the package-level DB-dependent autouse fixture.

    The package ``tests/conftest.py`` defines an autouse ``cleanup_test_data``
    that depends on ``db_service`` and skips when PostgreSQL is unavailable.
    These tests are fully mocked/offline, so we override it with a no-op (same
    pattern as tests/failure_injection/conftest.py).
    """
    yield


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeStaging:
    """In-memory stand-in for the staging service."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.written_chunks: list[dict] | None = None

    def read_text(self, workflow_run_id: str) -> str:
        return self._text

    def write_chunks(self, workflow_run_id: str, chunks: list[dict]) -> None:
        self.written_chunks = chunks


def _make_settings(**overrides) -> Settings:
    base = dict(
        DATABASE_URL="postgresql://x/y",
        WEAVIATE_URL="http://localhost:8080",
        WEAVIATE_API_KEY="",
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _run_chunk(monkeypatch, text: str, input_obj: ChunkTextInput, settings: Settings):
    """Run _chunk_text_inner with staging + settings patched, return the fake staging."""
    fake = _FakeStaging(text)

    import src.temporal.shared_services as shared

    monkeypatch.setattr(shared, "get_staging_service", lambda: fake, raising=True)
    monkeypatch.setattr(chunk_mod, "get_settings", lambda: settings, raising=False)
    # get_settings is imported lazily inside the function from src.config.settings
    import src.config.settings as settings_mod

    monkeypatch.setattr(settings_mod, "get_settings", lambda: settings, raising=True)

    asyncio.run(_chunk_text_inner(input_obj))
    return fake


# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------


def test_estimate_tokens_empty_is_zero():
    assert estimate_tokens("") == 0


def test_estimate_tokens_uses_max_of_word_and_char_branches():
    # Many short words -> word branch (words * 1.3) dominates.
    text = "a a a a a a a a a a"  # 10 words, 19 chars
    # word branch: ceil(10 * 1.3) = 13 ; char branch: ceil(19/4) = 5
    assert estimate_tokens(text) == 13

    # Long single token -> char branch (chars / 4) dominates.
    long = "x" * 400  # 1 word, 400 chars
    # word branch: ceil(1.3) = 2 ; char branch: ceil(400/4) = 100
    assert estimate_tokens(long) == 100


def test_estimate_tokens_is_not_naive_word_split():
    # Naive len(split()) would be 1; our estimate must be higher for a long token.
    long = "y" * 100
    assert len(long.split()) == 1
    assert estimate_tokens(long) > 1


# ---------------------------------------------------------------------------
# Token budget cap helper
# ---------------------------------------------------------------------------


def test_token_budget_char_cap():
    # Cap is the conservative min of the chars-branch (4T) and the words-branch
    # (~2T/1.3) so BOTH estimate_tokens branches stay under the budget.
    cap = _token_budget_char_cap(512)
    assert cap == min(512 * 4, int((2 * 512) / 1.3))
    # A chunk of exactly `cap` chars must estimate at or under the budget.
    assert estimate_tokens("x" * cap) <= 512
    assert estimate_tokens(" ".join(["a"] * (cap // 2))) <= 512
    assert _token_budget_char_cap(0) == 1  # never zero


# ---------------------------------------------------------------------------
# Chunk activity honours settings/input (not the old hardcoded literals)
# ---------------------------------------------------------------------------


def test_chunk_activity_applies_token_count_to_stored_chunks(monkeypatch):
    settings = _make_settings(EMBEDDING_MAX_TOKENS=512)
    text = "This is a sentence. " * 20
    input_obj = ChunkTextInput(
        workflow_run_id="wf1",
        document_id="doc1",
        strategy="sentences",
        max_chunk_size=200,
        chunk_overlap=20,
    )
    fake = _run_chunk(monkeypatch, text, input_obj, settings)

    assert fake.written_chunks
    for c in fake.written_chunks:
        assert "token_count" in c
        # token_count is the model-aware estimate, not naive word split.
        assert c["token_count"] == estimate_tokens(c["content"])
        assert c["token_count"] > 0


def test_chunk_activity_respects_non_default_strategy_and_size(monkeypatch):
    # Use paragraph strategy with a small size -> proves the input values are
    # used rather than the old hardcoded strategy="sentences"/max=1000.
    settings = _make_settings(EMBEDDING_MAX_TOKENS=512)
    text = "Para one body text here.\n\nPara two body text here.\n\nPara three body."
    input_obj = ChunkTextInput(
        workflow_run_id="wf1",
        document_id="doc1",
        strategy="paragraphs",
        max_chunk_size=30,
        chunk_overlap=0,
    )
    fake = _run_chunk(monkeypatch, text, input_obj, settings)

    assert fake.written_chunks
    # With max_chunk_size=30 chars and 3 paragraphs, we expect multiple chunks
    # (a max_chunk_size of 1000 would have produced a single chunk).
    assert len(fake.written_chunks) >= 2


# ---------------------------------------------------------------------------
# Oversized text is split to stay under the embedding token budget
# ---------------------------------------------------------------------------


def test_oversized_text_split_under_token_budget(monkeypatch):
    # Tiny token budget so the char cap is small; even though max_chunk_size is
    # huge, the effective size must be clamped and every chunk must stay under
    # the budget.
    settings = _make_settings(EMBEDDING_MAX_TOKENS=10)  # char cap = 40
    # One long run of words with no sentence punctuation -> size-based splitting.
    text = "word " * 200
    input_obj = ChunkTextInput(
        workflow_run_id="wf1",
        document_id="doc1",
        strategy="tokens",
        max_chunk_size=100_000,  # absurdly large; must be clamped
        chunk_overlap=0,
    )
    fake = _run_chunk(monkeypatch, text, input_obj, settings)

    assert fake.written_chunks
    assert len(fake.written_chunks) > 1  # had to split
    for c in fake.written_chunks:
        assert c["token_count"] <= settings.embedding_max_tokens


# ---------------------------------------------------------------------------
# Workflow resolution logic (input override else settings; not hardcoded)
# ---------------------------------------------------------------------------


def _resolve(input_obj, settings):
    """Mirror the workflow's resolution logic for unit testing."""
    strategy = input_obj.chunking_strategy or settings.chunking_strategy
    max_chunk_size = (
        input_obj.max_chunk_size
        if input_obj.max_chunk_size is not None
        else settings.max_chunk_size
    )
    chunk_overlap = (
        input_obj.chunk_overlap if input_obj.chunk_overlap is not None else settings.chunk_overlap
    )
    return strategy, max_chunk_size, chunk_overlap


def test_workflow_falls_back_to_settings_when_input_unset():
    from src.temporal.models import DocumentIngestionInput

    settings = _make_settings(CHUNKING_STRATEGY="paragraphs", MAX_CHUNK_SIZE=777, CHUNK_OVERLAP=33)
    inp = DocumentIngestionInput(
        document_id="d",
        workspace_id="w",
        user_id="u",
        filename="f",
        original_filename="f",
        content_type="text/plain",
        size_bytes=1,
        storage_backend="local",
        storage_path="p",
    )
    strategy, max_size, overlap = _resolve(inp, settings)
    # Not the old hardcoded literals (sentences/1000/200).
    assert (strategy, max_size, overlap) == ("paragraphs", 777, 33)


def test_workflow_prefers_input_overrides():
    from src.temporal.models import DocumentIngestionInput

    settings = _make_settings(CHUNKING_STRATEGY="sentences", MAX_CHUNK_SIZE=1000, CHUNK_OVERLAP=200)
    inp = DocumentIngestionInput(
        document_id="d",
        workspace_id="w",
        user_id="u",
        filename="f",
        original_filename="f",
        content_type="text/plain",
        size_bytes=1,
        storage_backend="local",
        storage_path="p",
        chunking_strategy="tokens",
        max_chunk_size=256,
        chunk_overlap=10,
    )
    strategy, max_size, overlap = _resolve(inp, settings)
    assert (strategy, max_size, overlap) == ("tokens", 256, 10)


def test_settings_default_embedding_max_tokens():
    # Fresh settings (defaults) expose the new budget field at 512 (bge-small).
    get_settings.cache_clear()
    s = _make_settings()
    assert s.embedding_max_tokens == 512


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
