"""Minimal Ollama /api/chat client with JSON-schema structured output."""

from __future__ import annotations

import json
import re
import time
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Config, ModelCfg

T = TypeVar("T", bound=BaseModel)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class LLMError(RuntimeError):
    pass


def strip_thinking(text: str) -> str:
    """Remove reasoning blocks, including an unterminated leading one."""
    text = _THINK_RE.sub("", text)
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.replace("<think>", "").strip()


class ChatClient(Protocol):
    def structured(self, model: ModelCfg, system: str, user: str, schema: type[T]) -> T: ...


class OllamaClient:
    def __init__(self, cfg: Config, http: httpx.Client | None = None):
        self.cfg = cfg
        self.http = http or httpx.Client(base_url=cfg.services.ollama_url, timeout=cfg.llm.timeout_s)
        self._no_think_param: set[str] = set()

    def _post_chat(self, payload: dict) -> str:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                r = self.http.post("/api/chat", json=payload)
            except httpx.TransportError as e:
                last_exc = e
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 400 and "think" in r.text.lower() and "think" in payload:
                # Model does not support the think flag; remember and retry without it.
                self._no_think_param.add(payload["model"])
                payload = {k: v for k, v in payload.items() if k != "think"}
                continue
            if r.status_code >= 500:
                last_exc = LLMError(f"ollama {r.status_code}: {r.text[:200]}")
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise LLMError(f"ollama {r.status_code}: {r.text[:300]}")
            return r.json()["message"]["content"]
        raise LLMError(f"ollama request failed: {last_exc}")

    def structured(self, model: ModelCfg, system: str, user: str, schema: type[T]) -> T:
        payload: dict = {
            "model": model.name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": schema.model_json_schema(),
            "stream": False,
            "keep_alive": self.cfg.llm.keep_alive,
            "options": {
                "temperature": model.temperature,
                "seed": self.cfg.llm.seed,
                "num_ctx": self.cfg.llm.num_ctx,
            },
        }
        if model.think_capable and model.name not in self._no_think_param:
            payload["think"] = False

        errors: list[str] = []
        for _ in range(2):
            raw = strip_thinking(self._post_chat(payload))
            try:
                return schema.model_validate(json.loads(raw))
            except (json.JSONDecodeError, ValidationError) as e:
                errors.append(str(e)[:200])
        raise LLMError(f"{model.name} returned invalid JSON for {schema.__name__}: {errors}")
