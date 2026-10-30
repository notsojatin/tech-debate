"""Persistent debate state, saved to state.json after every phase."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.ledger import Ledger, Side


MAX_REBUTTAL_ROUNDS = 10


class Phase(str, Enum):
    RESEARCH = "research"
    OPENINGS = "openings"
    REBUTTAL_1 = "rebuttal_1"
    REBUTTAL_2 = "rebuttal_2"
    REBUTTAL_3 = "rebuttal_3"
    REBUTTAL_4 = "rebuttal_4"
    REBUTTAL_5 = "rebuttal_5"
    REBUTTAL_6 = "rebuttal_6"
    REBUTTAL_7 = "rebuttal_7"
    REBUTTAL_8 = "rebuttal_8"
    REBUTTAL_9 = "rebuttal_9"
    REBUTTAL_10 = "rebuttal_10"  # MAX_REBUTTAL_ROUNDS
    CLOSINGS = "closings"
    JUDGE = "judge"
    RENDER = "render"
    DONE = "done"


def rebuttal_phase(round_no: int) -> Phase:
    return Phase(f"rebuttal_{round_no}")


def is_rebuttal(phase: Phase) -> bool:
    return phase.value.startswith("rebuttal_")


def rebuttal_no(phase: Phase) -> int:
    return int(phase.value.rsplit("_", 1)[1])


_NUMBER_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def phase_title(phase: Phase) -> str:
    """Short written title: 'Openings', 'Rebuttal round 3', 'Closings'."""
    if is_rebuttal(phase):
        return f"Rebuttal round {rebuttal_no(phase)}"
    return {Phase.OPENINGS: "Openings", Phase.CLOSINGS: "Closings"}.get(phase, phase.value.title())


def phase_heading(phase: Phase) -> str:
    """Spoken heading the narrator reads: 'Opening statements', 'Rebuttals, round three', 'Closing lines'."""
    if is_rebuttal(phase):
        n = rebuttal_no(phase)
        return f"Rebuttals, round {_NUMBER_WORDS[n] if n < len(_NUMBER_WORDS) else n}"
    return {Phase.OPENINGS: "Opening statements", Phase.CLOSINGS: "Closing lines"}.get(phase, phase.value.title())


class Turn(BaseModel):
    phase: Phase
    side: Side
    model: str
    text: str
    cites: list[str] = []
    quote: str | None = None
    attacks: str | None = None
    new_point: str | None = None
    quote_matched: bool | None = None
    attempts: int = 1
    warnings: list[str] = []


class DebateState(BaseModel):
    topic: str
    run_dir: Path
    models: dict[str, str]
    # Chosen per debate; None on runs saved before these were configurable (they use the config defaults).
    rebuttal_rounds: int | None = None
    speech_length: str | None = None
    phases_done: list[Phase] = []
    ledger: Ledger = Ledger()
    queries: dict[str, list[str]] = {}
    counter_claim: str | None = None
    turns: list[Turn] = []
    points_made: dict[str, list[str]] = {"pro": [], "con": []}
    judge: dict[str, Any] | None = None
    warnings: list[str] = []
    timings_s: dict[str, float] = {}

    @property
    def path(self) -> Path:
        return self.run_dir / "state.json"

    def save(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @classmethod
    def load(cls, run_dir: Path) -> "DebateState":
        data = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        data["run_dir"] = str(run_dir)
        return cls.model_validate(data)

    def last_turn(self, side: Side) -> Turn | None:
        return next((t for t in reversed(self.turns) if t.side == side), None)

    def turns_in(self, phase: Phase) -> list[Turn]:
        return [t for t in self.turns if t.phase == phase]

    def spoken_phases(self) -> list[Phase]:
        """Phases that have turns, in the order they were spoken."""
        return list(dict.fromkeys(t.phase for t in self.turns))
