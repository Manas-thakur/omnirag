from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from omnirag.server.app import create_app


@pytest.fixture
def client(tmp_path, settings):
    app = create_app(home=tmp_path / "srv", default_kb="demo", settings=settings)
    with TestClient(app) as c:
        yield c


def test_index_page_and_health(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "OmniRAG" in page.text and 'DEFAULT_KB = "demo"' in page.text
    assert client.get("/api/health").json()["status"] == "ok"


def test_ingest_query_stats_preview(client, corpus):
    r = client.post("/api/ingest", json={"paths": [str(corpus)], "kb": "demo"})
    assert r.status_code == 200, r.text
    assert len(r.json()["added"]) == 10

    kbs = client.get("/api/kbs").json()
    assert kbs[0]["name"] == "demo" and kbs[0]["documents"] == 10

    stats = client.get("/api/kbs/demo/stats").json()
    assert stats["chunks"] > 0
    assert client.get("/api/stats", params={"kb": "demo"}).json() == stats

    q = client.post(
        "/api/query", json={"query": "How are refresh tokens rotated?", "kb": "demo", "llm": "none"}
    )
    assert q.status_code == 200, q.text
    body = q.json()
    assert body["backend"] == "extractive" and body["cited"]
    src = body["sources"][0]

    chunk = client.get(f"/api/kbs/demo/chunks/{src['chunk_id']}").json()
    assert chunk["content"] == src["content"]
    assert "before" in chunk and "after" in chunk

    img = client.post(
        "/api/query",
        json={"query": "diagram", "kb": "demo", "llm": "none", "modalities": ["image"]},
    ).json()
    assert img["sources"] and all(s["modality"] == "image" for s in img["sources"])
    raw = client.get(f"/api/kbs/demo/documents/{img['sources'][0]['doc_id']}/raw")
    assert raw.status_code == 200 and len(raw.content) > 100

    docs = client.get("/api/kbs/demo/documents").json()
    assert len(docs) == 10


def test_error_responses(client):
    assert client.get("/api/kbs/missing/stats").status_code == 404
    assert client.post("/api/query", json={"query": "x", "kb": "missing"}).status_code == 404
    assert client.post("/api/query", json={"query": ""}).status_code == 422
    assert client.post("/api/kbs", json={"name": "fresh"}).status_code == 201
    assert client.post("/api/kbs", json={"name": "fresh"}).status_code == 400
    bad = client.post("/api/query", json={"query": "x", "kb": "fresh", "modalities": ["video"]})
    assert bad.status_code == 400
    assert (
        client.post(
            "/api/ingest", json={"paths": ["/definitely/missing"], "kb": "fresh"}
        ).status_code
        == 400
    )
    assert client.get("/api/kbs/fresh/chunks/nope").status_code == 404
    assert client.get("/api/kbs/fresh/documents/nope/raw").status_code == 404
