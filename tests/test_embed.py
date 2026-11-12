from __future__ import annotations

import httpx
import numpy as np
import pytest

from omnirag.embed import (
    CachedEmbedder,
    EmbeddingCache,
    EmbeddingError,
    HashingEmbedder,
    OllamaEmbedder,
    create_embedder,
    l2_normalize,
    normalize_spec,
)


def test_hashing_embedder_is_deterministic_and_normalised():
    emb = HashingEmbedder(512)
    a = emb.embed_documents(["the rate limiter uses a token bucket"])
    b = HashingEmbedder(512).embed_documents(["the rate limiter uses a token bucket"])
    assert a.shape == (1, 512) and a.dtype == np.float32
    np.testing.assert_allclose(a, b)
    assert np.isclose(np.linalg.norm(a[0]), 1.0)


def test_hashing_embedder_similarity_ordering():
    emb = HashingEmbedder()
    docs = emb.embed_documents(
        [
            "JWT access tokens are validated by the authentication middleware",
            "The quarterly sales report shows revenue growth in Europe",
        ]
    )
    q = emb.embed_query("how is authentication with JWT tokens validated")
    sims = docs @ q
    assert sims[0] > sims[1]


def test_hashing_char_ngrams_give_morphological_overlap():
    emb = HashingEmbedder()
    a, b, c = emb.embed_documents(["authentication", "authenticate", "spreadsheet"])
    assert float(a @ b) > float(a @ c)


def test_empty_inputs():
    emb = HashingEmbedder(64)
    assert emb.embed_documents([]).shape == (0, 64)
    assert np.allclose(emb.embed_query(""), 0)
    with pytest.raises(ValueError):
        HashingEmbedder(4)


def test_l2_normalize_handles_zero_rows():
    m = l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
    np.testing.assert_allclose(m, [[0.6, 0.8], [0.0, 0.0]])


def test_embedding_cache_roundtrip(tmp_path):
    cache = EmbeddingCache(tmp_path / "cache.sqlite")
    inner = HashingEmbedder(128)
    calls = []

    class Spy(HashingEmbedder):
        def embed_documents(self, texts):
            calls.append(list(texts))
            return super().embed_documents(texts)

    spy = Spy(128)
    emb = CachedEmbedder(spy, cache)
    first = emb.embed_documents(["alpha", "beta"])
    second = emb.embed_documents(["beta", "gamma", "alpha"])
    assert calls == [["alpha", "beta"], ["gamma"]]
    np.testing.assert_allclose(first[0], second[2])
    np.testing.assert_allclose(second[1], inner.embed_documents(["gamma"])[0])
    assert len(cache) == 3
    cache.close()
    reopened = EmbeddingCache(tmp_path / "cache.sqlite")
    assert len(reopened.get_many(spy.name, ["alpha", "gamma", "missing"])) == 2
    reopened.clear()
    assert len(reopened) == 0
    reopened.close()


def test_factory_and_specs():
    assert normalize_spec("hashing") == "hashing:2048"
    assert normalize_spec("sentence-transformers:foo") == "st:foo"
    assert create_embedder("hashing:256").dimension == 256
    assert isinstance(create_embedder("ollama:nomic-embed-text"), OllamaEmbedder)
    with pytest.raises(EmbeddingError):
        create_embedder("bogus:x")


def test_ollama_embedder_with_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embed"
        import json

        body = json.loads(request.content)
        return httpx.Response(200, json={"embeddings": [[1.0, 0.0, 0.0]] * len(body["input"])})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    emb = OllamaEmbedder("m", "http://ollama.test", client=client)
    out = emb.embed_documents(["a", "b"])
    assert out.shape == (2, 3)
    assert emb.dimension == 3


def test_ollama_embedder_errors_are_wrapped():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(EmbeddingError):
        OllamaEmbedder("m", "http://ollama.test", client=client).embed_documents(["a"])
