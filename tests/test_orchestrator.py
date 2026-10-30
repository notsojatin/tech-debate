import json
import re
import wave

from app import agents
from app.judge import JudgeOut, SideScores
from app.orchestrator import Orchestrator, new_state
from app.state import DebateState, Phase
from app.tools.search import Found


class FakeLLM:
    """Scripted model: produces valid turns, except the very first opening which cites a bogus ID."""

    def __init__(self):
        self.calls = []
        self.n = 0
        self.bogus_sent = False

    def structured(self, model, system, user, schema):
        self.calls.append((model.name, schema.__name__))
        self.n += 1
        side = "FOR" if "argue FOR" in system else "AGAINST"
        if schema is agents.Queries:
            return schema(queries=[f"{side} query one", f"{side} query two"])
        if schema is agents.OpeningOut:
            bogus = not self.bogus_sent
            self.bogus_sent = True
            ids = re.findall(r'id="(E\d+)"', user)
            return schema(text=f"Opening for the {side} side here. Teams ship faster with {side.lower()} approach.",
                          cites=["E99"] if bogus else ids[:1], new_point=f"{side} speed argument")
        if schema is agents.RebuttalOut:
            opp = re.search(r"<opponent>(.*?)</opponent>", user, re.S).group(1)
            first = opp.split(". ")[0]
            ids = re.findall(r'id="(E\d+)"', user)
            return schema(quote=first, attacks="It is wrong.", text=f"That is false. New point number {self.n}.",
                          cites=ids[:1], new_point=f"{side} unique argument {self.n} zebra{self.n}")
        if schema is agents.StanceOut:
            statement = user.split("Statement:")[1]
            return schema(reason="x", supports="claim_1" if "FOR" in statement[:80] else "claim_2")
        if schema is agents.ClosingOut:
            return schema(text=f"Vote {side.lower()}.")
        if schema is JudgeOut:
            sc = lambda n: SideScores(evidence_use=n, rebuttal_responsiveness=n, argument_quality=n, stayed_on_side=n)
            # Side A is listed first in the transcript text.
            a_is_pro = user.index("Side A argues FOR") >= 0 if "Side A argues FOR" in user else False
            return schema(a=sc(8 if a_is_pro else 6), b=sc(6 if a_is_pro else 8),
                          winner="a" if a_is_pro else "b", reason="Pro used evidence better.")
        raise AssertionError(schema)


class FakeResearch:
    def research(self, topic, queries, exclude_urls):
        return [Found(query=q, url=f"https://site{i}.example/{q.replace(' ', '-')}", title=f"T{i}",
                      snippet=f"Evidence text number {i} about {q}, long enough to keep.")
                for i, q in enumerate(queries)]


class FakeTTS:
    def synth(self, text, voice):
        return b"\x01\x00" * 2400  # 0.1 s


def test_full_run(cfg, tmp_path):
    llm = FakeLLM()
    state = new_state(cfg, "Monorepos beat polyrepos", out_dir=tmp_path)
    Orchestrator(cfg, llm, FakeResearch(), FakeTTS(), log=lambda *_: None).run(state)

    assert [p.value for p in state.phases_done][-1] == "done"
    assert len(state.ledger.items) == 4
    assert state.counter_claim == "It is not true that Monorepos beat polyrepos"
    assert len(state.turns) == 2 + 2 * cfg.debate.rebuttal_rounds + 2
    # First opening was retried after a bogus cite and ended up valid.
    pro_open = state.turns[0]
    assert pro_open.attempts == 2 and pro_open.cites and not pro_open.warnings
    ids = state.ledger.ids()
    assert all(c in ids for t in state.turns for c in t.cites)
    assert all(t.quote_matched for t in state.turns if t.phase.value.startswith("rebuttal"))
    assert state.judge["winner"] == "pro" and state.judge["position_consistent"]

    run = state.run_dir
    for name in ("state.json", "transcript.md", "evidence.json", "judge.json", "debate.srt", "debate.wav"):
        assert (run / name).exists(), name
    md = (run / "transcript.md").read_text()
    assert "[^E1]:" in md and "Verdict" in md
    srt = (run / "debate.srt").read_text().strip().split("\n\n")
    with wave.open(str(run / "debate.wav")) as w:
        dur_ms = w.getnframes() * 1000 // w.getframerate()
    last_end = srt[-1].split("\n")[1].split(" --> ")[1]
    h, m, rest = last_end.split(":")
    s, ms = rest.split(",")
    assert int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms) == dur_ms

    # state.json round-trips and a resumed run does nothing new.
    reloaded = DebateState.load(run)
    n_calls = len(llm.calls)
    Orchestrator(cfg, llm, FakeResearch(), FakeTTS(), log=lambda *_: None).run(reloaded)
    assert len(llm.calls) == n_calls
    assert json.loads((run / "judge.json").read_text())["totals"]["pro"] > 0


def test_checkpoint_after_each_phase(cfg, tmp_path):
    class Boom(FakeLLM):
        def structured(self, model, system, user, schema):
            if schema is agents.ClosingOut:
                raise RuntimeError("crash")
            return super().structured(model, system, user, schema)

    state = new_state(cfg, "Tabs vs spaces", out_dir=tmp_path)
    try:
        Orchestrator(cfg, Boom(), FakeResearch(), None, log=lambda *_: None).run(state)
    except RuntimeError:
        pass
    saved = DebateState.load(state.run_dir)
    assert Phase.REBUTTAL_2 in saved.phases_done and Phase.CLOSINGS not in saved.phases_done
    Orchestrator(cfg, FakeLLM(), FakeResearch(), None, log=lambda *_: None).run(saved)
    assert Phase.DONE in saved.phases_done and len(saved.turns_in(Phase.CLOSINGS)) == 2
