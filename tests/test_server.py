from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("multipart")

from fastapi.testclient import TestClient

from omnirag.config import Settings
from omnirag.generate.llm import LLM
from omnirag.health import Probe
from omnirag.index.knowledge_base import KnowledgeBase
from omnirag.server import app as app_module
from omnirag.server.app import create_app, safe_filename

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000100e221bc330000000049454e44ae426082"
)


@pytest.fixture
def client(tmp_path, settings):
    app = create_app(home=tmp_path / "srv", default_kb="demo", settings=settings)
    with TestClient(app) as c:
        yield c


def make_client(tmp_path, **overrides) -> TestClient:
    settings = Settings(home=tmp_path / "home").with_overrides(**overrides)
    return TestClient(create_app(home=tmp_path / "srv", default_kb="demo", settings=settings))


def sse_events(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = block.splitlines()
        name = next(line[7:] for line in lines if line.startswith("event: "))
        data = json.loads("\n".join(line[6:] for line in lines if line.startswith("data: ")))
        events.append((name, data))
    return events


# ------------------------------------------------------------------ basics
def test_index_page_and_health(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "OmniRAG" in page.text
    assert 'name="omnirag-default-kb" content="demo"' in page.text
    assert "__VERSION__" not in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-content-type-options"] == "nosniff"
    health = client.get("/api/health").json()
    assert health["status"] == "ok" and health["auth_required"] is False


def built_assets(page: str) -> list[str]:
    """The hashed script and stylesheet paths the built index.html references."""
    return re.findall(r'(?:src|href)="(/static/assets/[^"]+\.(?:js|css))"', page)


def test_static_assets_and_traversal(client):
    for asset in ("favicon.svg", "theme-init.js"):
        r = client.get(f"/static/{asset}")
        assert r.status_code == 200, asset
        assert r.headers["cache-control"] == "no-cache"
    assets = built_assets(client.get("/").text)
    assert any(a.endswith(".js") for a in assets) and any(a.endswith(".css") for a in assets)
    for asset in assets:
        r = client.get(asset)
        assert r.status_code == 200, asset
        assert "immutable" in r.headers["cache-control"]
    assert "fonts.googleapis.com" not in client.get("/").headers["content-security-policy"]
    for path in ("/static/../app.py", "/static/%2e%2e/app.py", "/static/..%2fapp.py"):
        r = client.get(path)
        assert r.status_code == 404 or "create_app" not in r.text, path


def test_ingest_query_stats_preview(client, corpus):
    r = client.post("/api/ingest", json={"paths": [str(corpus)], "kb": "demo"})
    assert r.status_code == 200, r.text
    assert len(r.json()["added"]) == 10

    kbs = client.get("/api/kbs").json()
    assert kbs[0]["name"] == "demo" and kbs[0]["documents"] == 10 and kbs[0]["is_default"]

    stats = client.get("/api/kbs/demo/stats").json()
    assert stats["chunks"] > 0
    assert client.get("/api/stats", params={"kb": "demo"}).json() == stats

    q = client.post(
        "/api/query", json={"query": "How are refresh tokens rotated?", "kb": "demo", "llm": "none"}
    )
    assert q.status_code == 200, q.text
    body = q.json()
    assert body["backend"] == "extractive" and body["cited"]
    assert len(body["sources"]) == 5  # KB default top_k
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
    assert raw.headers["content-type"].startswith("image/")
    assert "sandbox" in raw.headers["content-security-policy"]

    docs = client.get("/api/kbs/demo/documents").json()
    assert len(docs) == 10
    doc = docs[0]
    assert {"name", "size_bytes", "created_at", "updated_at", "uploaded", "missing"} <= set(doc)
    assert doc["size_bytes"] > 0 and doc["uploaded"] is False and doc["missing"] is False

    html_doc = next(d for d in docs if d["name"] == "runbook.html")
    raw_html = client.get(f"/api/kbs/demo/documents/{html_doc['doc_id']}/raw")
    assert raw_html.headers["content-type"].startswith("text/plain")  # never rendered as HTML


def test_error_responses(client):
    assert client.get("/api/kbs/missing/stats").status_code == 404
    assert client.post("/api/query", json={"query": "x", "kb": "missing"}).status_code == 404
    assert client.post("/api/query", json={"query": ""}).status_code == 422
    assert client.post("/api/kbs", json={"name": "fresh"}).status_code == 201
    assert client.post("/api/kbs", json={"name": "fresh"}).status_code == 400
    assert client.post("/api/kbs", json={"name": "../evil"}).status_code == 400
    bad = client.post("/api/query", json={"query": "x", "kb": "fresh", "modalities": ["video"]})
    assert bad.status_code == 400
    missing = str(Path(__file__).parent / "definitely-missing")
    assert client.post("/api/ingest", json={"paths": [missing], "kb": "fresh"}).status_code == 400
    assert client.get("/api/kbs/fresh/chunks/nope").status_code == 404
    assert client.get("/api/kbs/fresh/documents/nope/raw").status_code == 404
    assert client.get("/api/kbs/fresh/documents/..%2F..%2Fkb.json/raw").status_code == 404
    assert client.delete("/api/kbs/fresh/documents/nope").status_code == 404
    assert client.post("/api/kbs/fresh/documents/nope/reingest").status_code == 404
    assert (
        client.post("/api/query", json={"query": "x", "kb": "fresh", "llm": "bogus"}).status_code
        == 400
    )


# --------------------------------------------------------------- KB CRUD
def test_kb_crud(client):
    assert client.get("/api/kbs").json() == []
    created = client.post("/api/kbs", json={"name": "notes", "description": " Team notes "})
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "notes" and body["description"] == "Team notes"
    assert body["documents"] == 0 and body["is_default"] is False
    assert client.get("/api/kbs/notes").json()["embedder"].startswith("hashing")
    assert [k["name"] for k in client.get("/api/kbs").json()] == ["notes"]

    client.post("/api/kbs/notes/upload", files={"files": ("a.md", b"# A\n\nalpha beta")})
    deleted = client.delete("/api/kbs/notes")
    assert deleted.status_code == 200 and deleted.json() == {"deleted": "notes"}
    assert client.get("/api/kbs/notes").status_code == 404
    assert client.get("/api/kbs").json() == []
    assert client.delete("/api/kbs/notes").status_code == 404
    # The name can be reused after deletion.
    assert client.post("/api/kbs", json={"name": "notes"}).status_code == 201


def test_kb_settings(client):
    client.post("/api/kbs", json={"name": "demo"})
    assert client.get("/api/kbs/demo/settings").json() == {
        "llm": "",
        "model": "",
        "base_url": "",
        "top_k": 5,
    }
    saved = client.put(
        "/api/kbs/demo/settings",
        json={"llm": "ollama", "model": "qwen2.5:7b", "base_url": "http://gpu:11434/", "top_k": 8},
    )
    assert saved.status_code == 200
    assert saved.json()["base_url"] == "http://gpu:11434"
    assert client.get("/api/kbs/demo/settings").json()["top_k"] == 8
    assert client.put("/api/kbs/demo/settings", json={"llm": "nope"}).status_code == 400
    assert client.put("/api/kbs/demo/settings", json={"base_url": "file:///x"}).status_code == 400
    assert client.put("/api/kbs/demo/settings", json={"top_k": 99}).status_code == 422
    assert client.get("/api/kbs/missing/settings").status_code == 404


# ----------------------------------------------------------------- uploads
def test_upload_ingest_delete_reingest(client):
    client.post("/api/kbs", json={"name": "up"})
    md = b"# Certificates\n\nTLS certificates expire every 90 days. Renewal runs nightly."
    r = client.post(
        "/api/kbs/up/upload",
        files=[
            ("files", ("../../escape/notes.md", md, "text/markdown")),
            ("files", ("pixel.png", PNG_1PX, "image/png")),
        ],
    )
    assert r.status_code == 200, r.text
    files = {f["name"]: f for f in r.json()["files"]}
    assert set(files) == {"notes.md", "pixel.png"}
    assert files["notes.md"]["status"] == "added" and files["notes.md"]["chunks"] >= 1
    assert files["notes.md"]["size_bytes"] == len(md)
    assert files["pixel.png"]["status"] == "added"

    kb_dir = Path(client.get("/api/kbs/up/stats").json()["path"])
    uploads = kb_dir / "uploads"
    assert (uploads / "notes.md").read_bytes() == md
    assert not (kb_dir.parent / "escape").exists()

    # Same content again: recognised as unchanged.
    again = client.post("/api/kbs/up/upload", files={"files": ("notes.md", md)})
    assert again.json()["files"][0]["status"] == "unchanged"

    docs = {d["name"]: d for d in client.get("/api/kbs/up/documents").json()}
    assert docs["notes.md"]["uploaded"] is True and docs["notes.md"]["path"] == "notes.md"

    answer = client.post("/api/query", json={"query": "When do certificates expire?", "kb": "up"})
    assert "90 days" in answer.json()["answer"]

    reingested = client.post(f"/api/kbs/up/documents/{docs['notes.md']['doc_id']}/reingest")
    assert reingested.status_code == 200, reingested.text
    assert reingested.json()["report"]["updated"]
    assert reingested.json()["document"]["path"] == "notes.md"

    gone = client.delete(f"/api/kbs/up/documents/{docs['notes.md']['doc_id']}")
    assert gone.status_code == 200 and gone.json()["removed_file"] is True
    assert not (uploads / "notes.md").exists()
    assert [d["name"] for d in client.get("/api/kbs/up/documents").json()] == ["pixel.png"]

    # A document whose file vanished cannot be re-ingested.
    (uploads / "pixel.png").unlink()
    missing = client.post(f"/api/kbs/up/documents/{docs['pixel.png']['doc_id']}/reingest")
    assert missing.status_code == 410
    listed = client.get("/api/kbs/up/documents").json()
    assert listed[0]["missing"] is True and listed[0]["size_bytes"] is None


def test_upload_rejects_unsupported_and_missing_kb(client):
    client.post("/api/kbs", json={"name": "up"})
    r = client.post("/api/kbs/up/upload", files={"files": ("setup.exe", b"MZ")})
    assert r.status_code == 415
    r = client.post("/api/kbs/up/upload", files={"files": ("noext", b"hello")})
    assert r.status_code == 415
    assert client.get("/api/kbs/up/documents").json() == []
    r = client.post("/api/kbs/nope/upload", files={"files": ("a.md", b"x")})
    assert r.status_code == 404


def test_upload_size_limit(tmp_path):
    with make_client(tmp_path, max_upload_mb=0.01) as client:  # ~10 KB
        client.post("/api/kbs", json={"name": "up"})
        small = client.post("/api/kbs/up/upload", files={"files": ("ok.txt", b"small file")})
        assert small.status_code == 200
        big = client.post("/api/kbs/up/upload", files={"files": ("big.txt", b"x" * 200_000)})
        assert big.status_code == 413
        assert "limit" in big.json()["detail"]
        names = [d["name"] for d in client.get("/api/kbs/up/documents").json()]
        assert names == ["ok.txt"]
        assert client.get("/api/status").json()["max_upload_mb"] == 0.01


def test_safe_filename():
    assert safe_filename("../../etc/passwd.md") == "passwd.md"
    assert safe_filename("C:\\Users\\me\\notes.txt") == "notes.txt"
    assert safe_filename("we<ird>|name?.py") == "we_ird_name_.py"
    assert safe_filename("résumé.pdf") == "résumé.pdf"
    assert safe_filename("CON.txt") == "_CON.txt"
    assert safe_filename("...") == ""
    long = safe_filename("a" * 300 + ".md")
    assert len(long) == 150 and long.endswith(".md")


# --------------------------------------------------------------------- SSE
def test_query_stream_extractive(client, corpus):
    client.post("/api/ingest", json={"paths": [str(corpus)], "kb": "demo"})
    with client.stream(
        "POST", "/api/query/stream", json={"query": "How does the token bucket refill?", "top_k": 3}
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        text = "".join(r.iter_text())
    events = sse_events(text)
    names = [e for e, _ in events]
    assert names[0] == "sources" and names[-1] == "done"
    assert names.count("delta") > 3
    assert len(events[0][1]["sources"]) == 3
    done = events[-1][1]
    streamed = "".join(d["text"] for e, d in events if e == "delta")
    assert done["answer"] == streamed.strip()
    assert done["backend"] == "extractive" and done["cited"]
    assert done["timings"]["total_ms"] > 0


def test_query_stream_with_llm_and_errors(client, corpus, monkeypatch):
    client.post("/api/ingest", json={"paths": [str(corpus)], "kb": "demo"})

    class FakeLLM(LLM):
        name = "fake:model"

        def complete(self, messages, temperature=0.1, max_tokens=800):
            return "unused"

        def stream(self, messages, temperature=0.1, max_tokens=800):
            yield "Refresh tokens rotate [1]"
            yield " on every use [42]."

    monkeypatch.setattr(KnowledgeBase, "default_llm", lambda self: FakeLLM())
    r = client.post("/api/query/stream", json={"query": "refresh token rotation"})
    events = sse_events(r.text)
    assert [d["text"] for e, d in events if e == "delta"] == [
        "Refresh tokens rotate [1]",
        " on every use [42].",
    ]
    done = events[-1][1]
    assert done["backend"] == "fake:model"
    assert done["answer"] == "Refresh tokens rotate [1] on every use."
    assert done["cited"] == [1]

    assert client.post("/api/query/stream", json={"query": "x", "kb": "nope"}).status_code == 404
    assert (
        client.post("/api/query/stream", json={"query": "x", "modalities": ["video"]}).status_code
        == 400
    )
    assert client.post("/api/query/stream", json={"query": "x", "mode": "magic"}).status_code == 400
    assert client.post("/api/query/stream", json={"query": "x", "llm": "bogus"}).status_code == 400


def _doc_id(client, name: str) -> str:
    docs = client.get("/api/kbs/demo/documents").json()
    return next(d["doc_id"] for d in docs if d["name"] == name)


def test_query_scoped_to_selected_documents(client, corpus):
    client.post("/api/ingest", json={"paths": [str(corpus)], "kb": "demo"})
    rate = _doc_id(client, "rate-limiting.md")
    code = _doc_id(client, "rate_limiter.py")

    # Unscoped, this question is answered from the authentication docs.
    body = {"query": "How do refresh tokens work?", "top_k": 4}
    free = client.post("/api/query", json=body).json()
    assert any(s["doc_id"] not in {rate, code} for s in free["sources"])

    scoped = client.post("/api/query", json={**body, "doc_ids": [rate, code]}).json()
    assert scoped["sources"]
    assert {s["doc_id"] for s in scoped["sources"]} <= {rate, code}
    assert scoped["query"]["filters"]["doc_ids"] == [rate, code]

    with client.stream("POST", "/api/query/stream", json={**body, "doc_ids": [rate]}) as r:
        events = sse_events("".join(r.iter_text()))
    assert {s["doc_id"] for s in events[0][1]["sources"]} == {rate}
    assert events[-1][0] == "done"
    assert {s["doc_id"] for s in events[-1][1]["sources"]} == {rate}

    # Ids that exist nowhere simply match nothing; malformed ids are rejected.
    none = client.post("/api/query", json={**body, "doc_ids": ["0" * 16]}).json()
    assert none["sources"] == []
    bad = client.post("/api/query", json={**body, "doc_ids": ["../etc"]})
    assert bad.status_code == 400 and "doc_ids" in bad.json()["detail"]
    bad = client.post("/api/query/stream", json={**body, "doc_ids": ["a b"]})
    assert bad.status_code == 400


def test_related_questions(client, corpus):
    client.post("/api/ingest", json={"paths": [str(corpus)], "kb": "demo"})

    starters = client.post("/api/kbs/demo/related", json={"limit": 5}).json()["questions"]
    assert len(starters) == 5
    assert len({q["doc_id"] for q in starters}) == 5  # one per document
    assert len({q["modality"] for q in starters}) >= 4  # spread across modalities
    assert all(q["question"] and q["source"] for q in starters)

    question = "How do refresh tokens work?"
    answer = client.post("/api/query", json={"query": question, "top_k": 4}).json()
    used = [s["chunk_id"] for s in answer["sources"]]
    related = client.post(
        "/api/kbs/demo/related", json={"query": question, "chunk_ids": used}
    ).json()["questions"]
    assert 1 <= len(related) <= 4
    assert not {q["chunk_id"] for q in related} & set(used)
    # The first suggestion is a sibling section of the document the answer used.
    auth = _doc_id(client, "authentication.md")
    assert related[0]["doc_id"] == auth
    # A sibling section of the same document (which one depends on retrieval).
    assert related[0]["question"].startswith("What does Authentication say about ")
    assert len({q["question"] for q in related}) == len(related)

    rate = _doc_id(client, "rate-limiting.md")
    scoped = client.post(
        "/api/kbs/demo/related",
        json={"query": "limits", "chunk_ids": used, "doc_ids": [rate]},
    ).json()["questions"]
    assert scoped and all(q["doc_id"] == rate for q in scoped)

    assert client.post("/api/kbs/demo/related", json={"chunk_ids": ["x/y"]}).status_code == 400
    assert client.post("/api/kbs/demo/related", json={"limit": 0}).status_code == 422
    assert client.post("/api/kbs/nope/related", json={}).status_code == 404


# ------------------------------------------------------------------ status
def test_status_extractive(client):
    s = client.get("/api/status").json()
    assert s["kb"] is None and s["embedder"] is None
    assert s["llm"]["backend"] == "none" and s["llm"]["reachable"] is None
    assert ".md" in s["upload_extensions"] and ".exe" not in s["upload_extensions"]
    client.post("/api/kbs", json={"name": "demo"})
    s = client.get("/api/status", params={"kb": "demo"}).json()
    assert s["kb"] == "demo"
    assert s["embedder"]["spec"].startswith("hashing") and s["embedder"]["offline"] is True
    assert s["llm"]["source"] == "server"
    assert s["defaults"]["ollama"]["model"]


def test_status_probes_configured_backend(client, monkeypatch):
    calls = []

    def fake_probe(spec, settings, timeout=2.0):
        calls.append((spec, settings.openai_base_url))
        return Probe(
            "openai", settings.openai_base_url, True, "2 model(s) listed", 12.5, ["m1", "m2"]
        )

    monkeypatch.setattr(app_module, "probe_llm", fake_probe)
    client.post("/api/kbs", json={"name": "demo"})
    client.put(
        "/api/kbs/demo/settings",
        json={"llm": "openai", "model": "m1", "base_url": "http://local:1234/v1"},
    )
    llm = client.get("/api/status", params={"kb": "demo"}).json()["llm"]
    assert calls == [("openai:m1", "http://local:1234/v1")]
    assert llm == {
        "backend": "openai",
        "model": "m1",
        "base_url": "http://local:1234/v1",
        "source": "kb",
        "reachable": True,
        "detail": "2 model(s) listed",
        "latency_ms": 12.5,
        "models": ["m1", "m2"],
    }
    skipped = client.get("/api/status", params={"kb": "demo", "probe": False}).json()["llm"]
    assert skipped["reachable"] is None and len(calls) == 1


# -------------------------------------------------------------------- auth
def test_api_key_auth(tmp_path):
    with make_client(tmp_path, api_key="s3cret") as client:
        health = client.get("/api/health")
        assert health.status_code == 200 and health.json()["auth_required"] is True
        assert client.get("/").status_code == 200
        page = client.get("/").text
        assert all(client.get(a).status_code == 200 for a in built_assets(page))
        denied = client.get("/api/kbs")
        assert denied.status_code == 401
        assert denied.json()["detail"] == "missing or invalid API key"
        assert client.get("/api/kbs", headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.get("/api/kbs", headers={"X-API-Key": "s3cret"}).status_code == 200
        bearer = {"Authorization": "Bearer s3cret"}
        assert client.post("/api/kbs", json={"name": "k"}, headers=bearer).status_code == 201
        assert client.post("/api/query/stream", json={"query": "x", "kb": "k"}).status_code == 401
        assert (
            client.post(
                "/api/kbs/k/upload", files={"files": ("a.md", b"# a")}, headers=bearer
            ).status_code
            == 200
        )
        assert (
            client.post("/api/kbs/k/upload", files={"files": ("a.md", b"# a")}).status_code == 401
        )


def test_cors_is_off_by_default_and_configurable(tmp_path, client):
    preflight = {
        "Origin": "http://app.example",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-api-key,content-type",
    }
    r = client.get("/api/health", headers={"Origin": "http://app.example"})
    assert "access-control-allow-origin" not in r.headers

    with make_client(tmp_path, cors_origins=("http://app.example",), api_key="k") as cors_client:
        r = cors_client.options("/api/query", headers=preflight)
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == "http://app.example"
        assert "x-api-key" in r.headers["access-control-allow-headers"].lower()
        denied = cors_client.get("/api/kbs", headers={"Origin": "http://app.example"})
        assert denied.status_code == 401
        assert denied.headers["access-control-allow-origin"] == "http://app.example"
        other = cors_client.get("/api/health", headers={"Origin": "http://evil.example"})
        assert "access-control-allow-origin" not in other.headers


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("OMNIRAG_API_KEY", "abc")
    monkeypatch.setenv("OMNIRAG_CORS_ORIGINS", "http://a.test, http://b.test/")
    monkeypatch.setenv("OMNIRAG_MAX_UPLOAD_MB", "5")
    s = Settings.from_env()
    assert s.api_key == "abc"
    assert s.cors_origins == ("http://a.test", "http://b.test")
    assert s.max_upload_mb == 5.0
