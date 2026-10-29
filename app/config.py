"""Load config/debate.yaml plus service URLs from the environment."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("DEBATE_CONFIG_DIR", ROOT / "config"))


class ModelCfg(BaseModel):
    name: str
    think_capable: bool = False
    temperature: float = 0.7


class Models(BaseModel):
    pro: ModelCfg
    con: ModelCfg
    judge: ModelCfg

    def for_role(self, role: str) -> ModelCfg:
        return getattr(self, role)

    def unique_names(self) -> list[str]:
        return list(dict.fromkeys([self.pro.name, self.con.name, self.judge.name]))


class LLMCfg(BaseModel):
    seed: int = 42
    num_ctx: int = 8192
    timeout_s: float = 600
    keep_alive: str = "5m"


class Words(BaseModel):
    opening: int = 120
    rebuttal: int = 110
    closing: int = 30


class DebateCfg(BaseModel):
    rebuttal_rounds: int = 2
    turn_retries: int = 3
    words: Words = Words()
    novelty_threshold: float = 0.6
    quote_match_ratio: float = 0.85
    stance_check: bool = True


class ResearchCfg(BaseModel):
    queries_per_side: int = 3
    results_per_query: int = 4
    fetch_per_query: int = 2
    snippet_chars: int = 600
    evidence_per_side_in_prompt: int = 6
    fetch_timeout_s: float = 10
    search_timeout_s: float = 15
    max_page_bytes: int = 2_000_000


class Voices(BaseModel):
    pro: str = "am_michael"
    con: str = "bf_emma"
    narrator: str = "bm_george"
    speed: float = 1.0


class RenderCfg(BaseModel):
    sentence_gap_ms: int = 150
    speaker_gap_ms: int = 700
    mp3_bitrate: str = "128k"


class Services(BaseModel):
    ollama_url: str
    searxng_url: str
    kokoro_url: str
    out_dir: Path
    cache_dir: Path


class Config(BaseModel):
    models: Models
    llm: LLMCfg = LLMCfg()
    debate: DebateCfg = DebateCfg()
    research: ResearchCfg = ResearchCfg()
    voices: Voices = Voices()
    render: RenderCfg = RenderCfg()
    demo_topic: str
    services: Services


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config() -> Config:
    data = load_yaml("debate.yaml")
    data["services"] = Services(
        ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        searxng_url=os.environ.get("SEARXNG_URL", "http://localhost:8080").rstrip("/"),
        kokoro_url=os.environ.get("KOKORO_URL", "http://localhost:8880").rstrip("/"),
        out_dir=Path(os.environ.get("OUT_DIR", ROOT / "out")),
        cache_dir=Path(os.environ.get("CACHE_DIR", ROOT / "cache")),
    )
    return Config.model_validate(data)
