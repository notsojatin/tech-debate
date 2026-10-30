"""Per-debate rebuttal rounds and speech length, model limits, and phase titles beyond round two."""

import json
import time

import httpx
import pytest

from app import judge, render
from app.__main__ import main as cli_main
from app.config import cfg_for_state
from app.judge import JudgeOut
from app.ledger import Evidence
from app.llm import LLMError, OllamaClient, estimate_tokens
from app.orchestrator import Orchestrator, new_state, phase_plan
from app.state import DebateState, Phase, Turn, rebuttal_phase
from tests.test_orchestrator import FakeLLM, FakeResearch
from tests.test_server import _make_client

WORDS = ("open weight models now match frontier systems on most production workloads while costing a "
         "fraction per token and keeping customer data inside the company network").split()


def prose(n: int) -> str:
    return " ".join(WORDS[i % len(WORDS)] for i in range(n)) + "."


# ---------------------------------------------------------------- config

def test_with_debate_settings_sets_rounds_and_words(cfg):
    run = cfg.with_debate_settings(10, "long")
    assert run.debate.rebuttal_rounds == 10 and run.debate.speech_length == "long"
    assert run.debate.words.rebuttal == 180
    assert phase_plan(run)[-3:] == [Phase.CLOSINGS, Phase.JUDGE, Phase.RENDER]
    assert rebuttal_phase(10) in phase_plan(run)
    # Defaults come from config/debate.yaml.
    assert cfg.debate.rebuttal_rounds == 2 and cfg.debate.speech_length == "standard"
    assert cfg.debate.words.rebuttal == 110


@pytest.mark.parametrize("rounds,length", [(0, None), (11, None), (None, "epic")])
def test_with_debate_settings_rejects_bad_values(cfg, rounds, length):
    with pytest.raises(ValueError):
        cfg.with_debate_settings(rounds, length)


def test_old_state_without_settings_uses_defaults(cfg, tmp_path):
    run_dir = tmp_path / "20260101-000000-old"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(json.dumps({
        "topic": "Old run", "run_dir": str(run_dir),
        "models": {"pro": "qwen3:4b", "con": "gemma3:4b", "judge": "llama3.2:3b"},
        "phases_done": ["research", "openings", "rebuttal_1"],
    }))
    state = DebateState.load(run_dir)
    assert state.rebuttal_rounds is None and state.speech_length is None
    run = cfg_for_state(cfg, state)
    assert run.debate.rebuttal_rounds == 2 and run.debate.speech_length == "standard"


def test_evidence_serializes_domain():
    ev = Evidence(id="E1", side="pro", query="q", url="https://www.epoch.ai/x", title="t", snippet="s")
    assert ev.model_dump()["domain"] == "epoch.ai"
    # Saved states that now contain `domain` still load.
    assert Evidence.model_validate(ev.model_dump()).domain == "epoch.ai"


# ---------------------------------------------------------------- orchestration

def test_ten_round_run_and_resume_keeps_rounds(cfg, tmp_path):
    run_cfg = cfg.with_debate_settings(10, "short")
    state = new_state(run_cfg, "Monorepos beat polyrepos", out_dir=tmp_path)
    assert state.rebuttal_rounds == 10 and state.speech_length == "short"
    Orchestrator(run_cfg, FakeLLM(), FakeResearch(), None, log=lambda *_: None).run(state)
    assert len(state.turns) == 2 + 2 * 10 + 2
    assert Phase.REBUTTAL_10 in state.phases_done and Phase.DONE in state.phases_done

    # A resumed run plans the stored rounds, not the configured default.
    saved = DebateState.load(state.run_dir)
    assert len(phase_plan(cfg_for_state(cfg, saved))) == len(phase_plan(run_cfg))


def test_titles_come_from_turns_without_phases_done(tmp_path):
    turns = [Turn(phase=Phase.OPENINGS, side=s, model="m", text=f"{s} opening.") for s in ("pro", "con")]
    turns += [Turn(phase=rebuttal_phase(n), side=s, model="m", text=f"{s} rebuttal {n}.")
              for n in range(1, 11) for s in ("pro", "con")]
    state = DebateState(topic="T", run_dir=tmp_path, models={"pro": "a", "con": "b", "judge": "c"}, turns=turns)
    assert state.phases_done == []

    text = judge.render_for_judge(state, "pro")
    assert "## Rebuttal round 3" in text and "## Rebuttal round 10" in text
    assert text.index("## Rebuttal round 9") < text.index("## Rebuttal round 10")

    narrator = [s.text for s in render.build_script(state) if s.speaker == "narrator"]
    assert "Rebuttals, round three." in narrator and "Rebuttals, round ten." in narrator
    assert "## Rebuttals — round ten" in render.transcript_markdown(state)
    assert judge.side_facts(state, "pro")["rebuttals_quoting_opponent"].endswith("/10")


# ---------------------------------------------------------------- model limits

