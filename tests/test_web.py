import json
import threading
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from edulite.model_manager import ModelManager
from edulite.storage import Store
from edulite.web.app import create_app

BASE = "http://127.0.0.1"


@pytest.fixture
def web(make_config, tmp_path):
    """A running app wired to the fake llama-server. Returns (client, manager, store)."""
    created = []

    def make(**config_overrides):
        config = make_config(**config_overrides)
        lite = replace(config.model, key="lite", name="Fake Lite")
        registry = {"default": config.model, "lite": lite}
        manager = ModelManager(config, registry=registry)
        store = Store(tmp_path / f"web{len(created)}.db")
        client = TestClient(create_app(manager, store), base_url=BASE)
        client.__enter__()
        deadline = time.time() + 10
        while manager.state == "loading" and time.time() < deadline:
            time.sleep(0.05)
        created.append((client, store))
        return client, manager, store

    yield make
    for client, store in created:
        client.__exit__(None, None, None)
        store.close()


def stream_message(client, conversation_id, content):
    events = []
    with client.stream("POST", f"/api/conversations/{conversation_id}/messages", json={"content": content}) as r:
        assert r.status_code == 200, r.read()
        event = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                events.append((event, json.loads(line[5:])))
    return events


# ------------------------------------------------------------------ basics

def test_index_status_and_security_headers(web):
    client, manager, _ = web()
    page = client.get("/")
    assert page.status_code == 200 and "EduLite" in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"]
    status = client.get("/api/status").json()
    assert status["state"] == "ready" and status["model"]["key"] == "default"
    assert {m["key"] for m in status["models"]} == {"default", "lite"}
    assert client.get("/static/vendor/highlight.min.js").status_code == 200


