import time

import pytest
from starlette.testclient import TestClient

from app import agents
from app.safety import TopicCheck
from app.server import DebateManager, create_app
from app.state import Phase
from tests.test_orchestrator import FakeLLM, FakeResearch, FakeTTS


class ServerFakeLLM(FakeLLM):
    def structured(self, model, system, user, schema):
        if schema is TopicCheck:
            return TopicCheck(is_tech=True, reason=" clearly about software ")
        return super().structured(model, system, user, schema)


def _make_client(cfg, tmp_path, llm_cls=ServerFakeLLM):
    cfg = cfg.model_copy(
        update={
            "services": cfg.services.model_copy(
                update={"out_dir": tmp_path / "out", "cache_dir": tmp_path / "cache"}
            )
        }
    )
    mgr = DebateManager(
        cfg,
        llm_factory=lambda _c: llm_cls(),
        researcher_factory=lambda _c, _r: FakeResearch(),
        tts_factory=lambda _c: FakeTTS(),
        skip_service_wait=True,
    )
    return TestClient(create_app(mgr)), mgr


def test_get_models_and_role_swap(cfg, tmp_path, monkeypatch):
    client, _ = _make_client(cfg, tmp_path)
    r = client.get("/api/models")
    assert r.status_code == 200
    data = r.json()
    assert [m["name"] for m in data["models"]] == ["qwen3:4b", "gemma3:4b", "llama3.2:3b"]
    assert data["defaults"] == {"pro": "qwen3:4b", "con": "gemma3:4b", "judge": "llama3.2:3b"}
    assert len(data["preset_topics"]) >= 5

    # Verify cloud role swapping preserves model-to-URL bindings and model-specific think flags.
    for role, port in (("PRO", 11441), ("CON", 11442), ("JUDGE", 11443)):
        monkeypatch.setenv(f"OLLAMA_URL_{role}", f"http://h:{port}")
    from app.config import load_config

    cloud = load_config("cloud")
    swapped = cloud.with_role_models({"pro": "qwen3:14b", "con": "gpt-oss:20b", "judge": "gemma3:12b"})
    assert swapped.models.pro.name == "qwen3:14b" and swapped.models.pro.think is False
    assert swapped.models.con.name == "gpt-oss:20b" and swapped.models.con.think == "low"
    assert swapped.ollama_url_for("gpt-oss:20b") == "http://h:11441"
    assert swapped.ollama_url_for("qwen3:14b") == "http://h:11442"


def test_rejects_denylisted_topic_and_unknown_model(cfg, tmp_path):
    client, _ = _make_client(cfg, tmp_path)
    r = client.post("/api/debates", json={"topic": "Should the president win the election?"})
    assert r.status_code == 422
    assert "blocked subject" in r.json()["detail"]

    r2 = client.post(
        "/api/debates",
        json={"topic": "Rust vs Go", "models": {"pro": "not-in-catalog:7b", "con": "gemma3:4b", "judge": "llama3.2:3b"}},
    )
    assert r2.status_code == 422
    assert "Unknown model" in r2.json()["detail"]


def test_create_debate_runs_to_completion_with_live_segments(cfg, tmp_path):
    client, _ = _make_client(cfg, tmp_path)
    r = client.post(
        "/api/debates",
        json={
            "topic": "Monorepos beat polyrepos",
            "models": {"pro": "gemma3:4b", "con": "qwen3:4b", "judge": "llama3.2:3b"},
        },
    )
    assert r.status_code == 201
    run_id = r.json()["id"]

    # Wait for background worker to finish.
    deadline = time.monotonic() + 10
    detail = None
    while time.monotonic() < deadline:
        detail = client.get(f"/api/debates/{run_id}").json()
        if detail["status"] == "done":
            break
        time.sleep(0.05)

    assert detail is not None and detail["status"] == "done"
    assert detail["state"]["models"]["pro"] == "gemma3:4b"
    assert detail["state"]["models"]["con"] == "qwen3:4b"
    assert detail["has_wav"] is True
    assert len(detail["srt_cues"]) > 0
    # Intro + 8 turns + verdict = 10 live audio segments
    assert len(detail["segments"]) == 10

    seg_url = detail["segments"][0]["url"]
    assert client.get(seg_url).status_code == 200
    assert client.get(detail["audio_url"]).status_code == 200

    # Check SSE snapshot on completed debate
    sse = client.get(f"/api/debates/{run_id}/events")
    assert sse.status_code == 200
    assert "event: snapshot" in sse.text

    # Check list endpoint
    items = client.get("/api/debates").json()
    assert len(items) == 1 and items[0]["id"] == run_id and items[0]["winner"] == "pro"


