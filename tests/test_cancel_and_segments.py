import pytest

from app import agents, judge, render
from app.agents import OpeningOut
from app.judge import JudgeOut, SideScores
from app.ledger import Ledger
from app.orchestrator import Orchestrator, new_state
from app.state import Phase, Turn
from tests.test_orchestrator import FakeLLM, FakeTTS


class Stop(Exception):
    pass


def cancel_after(n):
    calls = {"n": 0}

    def point():
        calls["n"] += 1
        if calls["n"] > n:
            raise Stop()
    return point


def test_cancel_between_turn_retries(cfg, tmp_path):
    asked = []

    class Bad:
        def structured(self, model, system, user, schema):
            asked.append(schema)
            return OpeningOut(text="Monorepos win.", cites=["E99"], new_point="x")  # always rejected

    state = new_state(cfg, "Monorepos beat polyrepos", out_dir=tmp_path)
    state.ledger = Ledger()
    state.ledger.add("pro", "q", "https://a.example/x", "A", "snippet long enough to keep around")
    with pytest.raises(Stop):
        agents.run_turn(Bad(), cfg, state, cfg.models.pro, "pro", Phase.OPENINGS, "prompt",
                        cancel_point=cancel_after(1))
    assert len(asked) == 1  # stopped before the retry, not after all 3 attempts


def test_cancel_between_judge_passes(cfg, tmp_path):
    asked = []

    class J:
        def structured(self, model, system, user, schema):
            asked.append(1)
            s = SideScores(evidence_use=5, rebuttal_responsiveness=5, argument_quality=5, stayed_on_side=5)
            return JudgeOut(a=s, b=s, winner="tie", reason="r")

    state = new_state(cfg, "T", out_dir=tmp_path)
    with pytest.raises(Stop):
        judge.judge(J(), cfg, state, check=cancel_after(1))
    assert len(asked) == 1


def _state_with_turns(cfg, tmp_path, n):
    state = new_state(cfg, "Tabs beat spaces", out_dir=tmp_path)
    state.phases_done = [Phase.RESEARCH, Phase.OPENINGS]
    state.turns = [Turn(phase=Phase.OPENINGS, side=s, model="m", text=f"Turn {i} says something clear.")
                   for i, s in zip(range(n), ("pro", "con"))]
    return state


def test_prune_removes_clips_of_discarded_turns(cfg, tmp_path):
    state = _state_with_turns(cfg, tmp_path, 2)
    seg = state.run_dir / "segments"
    seg.mkdir(parents=True)
    for name in ("00_intro.wav", "turn_00_openings_pro.wav", "turn_01_openings_con.wav",
                 "turn_02_rebuttal_1_pro.wav", "99_verdict.wav"):
        (seg / name).write_bytes(b"x")
    assert sorted(render.prune_live_segments(state)) == ["99_verdict.wav", "turn_02_rebuttal_1_pro.wav"]
    assert {p.name for p in seg.iterdir()} == {"00_intro.wav", "turn_00_openings_pro.wav", "turn_01_openings_con.wav"}


def test_resume_backfills_missing_clips(cfg, tmp_path):
    state = _state_with_turns(cfg, tmp_path, 2)
    orch = Orchestrator(cfg, FakeLLM(), None, FakeTTS(), log=lambda *_: None, live_tts=True)
    orch._backfill_live_tts(state)
    orch._drain_live_tts()
    names = {p.name for p in (state.run_dir / "segments").iterdir()}
    assert names == {"00_intro.wav", "turn_00_openings_pro.wav", "turn_01_openings_con.wav"}
