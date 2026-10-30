"""The debate state machine. Each phase runs to completion and is checkpointed to state.json."""

from __future__ import annotations

import re
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app import agents, judge, render
from app.config import Config
from app.ledger import Side
from app.llm import ChatClient
from app.state import DebateState, Phase, is_rebuttal, rebuttal_no, rebuttal_phase
from app.tools.search import Researcher
from app.tools.tts import KokoroClient

SIDES: tuple[Side, Side] = ("pro", "con")


class DebateCancelled(RuntimeError):
    """Raised when an active debate is cancelled via cancel_check."""


def slugify(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:50] or "debate"


def new_state(cfg: Config, topic: str, out_dir: Path | None = None) -> DebateState:
    out_dir = out_dir or cfg.services.out_dir
    run_dir = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{slugify(topic)}"
    models = {role: cfg.models.for_role(role).name for role in ("pro", "con", "judge")}
    return DebateState(topic=topic, run_dir=run_dir, models=models,
                       rebuttal_rounds=cfg.debate.rebuttal_rounds, speech_length=cfg.debate.speech_length)


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
        on_event: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        live_tts: bool = False,
    ):
        self.cfg = cfg
        self.llm = llm
        self.researcher = researcher
        self.tts = tts
        self.log = log
        self.on_event = on_event
        self.cancel_check = cancel_check
        self.live_tts = live_tts
        self._tts_pool: ThreadPoolExecutor | None = None
        self._tts_futures: list[Future] = []

    def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event is not None:
            self.on_event(event)

    def _check_cancel(self) -> None:
        if self.cancel_check is not None and self.cancel_check():
            raise DebateCancelled("Debate cancelled by user")

    def _queue_segment_tts(
        self,
        state: DebateState,
        segment_id: str,
        speaker: str,
        text: str,
        phase: str,
        turn_index: int | None = None,
    ) -> None:
        if not self.live_tts or self.tts is None:
            return
        if self._tts_pool is None:
            self._tts_pool = ThreadPoolExecutor(max_workers=1)
        out_path = state.run_dir / "segments" / f"{segment_id}.wav"

        def _synth() -> None:
            if self.cancel_check and self.cancel_check():
                return
            try:
                meta = render.render_segment_wav(self.cfg, self.tts, speaker, text, out_path)  # type: ignore[arg-type]
                self._emit({
                    "type": "segment_audio_ready",
                    "segment_id": segment_id,
                    "phase": phase,
                    "turn_index": turn_index,
                    **meta,
                })
            except Exception as exc:
                self.log(f"  ! live tts error ({segment_id}): {exc}")

        self._tts_futures.append(self._tts_pool.submit(_synth))

    def _drain_live_tts(self) -> None:
        for fut in self._tts_futures:
            try:
                fut.result()
            except Exception:
                pass
        self._tts_futures.clear()
        if self._tts_pool is not None:
            self._tts_pool.shutdown(wait=True)
            self._tts_pool = None

    def _backfill_live_tts(self, state: DebateState) -> None:
        """On resume, queue clips for saved turns whose audio never got made (dropped by a cancel)."""
        for seg in render.live_segments(state):
            if not (state.run_dir / "segments" / f"{seg.segment_id}.wav").exists():
                self._queue_segment_tts(state, seg.segment_id, seg.speaker, seg.text, seg.phase, seg.turn_index)

    def run(self, state: DebateState) -> DebateState:
        try:
            if self.live_tts and self.tts is not None and Phase.RENDER not in state.phases_done:
                self._backfill_live_tts(state)
            for phase in phase_plan(self.cfg):
                if phase in state.phases_done:
                    continue
                self._check_cancel()
                self.log(f"== {phase.value}")
                self._emit({"type": "phase_start", "phase": phase.value})
                t0 = time.monotonic()
                self._run_phase(state, phase)
                state.timings_s[phase.value] = round(time.monotonic() - t0, 1)
                state.phases_done.append(phase)
                state.save()
                if phase in (Phase.OPENINGS, Phase.CLOSINGS) or is_rebuttal(phase):
                    for t in state.turns_in(phase):
                        self.log(f"  [{t.side}] {t.text}")
                self._emit({
                    "type": "phase_done",
                    "phase": phase.value,
                    "elapsed_s": state.timings_s[phase.value],
                    "phases_done": [p.value for p in state.phases_done],
                })
            if Phase.DONE not in state.phases_done:
                state.phases_done.append(Phase.DONE)
                state.save()
                # The caller (CLI or web server) announces completion; it knows when its own work is done.
            return state
        finally:
            self._drain_live_tts()

    def _run_phase(self, state: DebateState, phase: Phase) -> None:
        if phase is Phase.RESEARCH:
            self.research(state)
            self._queue_segment_tts(state, "00_intro", "narrator", render.intro_line(state), phase.value)
        elif phase is Phase.OPENINGS:
            for side in SIDES:
                self._turn(state, side, phase, agents.opening_prompt(state, self.cfg, side))
        elif is_rebuttal(phase):
            n = rebuttal_no(phase)
            for side in SIDES:
                self._turn(state, side, phase, agents.rebuttal_prompt(state, self.cfg, side, n))
        elif phase is Phase.CLOSINGS:
            for side in SIDES:
                self._turn(state, side, phase, agents.closing_prompt(state, self.cfg, side))
        elif phase is Phase.JUDGE:
            self._check_cancel()
            self._emit({"type": "judge_start", "model": self.cfg.models.judge.name})
            state.judge = judge.judge(self.llm, self.cfg, state, check=self._check_cancel)
            j = state.judge
            self.log(f"  winner={j['winner']} totals={j['totals']} consistent={j['position_consistent']}")
            self.log(f"  {j['reason']}")
            self._emit({"type": "judge_complete", "judge": j})
            self._queue_segment_tts(state, "99_verdict", "narrator", render.verdict_line(j), phase.value)
        elif phase is Phase.RENDER:
            self._drain_live_tts()
            self.render(state)

    def research(self, state: DebateState) -> None:
        if self.cfg.debate.stance_check and not state.counter_claim:
            self.state_counter_claim_step(state)
        if self.researcher is None:
            state.warnings.append("search disabled; debaters argued without evidence")
            return
        n = self.cfg.research.queries_per_side
        for side in SIDES:
            self._check_cancel()
            if side not in state.queries:
                self._emit({"type": "research_status", "side": side, "status": "generating_queries"})
                system, user = agents.query_prompt(state.topic, side, n)
                q = self.llm.structured(self.cfg.models.for_role(side), system, user, agents.Queries)
                state.queries[side] = [s.strip() for s in q.queries if s.strip()][:n] or [state.topic]
            self.log(f"  {side} queries: {state.queries[side]}")
            self._emit({"type": "research_queries", "side": side, "queries": state.queries[side]})
            exclude = {e.url for e in state.ledger.items}
            self._emit({"type": "research_status", "side": side, "status": "searching_web"})
            for f in self.researcher.research(state.topic, state.queries[side], exclude):
                ev = state.ledger.add(side, f.query, f.url, f.title, f.snippet)
                self._emit({"type": "evidence_added", "side": side, "evidence": ev.model_dump()})
            self.log(f"  {side} evidence: {len(state.ledger.for_side(side, 999))}")
        if not state.ledger.items:
            state.warnings.append("research found no evidence; citations were not required")

    def state_counter_claim_step(self, state: DebateState) -> None:
        state.counter_claim = agents.counter_claim(state.topic)
        self.log(f"  counter-claim: {state.counter_claim}")
        self._emit({"type": "counter_claim", "counter_claim": state.counter_claim})

    def _turn(self, state: DebateState, side: Side, phase: Phase, prompt: str) -> None:
        self._check_cancel()
        turn = agents.run_turn(
            self.llm,
            self.cfg,
            state,
            self.cfg.models.for_role(side),
            side,
            phase,
            prompt,
            on_event=self._emit,
            cancel_point=self._check_cancel,
        )
        turn_index = len(state.turns)
        state.turns.append(turn)
        if turn.new_point:
            state.points_made[side].append(turn.new_point)
        for w in turn.warnings:
            state.warnings.append(f"{side} {phase.value}: {w}")
        self._emit({
            "type": "turn_complete",
            "turn_index": turn_index,
            "side": side,
            "turn": turn.model_dump(mode="json"),
        })
        seg_id = render.turn_segment_id(turn_index, phase.value, side)
        self._queue_segment_tts(state, seg_id, side, turn.text, phase.value, turn_index=turn_index)

    def render(self, state: DebateState) -> None:
        render.write_json_outputs(state)
        render.write_transcript(state)
        if self.tts is None:
            self.log("  audio skipped")
            return
        self._emit({"type": "render_status", "status": "stitching_audio"})
        seconds = render.render_audio(state, self.cfg, self.tts, self.log)
        self.log(f"  audio: {seconds:.0f}s")
        self._emit({"type": "render_complete", "duration_s": round(seconds, 1)})
