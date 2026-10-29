"""The debate state machine. Each phase runs to completion and is checkpointed to state.json."""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from app import agents, judge, render
from app.config import Config
from app.ledger import Side
from app.llm import ChatClient
from app.state import DebateState, Phase, rebuttal_phase
from app.tools.search import Researcher
from app.tools.tts import KokoroClient

SIDES: tuple[Side, Side] = ("pro", "con")


def slugify(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:50] or "debate"


def new_state(cfg: Config, topic: str, out_dir: Path | None = None) -> DebateState:
    out_dir = out_dir or cfg.services.out_dir
    run_dir = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{slugify(topic)}"
    models = {role: cfg.models.for_role(role).name for role in ("pro", "con", "judge")}
    return DebateState(topic=topic, run_dir=run_dir, models=models)


def phase_plan(cfg: Config) -> list[Phase]:
    rounds = [rebuttal_phase(i) for i in range(1, cfg.debate.rebuttal_rounds + 1)]
    return [Phase.RESEARCH, Phase.OPENINGS, *rounds, Phase.CLOSINGS, Phase.JUDGE, Phase.RENDER]


class Orchestrator:
    def __init__(
        self,
        cfg: Config,
        llm: ChatClient,
        researcher: Researcher | None,
        tts: KokoroClient | None,
        log: Callable[[str], None] = print,
    ):
        self.cfg = cfg
        self.llm = llm
        self.researcher = researcher
        self.tts = tts
        self.log = log

    def run(self, state: DebateState) -> DebateState:
        for phase in phase_plan(self.cfg):
            if phase in state.phases_done:
                continue
            self.log(f"== {phase.value}")
            t0 = time.monotonic()
            self._run_phase(state, phase)
            state.timings_s[phase.value] = round(time.monotonic() - t0, 1)
            state.phases_done.append(phase)
            state.save()
            if phase in (Phase.OPENINGS, Phase.CLOSINGS) or phase.value.startswith("rebuttal"):
                for t in state.turns_in(phase):
                    self.log(f"  [{t.side}] {t.text}")
        if Phase.DONE not in state.phases_done:
            state.phases_done.append(Phase.DONE)
            state.save()
        return state

    def _run_phase(self, state: DebateState, phase: Phase) -> None:
        if phase is Phase.RESEARCH:
            self.research(state)
        elif phase is Phase.OPENINGS:
            for side in SIDES:
                self._turn(state, side, phase, agents.opening_prompt(state, self.cfg, side))
        elif phase.value.startswith("rebuttal_"):
            n = int(phase.value.rsplit("_", 1)[1])
            for side in SIDES:
                self._turn(state, side, phase, agents.rebuttal_prompt(state, self.cfg, side, n))
        elif phase is Phase.CLOSINGS:
            for side in SIDES:
                self._turn(state, side, phase, agents.closing_prompt(state, self.cfg, side))
        elif phase is Phase.JUDGE:
            state.judge = judge.judge(self.llm, self.cfg, state)
            j = state.judge
            self.log(f"  winner={j['winner']} totals={j['totals']} consistent={j['position_consistent']}")
            self.log(f"  {j['reason']}")
        elif phase is Phase.RENDER:
            self.render(state)

    def research(self, state: DebateState) -> None:
        if self.researcher is None:
            state.warnings.append("search disabled; debaters argued without evidence")
            return
        n = self.cfg.research.queries_per_side
        for side in SIDES:
            if side not in state.queries:
                system, user = agents.query_prompt(state.topic, side, n)
                q = self.llm.structured(self.cfg.models.for_role(side), system, user, agents.Queries)
                state.queries[side] = [s.strip() for s in q.queries if s.strip()][:n] or [state.topic]
            self.log(f"  {side} queries: {state.queries[side]}")
            exclude = {e.url for e in state.ledger.items}
            for f in self.researcher.research(state.topic, state.queries[side], exclude):
                state.ledger.add(side, f.query, f.url, f.title, f.snippet)
            self.log(f"  {side} evidence: {len(state.ledger.for_side(side, 999))}")
        if not state.ledger.items:
            state.warnings.append("research found no evidence; citations were not required")

    def _turn(self, state: DebateState, side: Side, phase: Phase, prompt: str) -> None:
        turn = agents.run_turn(self.llm, self.cfg, state, self.cfg.models.for_role(side), side, phase, prompt)
        state.turns.append(turn)
        if turn.new_point:
            state.points_made[side].append(turn.new_point)
        for w in turn.warnings:
            state.warnings.append(f"{side} {phase.value}: {w}")

    def render(self, state: DebateState) -> None:
        render.write_json_outputs(state)
        render.write_transcript(state)
        if self.tts is None:
            self.log("  audio skipped")
            return
        seconds = render.render_audio(state, self.cfg, self.tts, self.log)
        self.log(f"  audio: {seconds:.0f}s")