def test_cancel_and_resume_debate(cfg, tmp_path):
    class SlowLLM(ServerFakeLLM):
        def structured(self, model, system, user, schema):
            if schema is agents.ClosingOut:
                time.sleep(0.4)
            return super().structured(model, system, user, schema)

    client, mgr = _make_client(cfg, tmp_path, llm_cls=SlowLLM)
    r = client.post("/api/debates", json={"topic": "Tabs vs spaces"})
    assert r.status_code == 201
    run_id = r.json()["id"]

    # Wait until openings or rebuttals complete, then cancel.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        d = client.get(f"/api/debates/{run_id}").json()
        if len(d["state"]["phases_done"]) >= 2:
            client.post(f"/api/debates/{run_id}/cancel")
            break
        time.sleep(0.02)

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        d = client.get(f"/api/debates/{run_id}").json()
        if d["status"] in ("cancelled", "interrupted", "done"):
            break
        time.sleep(0.05)

    # After a cancel the run shows exactly what was saved (no half-finished phase).
    from app.state import DebateState
    saved = DebateState.load(mgr.cfg.services.out_dir / run_id)
    assert d["status"] == "cancelled"
    assert len(d["state"]["turns"]) == len(saved.turns)
    assert d["state"]["phases_done"] == [p.value for p in saved.phases_done]

    # Now resume the cancelled run using fast LLM.
    mgr.llm_factory = lambda _c: ServerFakeLLM()
    res = client.post(f"/api/debates/{run_id}/resume", json={})
    assert res.status_code == 200

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        d = client.get(f"/api/debates/{run_id}").json()
        if d["status"] == "done":
            break
        time.sleep(0.05)

    assert Phase.DONE.value in d["state"]["phases_done"]
    # Resume backfilled every live clip: intro + 8 turns + verdict, none missing or stale.
    names = sorted(seg["filename"] for seg in d["segments"])
    assert len(names) == 10 and names[0] == "00_intro.wav" and names[-1] == "turn_07_closings_con.wav"


def test_serves_built_spa_index(cfg, tmp_path):
    client, _ = _make_client(cfg, tmp_path)
    r = client.get("/")
    assert r.status_code == 200
    assert "Tech Debate Arena" in r.text



def test_cross_origin_writes_are_rejected(cfg, tmp_path):
    client, _ = _make_client(cfg, tmp_path)
    evil = client.post("/api/debates", json={"topic": "Rust vs Go"}, headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    assert "access-control-allow-origin" not in evil.headers
    pre = client.options("/api/debates", headers={"Origin": "https://evil.example",
                                                 "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in pre.headers
    # Same origin, the Vite dev server, and non-browser clients (no Origin) are fine.
    for headers in ({"Origin": "http://testserver"}, {"Origin": "http://localhost:5173"}, {}):
        r = client.post("/api/debates", json={"topic": "Who should win the election"}, headers=headers)
        assert r.status_code == 422, headers  # reached the handler (denylist), not blocked


def test_unknown_api_paths_and_bad_ids_are_404(cfg, tmp_path):
    client, _ = _make_client(cfg, tmp_path)
    assert client.get("/api/nope").status_code == 404
    assert client.get("/api/nope").headers["content-type"].startswith("application/json")
    for rid in ["..", "not-a-run", "20261030-103507-ok"]:  # last one is well-formed but doesn't exist
        assert client.get(f"/api/debates/{rid}").status_code == 404, rid
        assert client.get(f"/api/debates/{rid}/audio/master").status_code == 404, rid
        # ".." is collapsed by the client into /api/cancel, which has no POST route (405).
        assert client.post(f"/api/debates/{rid}/cancel").status_code in (404, 405), rid
    assert client.get("/api/debates/20261030-103507-ok/audio/segments/..%2fstate.json").status_code in (400, 404)
