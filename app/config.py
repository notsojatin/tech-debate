"""Load config/debate.yaml (plus an optional profile overlay) and service URLs from the environment."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import BaseModel, field_validator, model_validator

from app.state import MAX_REBUTTAL_ROUNDS

if TYPE_CHECKING:
    from app.state import DebateState

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
    num_ctx: int = 16384
    num_predict: int = 2048  # output cap per call; includes reasoning tokens for models that think
    timeout_s: float = 600
    keep_alive: str | int = "5m"
    warm_up: bool = False  # load every model up front, in parallel (cloud: overlaps the cold starts)


class Words(BaseModel):
    opening: int = 120
    rebuttal: int = 110
    closing: int = 30


SPEECH_LENGTHS = {
    "short": Words(opening=80, rebuttal=70, closing=25),
    "standard": Words(opening=120, rebuttal=110, closing=30),
    "long": Words(opening=200, rebuttal=180, closing=40),
}


class DebateCfg(BaseModel):
    rebuttal_rounds: int = 2
    turn_retries: int = 3
    words: Words = Words()  # the active limits; `with_debate_settings` sets them from `speech_lengths`
    speech_lengths: dict[str, Words] = SPEECH_LENGTHS
    speech_length: str = "standard"  # name of the active preset, recorded on each new debate
    novelty_threshold: float = 0.6
    quote_match_ratio: float = 0.85
    stance_check: bool = True

    @field_validator("rebuttal_rounds")
    @classmethod
    def _rounds_in_range(cls, v: int) -> int:
        if not 1 <= v <= MAX_REBUTTAL_ROUNDS:
            raise ValueError(f"rebuttal_rounds must be between 1 and {MAX_REBUTTAL_ROUNDS}, got {v}")
        return v

    @model_validator(mode="after")
    def _known_length(self) -> "DebateCfg":
        if self.speech_length not in self.speech_lengths:
            raise ValueError(f"speech_length {self.speech_length!r} is not one of {list(self.speech_lengths)}")
        return self


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
    model_urls: dict[str, str] = {}   # model-name -> URL bound before role overrides
    searxng_url: str
    kokoro_url: str
    out_dir: Path
    cache_dir: Path


class Config(BaseModel):
    models: Models
    catalog: list[ModelCfg] = []
    llm: LLMCfg = LLMCfg()
    debate: DebateCfg = DebateCfg()
    research: ResearchCfg = ResearchCfg()
    voices: Voices = Voices()
    render: RenderCfg = RenderCfg()
    demo_topic: str
    preset_topics: list[str] = []
    services: Services

    def curated_models(self) -> list[ModelCfg]:
        """Ordered list of allowed models from `models` (pro, con, judge) plus any extra `catalog` entries."""
        seen: dict[str, ModelCfg] = {}
        for role in ROLES:
            m = self.models.for_role(role)
            seen.setdefault(m.name, m)
        for m in self.catalog:
            seen.setdefault(m.name, m)
        return list(seen.values())

    def with_role_models(self, role_names: dict[str, str]) -> "Config":
        """Return a copy of Config with updated role models chosen from the curated catalog."""
        by_name = {m.name: m for m in self.curated_models()}
        new_models: dict[str, ModelCfg] = {}
        for role in ROLES:
            default_cfg = self.models.for_role(role)
            chosen_name = role_names.get(role, default_cfg.name)
            if chosen_name not in by_name:
                raise ValueError(f"Unknown model {chosen_name!r}; allowed: {list(by_name)}")
            base_model = by_name[chosen_name]
            new_models[role] = ModelCfg(
                name=base_model.name,
                think=base_model.think,
                temperature=default_cfg.temperature,
            )
        # Preserve original model->URL bindings so swapping roles in cloud mode still hits the right service.
        bound_urls = dict(self.services.model_urls)
        for role in ROLES:
            orig_name = self.models.for_role(role).name
            if role in self.services.ollama_urls and orig_name not in bound_urls:
                bound_urls[orig_name] = self.services.ollama_urls[role]
        new_services = self.services.model_copy(update={"model_urls": bound_urls})
        return self.model_copy(update={"models": Models(**new_models), "services": new_services})

    def with_debate_settings(self, rounds: int | None = None, length: str | None = None) -> "Config":
        """Return a copy with this debate's rebuttal rounds and speech length; None keeps the configured value."""
        rounds = self.debate.rebuttal_rounds if rounds is None else rounds
        length = self.debate.speech_length if length is None else length
        if not 1 <= rounds <= MAX_REBUTTAL_ROUNDS:
            raise ValueError(f"Rebuttal rounds must be between 1 and {MAX_REBUTTAL_ROUNDS}, got {rounds}")
        if length not in self.debate.speech_lengths:
            raise ValueError(f"Unknown speech length {length!r}; allowed: {list(self.debate.speech_lengths)}")
        debate = self.debate.model_copy(update={
            "rebuttal_rounds": rounds,
            "speech_length": length,
            "words": self.debate.speech_lengths[length],
        })
        return self.model_copy(update={"debate": debate})

    def ollama_url_for(self, model_name: str) -> str:
        """Base URL of the Ollama serving `model_name`: bound model URL, role override, else OLLAMA_URL."""
        if model_name in self.services.model_urls:
            return self.services.model_urls[model_name]
        for role in ROLES:
            if self.models.for_role(role).name == model_name and role in self.services.ollama_urls:
                return self.services.ollama_urls[role]
        return self.services.ollama_url

    def ollama_urls_by_model(self, names: list[str] | None = None) -> dict[str, str]:
        return {n: self.ollama_url_for(n) for n in (names or self.models.unique_names())}


def cfg_for_state(cfg: Config, state: "DebateState") -> Config:
    """The config a saved debate runs with: its models, rounds and speech length. Runs saved before a setting
    existed (or whose model is no longer in the catalog) fall back to the configured value."""
    try:
        cfg = cfg.with_role_models(state.models)
    except ValueError:
        pass
    try:
        return cfg.with_debate_settings(state.rebuttal_rounds, state.speech_length)
    except ValueError:
        return cfg


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
    cfg = Config.model_validate(data)
    # Apply the configured preset so `debate.words` always matches `debate.speech_length`.
    return cfg.with_debate_settings()


if __name__ == "__main__":
    # `python -m app.config [profile]` prints "role model" lines; the gcp/ scripts read this.
    cfg = load_config(sys.argv[1] if len(sys.argv) > 1 else None)
    for role in ROLES:
        print(role, cfg.models.for_role(role).name)
