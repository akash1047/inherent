"""Unit tests for the chunk embedder (ENG-S083).

The embedder is now a thin HTTP client over the text-embeddings-inference
(TEI) sidecar. These tests mock httpx so they run offline and don't pull
the model.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _reset_embedder_client(monkeypatch):
    """Reset the module-level httpx client between tests so each test
    can install its own mock without state leaking across tests."""
    from src.services import embedder

    monkeypatch.setattr(embedder, "_CLIENT", None, raising=False)
    yield
    monkeypatch.setattr(embedder, "_CLIENT", None, raising=False)


class _StubResponse:
    def __init__(self, payload: Any, status: int = 200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _StubClient:
    """Minimal httpx.Client stand-in that records requests and returns
    canned vectors of the configured dimension."""

    def __init__(self, dim: int = 384):
        self.dim = dim
        self.calls: list[dict] = []

    def post(self, url: str, json: dict) -> _StubResponse:
        self.calls.append({"url": url, "json": json})
        inputs = json["inputs"]
        # Generate distinct vectors per input so order/equality assertions
        # in tests can distinguish them.
        vecs = []
        for i, text in enumerate(inputs):
            seed = (hash(text) % 7) + i + 1  # non-zero, deterministic, varies by input
            vecs.append([float(seed) / 1000.0] * self.dim)
        return _StubResponse(vecs)


def _install_stub(monkeypatch, dim: int = 384) -> _StubClient:
    from src.services import embedder

    stub = _StubClient(dim=dim)
    monkeypatch.setattr(embedder, "_client", lambda: stub, raising=True)
    return stub


def test_embed_text_returns_correct_dim(monkeypatch):
    from src.services.embedder import embed_text

    _install_stub(monkeypatch)
    vec = embed_text("How do I authenticate API requests?")
    assert len(vec) == 384
    assert all(isinstance(x, float) for x in vec)


def test_embed_text_empty_returns_zero_vector_no_http(monkeypatch):
    from src.services.embedder import embed_text

    stub = _install_stub(monkeypatch)
    vec = embed_text("")
    assert len(vec) == 384
    assert all(x == 0.0 for x in vec)
    assert stub.calls == [], "empty input must not hit the network"


def test_embed_text_whitespace_only_returns_zero_vector_no_http(monkeypatch):
    from src.services.embedder import embed_text

    stub = _install_stub(monkeypatch)
    vec = embed_text("   \n\t  ")
    assert len(vec) == 384
    assert all(x == 0.0 for x in vec)
    assert stub.calls == [], "whitespace-only input must not hit the network"


def test_embed_texts_batched_preserves_order_and_handles_empties(monkeypatch):
    from src.services.embedder import embed_texts

    stub = _install_stub(monkeypatch)
    out = embed_texts(["hello world", "", "another sentence"])
    assert len(out) == 3
    assert len(out[0]) == 384
    assert all(x == 0.0 for x in out[1])
    assert len(out[2]) == 384
    # Different inputs produce different stub vectors
    assert out[0] != out[2]
    # Only the non-empty positions go over the wire, in one batch
    assert len(stub.calls) == 1
    assert stub.calls[0]["json"]["inputs"] == ["hello world", "another sentence"]


def test_embed_texts_empty_list(monkeypatch):
    from src.services.embedder import embed_texts

    stub = _install_stub(monkeypatch)
    assert embed_texts([]) == []
    assert stub.calls == []


def test_embed_texts_all_empty(monkeypatch):
    from src.services.embedder import embed_texts

    stub = _install_stub(monkeypatch)
    out = embed_texts(["", "  ", "\n"])
    assert len(out) == 3
    for vec in out:
        assert len(vec) == 384
        assert all(x == 0.0 for x in vec)
    assert stub.calls == [], "all-empty input must not hit the network"


def test_embed_text_idempotent_for_same_input(monkeypatch):
    from src.services.embedder import embed_text

    _install_stub(monkeypatch)
    a = embed_text("rotate an API key")
    b = embed_text("rotate an API key")
    assert a == b


def test_embed_texts_single_item(monkeypatch):
    from src.services.embedder import embed_texts

    stub = _install_stub(monkeypatch)
    out = embed_texts(["only one chunk here"])
    assert len(out) == 1
    assert len(out[0]) == 384
    assert len(stub.calls) == 1


def test_embed_dim_overridable_via_env(monkeypatch):
    """Allow upgrading to a different model with a different vector size."""
    monkeypatch.setenv("EMBEDDING_DIM", "768")
    from src.services.embedder import embed_text

    _install_stub(monkeypatch, dim=768)
    vec = embed_text("test")
    assert len(vec) == 768

    # Empty short-circuit also honors the configured dim
    zero = embed_text("")
    assert len(zero) == 768
    assert all(x == 0.0 for x in zero)


def test_embed_texts_chunks_into_batches(monkeypatch):
    """535-chunk PDFs were failing with HTTP 413; embed_texts must batch under EMBEDDING_BATCH_SIZE."""
    from src.services import embedder as emb

    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "10")
    captured_batches: list[int] = []

    def fake_post(inputs):
        captured_batches.append(len(inputs))
        return [[0.0] * emb._embedding_dim() for _ in inputs]

    monkeypatch.setattr(emb, "_post_embed", fake_post)
    out = emb.embed_texts([f"chunk-{i}" for i in range(25)])
    assert len(out) == 25
    # 25 chunks at batch=10 -> [10, 10, 5]
    assert captured_batches == [10, 10, 5]
