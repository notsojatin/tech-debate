import json

import httpx
import pytest

from app import llm, model_init
from app.agents import ClosingOut
from app.config import ModelCfg, load_config


def test_cloud_overlay_replaces_models_keeps_rest(cfg):
    cloud = load_config("cloud")
    assert [cloud.models.for_role(r).name for r in ("pro", "con", "judge")] == [
        "gpt-oss:20b", "qwen3:14b", "gemma3:12b"]
    assert cloud.models.pro.think == "low" and cloud.models.con.think is False and cloud.models.judge.think is None
    assert cloud.llm.keep_alive == -1 and cloud.llm.warm_up is True
    # Everything not in the overlay comes from debate.yaml.
    assert cloud.debate.rebuttal_rounds == cfg.debate.rebuttal_rounds
    assert cloud.llm.seed == cfg.llm.seed and cloud.voices == cfg.voices
    assert cfg.llm.warm_up is False  # local default unchanged


def test_profile_from_env(monkeypatch):
    monkeypatch.setenv("DEBATE_PROFILE", "cloud")
    assert load_config().models.pro.name == "gpt-oss:20b"


def test_role_urls_and_fallback(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://local:11434/")
    monkeypatch.setenv("OLLAMA_URL_PRO", "http://h:11441/")
    monkeypatch.setenv("OLLAMA_URL_CON", "")  # empty means "not set"
    c = load_config("cloud")
    assert c.ollama_url_for("gpt-oss:20b") == "http://h:11441"
    assert c.ollama_url_for("qwen3:14b") == "http://local:11434"
    assert c.ollama_url_for("not-configured:1b") == "http://local:11434"


def test_legacy_think_capable():
    assert ModelCfg(name="m", think_capable=True).think is False
    assert ModelCfg(name="m", think_capable=False).think is None
    assert ModelCfg(name="m", think="low").think == "low"


def test_client_routes_each_model_to_its_url(monkeypatch):
    for role, port in (("PRO", 1), ("CON", 2), ("JUDGE", 3)):
        monkeypatch.setenv(f"OLLAMA_URL_{role}", f"http://h:{port}")
    client = llm.OllamaClient(load_config("cloud"))
    assert str(client.client_for("gpt-oss:20b").base_url) == "http://h:1"
    assert str(client.client_for("gemma3:12b").base_url) == "http://h:3"
    assert client.client_for("gpt-oss:20b") is client.client_for("gpt-oss:20b")


def test_think_value_sent(cfg):
    sent = []

    def handler(req):
        sent.append(json.loads(req.content))
        return httpx.Response(200, json={"message": {"content": '{"text": "ok"}'}})

    client = llm.OllamaClient(load_config("cloud"), http=httpx.Client(transport=httpx.MockTransport(handler),
                                                                     base_url="http://x"))
    c = load_config("cloud")
    client.structured(c.models.pro, "s", "u", ClosingOut)
    client.structured(c.models.judge, "s", "u", ClosingOut)
    assert sent[0]["think"] == "low" and sent[0]["keep_alive"] == -1
    assert "think" not in sent[1]


def _fake_httpx(monkeypatch, calls):
    real = httpx.Client

    def handler(req):
        calls.append((req.url.host, req.url.port, req.url.path, req.content and json.loads(req.content)))
        return httpx.Response(200, json={"version": "x"})

    monkeypatch.setattr(llm.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def test_prepare_models_warms_every_url(monkeypatch):
    for role, port in (("PRO", 11441), ("CON", 11442), ("JUDGE", 11443)):
        monkeypatch.setenv(f"OLLAMA_URL_{role}", f"http://h:{port}")
    calls = []
    _fake_httpx(monkeypatch, calls)
    took = llm.prepare_models(load_config("cloud"), log=lambda *_: None)
    assert set(took) == {"gpt-oss:20b", "qwen3:14b", "gemma3:12b"}
    gens = {(port, body["model"]) for _, port, path, body in calls if path == "/api/generate"}
    assert gens == {(11441, "gpt-oss:20b"), (11442, "qwen3:14b"), (11443, "gemma3:12b")}
    assert all(body["keep_alive"] == -1 for *_, path, body in calls if path == "/api/generate")


def test_prepare_models_fails_fast_on_auth_errors(monkeypatch):
    real = httpx.Client
    monkeypatch.setattr(llm.httpx, "Client", lambda **kw: real(
        transport=httpx.MockTransport(lambda req: httpx.Response(401, text="Unauthorized")), **kw))
    with pytest.raises(llm.LLMError, match="HTTP 401"):
        llm.prepare_models(load_config(), log=lambda *_: None, timeout_s=5)


def test_prepare_models_local_only_waits(monkeypatch):
    calls = []
    _fake_httpx(monkeypatch, calls)
    llm.prepare_models(load_config(), log=lambda *_: None)
    assert calls and all(path == "/api/version" for _, _, path, _ in calls)


def test_model_init_skips_in_cloud_mode(monkeypatch, capsys):
    monkeypatch.setenv("MODEL_INIT_PULL", "0")

    def boom(*a, **kw):
        raise AssertionError("must not contact any server")

    monkeypatch.setattr(model_init.httpx, "Client", boom)
    model_init.main()
    assert "skipping" in capsys.readouterr().out


@pytest.mark.parametrize("model,service,tier", [
    ("gpt-oss:20b", "tech-debate-gpt-oss-20b", "8 32Gi"),
    ("qwen3:14b", "tech-debate-qwen3-14b", "8 32Gi"),
    ("llama3.2:3b", "tech-debate-llama3-2-3b", "4 16Gi"),
    ("gemma3:4b", "tech-debate-gemma3-4b", "4 16Gi"),
    ("some-model:latest", "tech-debate-some-model-latest", "8 32Gi"),
])
def test_gcp_naming_and_sizing(model, service, tier):
    import subprocess
    out = subprocess.run(["bash", "-c", f'source gcp/lib.sh && service_name "{model}" && size_tier "{model}"'],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    assert out[0] == service and out[1] == tier
