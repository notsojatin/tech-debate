"""Persistent debate state, saved to state.json after every phase."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.ledger import Ledger, Side


class Phase(str, Enum):
    RESEARCH = "research"
    OPENINGS = "openings"
    REBUTTAL_1 = "rebuttal_1"
    REBUTTAL_2 = "rebuttal_2"
    CLOSINGS = "closings"
    JUDGE = "judge"
    RENDER = "render"
    DONE = "done"


def rebuttal_phase(round_no: int) -> Phase:
    return Phase(f"rebuttal_{round_no}")


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
    phases_done: list[Phase] = []
    ledger: Ledger = Ledger()
    queries: dict[str, list[str]] = {}
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
