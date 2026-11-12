from __future__ import annotations

import numpy as np
import pytest

from omnirag.embed import HashingEmbedder
from omnirag.store import Chunk, Document, LocalStore, Modality, SearchFilters

EMB = HashingEmbedder(256)


def make_doc(doc_id: str, source: str, modality: Modality, texts: list[str], **meta):
    doc = Document(doc_id, source, modality, content_hash="h-" + doc_id, title=doc_id)
    vecs = EMB.embed_documents(texts)
    chunks = [
        Chunk(
            chunk_id=f"{doc_id}-{i}",
            doc_id=doc_id,
            content=t,
            modality=modality,
            source=source,
            position=i,
            metadata=dict(meta),
            embedding=vecs[i],
        )
        for i, t in enumerate(texts)
    ]
    return doc, chunks


@pytest.fixture
def store(tmp_path):
    s = LocalStore(tmp_path / "store.sqlite")
    s.upsert_document(
        *make_doc(
            "d1",
            "/kb/docs/auth.md",
            Modality.TEXT,
            ["JWT tokens authenticate users", "refresh tokens rotate", "roles control access"],
        )
    )
    s.upsert_document(
        *make_doc(
            "d2",
            "/kb/src/limiter.py",
            Modality.CODE,
            ["class TokenBucket rate limiter"],
            language="python",
        )
    )
    s.upsert_document(
        *make_doc("d3", "/kb/data/latency.csv", Modality.TABLE, ["p95 latency per endpoint"])
    )
    yield s
    s.close()


def test_documents_and_chunks_roundtrip(store):
    assert store.get_document("d1").chunk_count == 3
    assert store.get_document_by_source("/kb/src/limiter.py").doc_id == "d2"
    assert [d.doc_id for d in store.list_documents(Modality.CODE)] == ["d2"]
    chunk = store.get_chunk("d1-1")
    assert chunk.content == "refresh tokens rotate"
    assert [c.position for c in store.get_document_chunks("d1")] == [0, 1, 2]
    assert store.dimension == 256


def test_dense_search_ranks_relevant_first(store):
    hits = store.search(EMB.embed_query("token bucket rate limiter"), k=2)
    assert hits[0].chunk.chunk_id == "d2-0"
    assert hits[0].score >= hits[1].score


def test_search_filters(store):
    q = EMB.embed_query("tokens")
    code_only = store.search(q, k=10, filters=SearchFilters(modalities=[Modality.CODE]))
    assert {h.chunk.modality for h in code_only} == {Modality.CODE}
    no_text = store.search(q, k=10, filters=SearchFilters(exclude_modalities=[Modality.TEXT]))
    assert all(h.chunk.modality != Modality.TEXT for h in no_text)
    by_glob = store.search(q, k=10, filters=SearchFilters(sources=["*.csv"]))
    assert [h.chunk.doc_id for h in by_glob] == ["d3"]
    by_substring = store.search(q, k=10, filters=SearchFilters(sources=["docs/"]))
    assert {h.chunk.doc_id for h in by_substring} == {"d1"}
    by_meta = store.search(q, k=10, filters=SearchFilters(metadata={"language": "PYTHON"}))
    assert [h.chunk.doc_id for h in by_meta] == ["d2"]
    nothing = store.search(q, k=10, filters=SearchFilters(doc_ids=["missing"]))
    assert nothing == []


def test_neighbors(store):
    middle = store.get_chunk("d1-1")
    before, after = store.neighbors(middle, 1)
    assert [c.chunk_id for c in before] == ["d1-0"]
    assert [c.chunk_id for c in after] == ["d1-2"]
    assert store.neighbors(middle, 0) == ([], [])


def test_upsert_replaces_chunks_and_bumps_revision(store):
    rev = store.revision
    store.upsert_document(
        *make_doc("d1", "/kb/docs/auth.md", Modality.TEXT, ["only one chunk now"])
    )
    assert store.revision > rev
    assert store.get_document("d1").chunk_count == 1
    assert store.get_chunk("d1-2") is None
    assert len(store.all_chunks()) == 3


def test_delete_document(store):
    assert store.delete_document("d3")
    assert not store.delete_document("d3")
    assert store.get_chunk("d3-0") is None
    assert store.count_chunks() == 4


def test_dimension_mismatch_is_rejected(store):
    doc = Document("d9", "/kb/x.md", Modality.TEXT, "h")
    bad = Chunk("d9-0", "d9", "x", Modality.TEXT, embedding=np.ones(8, dtype=np.float32))
    with pytest.raises(ValueError):
        store.upsert_document(doc, [bad])
    with pytest.raises(ValueError):
        store.search(np.ones(8, dtype=np.float32))


def test_persistence_and_stats(tmp_path, store):
    stats = store.stats()
    assert stats.documents == 3 and stats.chunks == 5
    assert stats.by_modality == {"text": 3, "code": 1, "table": 1}
    assert stats.storage_bytes > 0
    store.close()
    reopened = LocalStore(store.path)
    assert reopened.count_chunks() == 5
    assert reopened.search(EMB.embed_query("latency"), k=1)[0].chunk.doc_id == "d3"
    reopened.close()


def test_update_embeddings(store):
    new = HashingEmbedder(64)
    vectors = {c.chunk_id: new.embed_documents([c.content])[0] for c in store.iter_chunks()}
    store.update_embeddings(vectors, 64)
    assert store.dimension == 64
    assert store.search(new.embed_query("latency"), k=1)[0].chunk.doc_id == "d3"


def test_modality_parse_aliases():
    assert Modality.parse("images") is Modality.IMAGE
    assert Modality.parse("transcript") is Modality.AUDIO
    assert Modality.parse(Modality.CODE) is Modality.CODE
    with pytest.raises(ValueError):
        Modality.parse("video")
