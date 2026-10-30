"""Minimal Ollama /api/chat client with JSON-schema structured output."""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from typing import Callable, Protocol, TypeVar

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
    """Talks to one Ollama per model: they may all be the same URL (local) or one per role (cloud)."""

    def __init__(self, cfg: Config, http: httpx.Client | None = None):
        self.cfg = cfg
        self._http = http  # a single injected client (tests) serves every model
        self._clients: dict[str, httpx.Client] = {}
        self._no_think_param: set[str] = set()

    def client_for(self, model_name: str) -> httpx.Client:
        if self._http is not None:
            return self._http
        url = self.cfg.ollama_url_for(model_name)
        if url not in self._clients:
            self._clients[url] = httpx.Client(base_url=url, timeout=self.cfg.llm.timeout_s)
        return self._clients[url]

    def _post_chat(self, payload: dict) -> str:
        last_exc: Exception | None = None
        http = self.client_for(payload["model"])
        for attempt in range(3):
            try:
                r = http.post("/api/chat", json=payload)
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
        if model.think is not None and model.name not in self._no_think_param:
            payload["think"] = model.think

        errors: list[str] = []
        for _ in range(2):
            raw = strip_thinking(self._post_chat(payload))
            try:
                return schema.model_validate(json.loads(raw))
            except (json.JSONDecodeError, ValidationError) as e:
                errors.append(str(e)[:200])
        raise LLMError(f"{model.name} returned invalid JSON for {schema.__name__}: {errors}")


def prepare_models(cfg: Config, names: list[str] | None = None, log: Callable[[str], None] = print,
                   timeout_s: float = 900, check: Callable[[], None] | None = None) -> dict[str, float]:
    """Wait until the Ollama serving each model answers, all in parallel. With `llm.warm_up` also load
    each model (an empty generate), so on Cloud Run the cold starts and weight loads overlap instead of
    landing on the first debate turn. Logs each model as it becomes ready; `check` is called while
    waiting and may raise to abandon the wait (e.g. on cancel). Returns seconds until each was ready."""
    names = names or cfg.models.unique_names()
    urls = cfg.ollama_urls_by_model(names)
    log(f"waiting for {len(names)} model server(s): {', '.join(sorted(set(urls.values())))}")

    def ready(name: str) -> float:
        t0 = time.monotonic()
        with httpx.Client(base_url=urls[name], timeout=timeout_s) as c:
            while True:
                if check:
                    check()
                try:
                    code = c.get("/api/version", timeout=60).status_code
                    if code in (401, 403):
                        raise LLMError(
                            f"ollama for {name} at {urls[name]} rejected the request (HTTP {code}). If this is a "
                            "Cloud Run proxy, its gcloud credentials were not accepted: see gcp/README.md "
                            "(Troubleshooting).")
                    if code < 500:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() - t0 > timeout_s:
                    raise LLMError(f"ollama for {name} is not reachable at {urls[name]}")
                time.sleep(3)
            if cfg.llm.warm_up:
                # Load with the context size the debate uses: a different num_ctx makes Ollama reload the
                # model on the first real request (measured: +45-60 s per model on Cloud Run).
                r = c.post("/api/generate", json={"model": name, "prompt": "", "keep_alive": cfg.llm.keep_alive,
                                                  "options": {"num_ctx": cfg.llm.num_ctx}})
                if r.status_code != 200:
                    raise LLMError(f"warm-up of {name} failed: {r.status_code} {r.text[:200]}")
        secs = time.monotonic() - t0
        log(f"  {name}: ready in {secs:.0f}s")
        return secs

    pool = ThreadPoolExecutor(max_workers=len(names))
    futures = {pool.submit(ready, n): n for n in names}
    try:
        pending = set(futures)
        while pending:
            done, pending = wait(pending, timeout=1, return_when=FIRST_EXCEPTION)
            for f in done:
                f.result()  # re-raise the first failure
            if check:
                check()
        return {futures[f]: f.result() for f in futures}
    finally:
        # Don't block on a warm-up still in flight after a cancel or failure; it finishes on its own.
        pool.shutdown(wait=False, cancel_futures=True)