def worst_case_state(tmp_path, cfg) -> DebateState:
    """10 rebuttal rounds of long speeches, every speech quoting its opponent, and a full ledger all cited."""
    long = cfg.with_debate_settings(10, "long").debate.words
    state = DebateState(topic="Open-weight local LLMs are better than proprietary APIs for enterprise teams",
                        run_dir=tmp_path, models={"pro": "a", "con": "b", "judge": "c"})
    for i in range(24):
        state.ledger.add("pro" if i % 2 else "con", "q", f"https://site{i}.example.com/page", f"Title {i}",
                         prose(110))
    ids = [e.id for e in state.ledger.items]
    for side in ("pro", "con"):
        state.turns.append(Turn(phase=Phase.OPENINGS, side=side, model="m", text=prose(long.opening), cites=ids[:3]))
    for n in range(1, 11):
        for side in ("pro", "con"):
            state.turns.append(Turn(phase=rebuttal_phase(n), side=side, model="m", text=prose(long.rebuttal),
                                    quote=prose(40), cites=ids[n % 24:n % 24 + 3]))
    for side in ("pro", "con"):
        state.turns.append(Turn(phase=Phase.CLOSINGS, side=side, model="m", text=prose(long.closing)))
    return state


def test_worst_case_judge_prompt_fits(cfg, tmp_path):
    state = worst_case_state(tmp_path, cfg)
    prompt = judge.SYSTEM + judge.render_for_judge(state, "pro") + json.dumps(JudgeOut.model_json_schema())
    budget = cfg.llm.num_ctx - cfg.llm.num_predict
    assert estimate_tokens(prompt) <= budget, (estimate_tokens(prompt), budget)

    # The guard really runs: the same prompt is refused under the old 8192 context.
    calls = []
    http = httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(500)),
                        base_url="http://x")
    small = cfg.model_copy(update={"llm": cfg.llm.model_copy(update={"num_ctx": 8192})})
    with pytest.raises(LLMError, match="over the"):
        OllamaClient(small, http=http).structured(cfg.models.judge, judge.SYSTEM,
                                                  judge.render_for_judge(state, "pro"), JudgeOut)
    assert calls == []  # refused before any request


def _chat_client(cfg, responses):
    sent = []

    def handler(req):
        sent.append(json.loads(req.content))
        return httpx.Response(200, json=responses[len(sent) - 1])

    return OllamaClient(cfg, http=httpx.Client(transport=httpx.MockTransport(handler), base_url="http://x")), sent


def test_truncated_output_retries_with_new_seed(cfg):
    good = JudgeOut.model_validate({
        "a": dict.fromkeys(judge.CRITERIA, 5), "b": dict.fromkeys(judge.CRITERIA, 6), "winner": "b", "reason": "r"})
    client, sent = _chat_client(cfg, [
        {"message": {"content": '{"a": {"evidence_use": 5'}, "done_reason": "length"},
        {"message": {"content": good.model_dump_json()}, "done_reason": "stop"},
    ])
    out = client.structured(cfg.models.judge, "sys", "user", JudgeOut)
    assert out == good
    assert [b["options"]["seed"] for b in sent] == [cfg.llm.seed, cfg.llm.seed + 1]
    assert all(b["options"]["num_predict"] == cfg.llm.num_predict for b in sent)
    assert all(b["options"]["num_ctx"] == cfg.llm.num_ctx for b in sent)


def test_truncated_output_twice_reports_why(cfg):
    cut = {"message": {"content": '{"a":'}, "done_reason": "length"}
    client, _ = _chat_client(cfg, [cut, cut])
    with pytest.raises(LLMError, match="output hit num_predict"):
        client.structured(cfg.models.judge, "sys", "user", JudgeOut)


# ---------------------------------------------------------------- server and CLI

@pytest.mark.parametrize("body", [{"rebuttal_rounds": 0}, {"rebuttal_rounds": 11}, {"speech_length": "epic"}])
def test_server_rejects_bad_settings(cfg, tmp_path, body):
    client, _ = _make_client(cfg, tmp_path)
    assert client.post("/api/debates", json={"topic": "Rust vs Go", **body}).status_code == 422


def test_server_runs_chosen_rounds(cfg, tmp_path):
    client, _ = _make_client(cfg, tmp_path)
    opts = client.get("/api/models").json()["debate_options"]
    assert opts["rebuttal_rounds"] == {"min": 1, "max": 10, "default": 2}
    assert set(opts["speech_lengths"]) == {"short", "standard", "long"}

    r = client.post("/api/debates", json={"topic": "Monorepos beat polyrepos", "rebuttal_rounds": 3,
                                          "speech_length": "short"})
    assert r.status_code == 201
    run_id = r.json()["id"]
    assert r.json()["phases_plan"].count("rebuttal_3") == 1 and "rebuttal_4" not in r.json()["phases_plan"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        detail = client.get(f"/api/debates/{run_id}").json()
        if detail["status"] == "done":
            break
        time.sleep(0.05)
    assert detail["status"] == "done"
    assert detail["rebuttal_rounds"] == 3 and detail["speech_length"] == "short"
    assert len(detail["state"]["turns"]) == 2 + 6 + 2
    assert detail["state"]["ledger"]["items"][0]["domain"]
    assert client.get("/api/debates").json()[0]["rebuttal_rounds"] == 3


def test_cli_resume_uses_stored_rounds(cfg, tmp_path, monkeypatch):
    run_cfg = cfg.with_debate_settings(5, "standard")
    state = new_state(run_cfg, "Tabs vs spaces", out_dir=tmp_path)
    state.save()
    planned = {}

    class Recorder:
        def run(self, s):
            planned["rounds"] = sum(p.value.startswith("rebuttal_") for p in phase_plan(self.cfg))

    def fake_build(c, **_):
        rec = Recorder()
        rec.cfg = c
        return rec

    monkeypatch.setattr("app.__main__.build", fake_build)
    cli_main(["resume", str(state.run_dir)])
    assert planned["rounds"] == 5