def test_requests_from_other_hosts_and_sites_are_refused(web):
    client, _, _ = web()
    assert client.get("/api/status", headers={"host": "evil.example"}).status_code == 400  # DNS rebinding
    assert client.post("/api/conversations", headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/conversations", headers={"origin": "http://localhost:8770"}).status_code == 201


# ----------------------------------------------------------- conversations

def test_conversation_crud(web):
    client, _, _ = web()
    c = client.post("/api/conversations").json()
    assert client.get("/api/conversations").json()[0]["id"] == c["id"]
    assert client.patch(f"/api/conversations/{c['id']}", json={"title": "Loops"}).json()["title"] == "Loops"
    assert client.get(f"/api/conversations/{c['id']}").json()["messages"] == []
    assert client.delete(f"/api/conversations/{c['id']}").status_code == 204
    assert client.get(f"/api/conversations/{c['id']}").status_code == 404
    assert client.patch("/api/conversations/999", json={"title": "x"}).status_code == 404


# --------------------------------------------------------------- chatting

def test_send_message_streams_and_saves(web, monkeypatch, tmp_path):
    record = tmp_path / "requests.jsonl"
    monkeypatch.setenv("FAKE_RECORD", str(record))
    client, _, store = web()
    c = client.post("/api/conversations").json()
    events = stream_message(client, c["id"], "What is a variable?")
    kinds = [e for e, _ in events]
    assert kinds[0] == "user" and kinds[-1] == "done" and kinds.count("token") == 6
    done = events[-1][1]
    assert done["content"] == "echo: w0 w1 w2 w3 w4" and not done["stopped"]
    assert done["stats"]["finish_reason"] == "stop"
    saved = client.get(f"/api/conversations/{c['id']}").json()
    assert saved["title"] == "What is a variable?"
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant"]

    stream_message(client, c["id"], "And a loop?")
    sent = json.loads(record.read_text().splitlines()[-1])["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]  # history included


def test_stop_saves_partial_answer_and_leaves_it_out_of_context(web, monkeypatch, tmp_path):
    record = tmp_path / "requests.jsonl"
    monkeypatch.setenv("FAKE_RECORD", str(record))
    monkeypatch.setenv("FAKE_STREAM_WORDS", "400")
    monkeypatch.setenv("FAKE_CHUNK_DELAY", "0.01")
    client, manager, _ = web()
    c = client.post("/api/conversations").json()
    result = {}
    worker = threading.Thread(target=lambda: result.update(events=stream_message(client, c["id"], "long one")))
    worker.start()
    time.sleep(0.6)
    assert client.post("/api/stop").json()["stopping"]
    worker.join(10)
    done = result["events"][-1][1]
    assert result["events"][-1][0] == "done" and done["stopped"]
    assert 0 < len(done["content"].split()) < 400
    assert not manager.generation_lock.locked()

    monkeypatch.setenv("FAKE_STREAM_WORDS", "3")
    stream_message(client, c["id"], "next")
    sent = json.loads(record.read_text().splitlines()[-1])["messages"]
    assert [m["content"] for m in sent if m["role"] == "user"] == ["long one", "next"]
    assert not any(m["role"] == "assistant" for m in sent)  # the stopped half-answer was skipped


def test_second_message_while_answering_is_refused(web):
    client, manager, _ = web()
    c = client.post("/api/conversations").json()
    with manager.generation_lock:
        r = client.post(f"/api/conversations/{c['id']}/messages", json={"content": "hi"})
    assert r.status_code == 409


def test_full_context_forgets_oldest_exchanges(web, monkeypatch):
    monkeypatch.setenv("FAKE_MAX_CHARS", "1200")  # read by the fake server at startup
    client, _, store = web()
    c = client.post("/api/conversations").json()
    for _ in range(4):
        store.add_message(c["id"], "user", "q" * 200)
        store.add_message(c["id"], "assistant", "a" * 200)
    done = stream_message(client, c["id"], "new question")[-1]
    assert done[0] == "done" and done[1]["stats"]["forgotten_exchanges"] >= 1
    # Only the model's view is trimmed; the saved history keeps everything.
    assert len(client.get(f"/api/conversations/{c['id']}").json()["messages"]) == 10


def test_message_too_long_is_rejected_and_removed(web, monkeypatch):
    monkeypatch.setenv("FAKE_MAX_CHARS", "100")
    client, _, _ = web()
    c = client.post("/api/conversations").json()
    events = stream_message(client, c["id"], "x" * 2000)
    assert events[-1][0] == "error" and "too long" in events[-1][1]["message"]
    assert client.get(f"/api/conversations/{c['id']}").json()["messages"] == []


def test_messages_refused_until_model_is_ready(web, monkeypatch):
    monkeypatch.setenv("FAKE_EXIT_ON_START", "1")
    client, manager, _ = web()
    assert manager.state == "error"
    status = client.get("/api/status").json()
    assert status["state"] == "error" and "failed to load model" in status["error"]
    c = client.post("/api/conversations").json()
    assert client.post(f"/api/conversations/{c['id']}/messages", json={"content": "hi"}).status_code == 503


def test_empty_message_rejected(web):
    client, _, _ = web()
    c = client.post("/api/conversations").json()
    assert client.post(f"/api/conversations/{c['id']}/messages", json={"content": ""}).status_code == 422


# --------------------------------------------------------------- settings

def test_settings_validation(web):
    client, _, _ = web()
    assert client.put("/api/settings", json={"context_tokens": 3000}).status_code == 422
    assert client.put("/api/settings", json={"max_tokens": 10}).status_code == 422
    assert client.put("/api/settings", json={"model": "huge"}).status_code == 422
    r = client.put("/api/settings", json={"max_tokens": 4096, "context_tokens": 4096})
    assert r.status_code == 422 and "smaller than the context" in r.json()["detail"]


def test_per_request_settings_apply_without_restart(web):
    client, manager, store = web()
    pid = manager.server.pid
    r = client.put("/api/settings", json={"max_tokens": 256, "temperature": 0.2}).json()
    assert not r["restarted"] and manager.server.pid == pid
    assert r["settings"]["max_tokens"] == 256
    assert store.get_settings()["max_tokens"] == 256  # remembered for next launch


def test_changing_model_or_context_restarts_server(web):
    client, manager, _ = web()
    pid = manager.server.pid
    r = client.put("/api/settings", json={"context_tokens": 2048}).json()
    assert r["restarted"] and r["state"] == "ready" and manager.server.pid != pid
    r = client.put("/api/settings", json={"model": "lite"}).json()
    assert r["restarted"] and r["model"]["key"] == "lite"


def test_settings_refused_while_answering(web):
    client, manager, _ = web()
    with manager.generation_lock:
        assert client.put("/api/settings", json={"context_tokens": 2048}).status_code == 409
