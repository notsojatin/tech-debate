"""Load config/debate.yaml (plus an optional profile overlay) and service URLs from the environment."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, model_validator

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("DEBATE_CONFIG_DIR", ROOT / "config"))


ROLES = ("pro", "con", "judge")


class ModelCfg(BaseModel):
    name: str
    # Sent as Ollama's `think`: false turns reasoning off (qwen3); "low" keeps it short for models that
    # cannot turn it off (gpt-oss); None sends nothing.
    think: bool | Literal["low", "medium", "high"] | None = None
    temperature: float = 0.7

    @model_validator(mode="before")
    @classmethod
    def _legacy_think_capable(cls, data: Any) -> Any:
        if isinstance(data, dict) and "think_capable" in data:
            data = dict(data)
            if data.pop("think_capable") and "think" not in data:
                data["think"] = False
        return data


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
    keep_alive: str | int = "5m"
    warm_up: bool = False  # load every model up front, in parallel (cloud: overlaps the cold starts)


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
    ollama_urls: dict[str, str] = {}  # per-role overrides (OLLAMA_URL_PRO, ...)
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

    def ollama_url_for(self, model_name: str) -> str:
        """Base URL of the Ollama serving `model_name`: its role's override, else OLLAMA_URL."""
        for role in ROLES:
            if self.models.for_role(role).name == model_name and role in self.services.ollama_urls:
                return self.services.ollama_urls[role]
        return self.services.ollama_url

    def ollama_urls_by_model(self, names: list[str] | None = None) -> dict[str, str]:
        return {n: self.ollama_url_for(n) for n in (names or self.models.unique_names())}


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(profile: str | None = None) -> Config:
    """`profile` (or $DEBATE_PROFILE), e.g. 'cloud', overlays config/debate.<profile>.yaml."""
    data = load_yaml("debate.yaml")
    profile = profile if profile is not None else os.environ.get("DEBATE_PROFILE", "")
    if profile:
        data = deep_merge(data, load_yaml(f"debate.{profile}.yaml"))
    role_urls = {r: u.rstrip("/") for r in ROLES if (u := os.environ.get(f"OLLAMA_URL_{r.upper()}", ""))}
    data["services"] = Services(
        ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        ollama_urls=role_urls,
        searxng_url=os.environ.get("SEARXNG_URL", "http://localhost:8080").rstrip("/"),
        kokoro_url=os.environ.get("KOKORO_URL", "http://localhost:8880").rstrip("/"),
        out_dir=Path(os.environ.get("OUT_DIR", ROOT / "out")),
        cache_dir=Path(os.environ.get("CACHE_DIR", ROOT / "cache")),
    )
    return Config.model_validate(data)


if __name__ == "__main__":
    # `python -m app.config [profile]` prints "role model" lines; the gcp/ scripts read this.
    cfg = load_config(sys.argv[1] if len(sys.argv) > 1 else None)
    for role in ROLES:
        print(role, cfg.models.for_role(role).name)
