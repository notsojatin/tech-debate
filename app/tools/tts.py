"""Text cleanup for speech and per-sentence Kokoro synthesis."""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

import httpx

from app.config import Config, load_yaml

SAMPLE_RATE = 24000  # Kokoro outputs 24 kHz mono 16-bit PCM

_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_CITE_TAG = re.compile(r"[\[(]\s*E\d+(?:\s*[,;]\s*E\d+)*\s*[\])]|\bE\d+\b")
_URL = re.compile(r"(https?://\S+|www\.\S+)")
_MD_CHARS = re.compile(r"[*_`#>|~]+")
_TAG = re.compile(r"</?[a-zA-Z][^>]*(?:>|$)")
_NUM_REF = re.compile(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(]?[A-Z0-9])")
_CAPS = re.compile(r"\b[A-Z]{2,4}s?\b")
_UNITS = {"ms": "milliseconds", "s": "seconds", "x": "times", "KB": "kilobytes", "MB": "megabytes",
          "GB": "gigabytes", "TB": "terabytes", "k": "thousand", "K": "thousand", "M": "million"}
_UNIT_RE = re.compile(r"(?<![A-Za-z])(\d+(?:\.\d+)?)\s?(" + "|".join(sorted(_UNITS, key=len, reverse=True)) + r")\b")
# Shouted English words are read as words, not spelled out.
_COMMON = set("AN AND ARE BUT CAN FOR HAS HOW NEW NOT NOW ONE OUR OUT THE THIS TWO WAY WHY YOU ALL ANY BAD BIG "
              "BEST DO DOES DONT EVER JUST LESS MORE MUST NEED NO ONLY REAL SO VERY WILL WITH YES".split())


class Pronunciation:
    def __init__(self, data: dict | None = None):
        data = data if data is not None else load_yaml("pronunciations.yaml")
        self.replace: dict[str, str] = {str(k): str(v) for k, v in (data.get("replace") or {}).items()}
        self.say_as_word = {str(w) for w in (data.get("say_as_word") or [])}
        # Longest keys first so "CI/CD" wins over "CI".
        keys = sorted(self.replace, key=len, reverse=True)
        self._re = re.compile(
            "|".join(rf"(?<![\w-]){re.escape(k)}(?![\w-])" if k[0].isalnum() else re.escape(k) for k in keys)
        ) if keys else None

    def apply(self, text: str) -> str:
        if self._re:
            text = self._re.sub(lambda m: self.replace[m.group(0)], text)
        return _CAPS.sub(self._spell, text)

    def _spell(self, m: re.Match) -> str:
        tok = m.group(0)
        base, plural = (tok[:-1], "s") if tok.endswith("s") and tok[:-1].isupper() else (tok, "")
        if base in self.say_as_word or tok in self.say_as_word:
            return tok
        if tok in _COMMON:
            return tok.lower()
        return "-".join(base) + plural


def clean_for_speech(text: str, pron: Pronunciation) -> str:
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    text = _CITE_TAG.sub("", text)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    text = _TAG.sub("", text)
    text = _NUM_REF.sub("", text)
    text = _MD_CHARS.sub("", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    text = _UNIT_RE.sub(lambda m: f"{m.group(1)} {_UNITS[m.group(2)]}", text)
    text = re.sub(r"\s<\s*(?=\d)", " less than ", text).replace("<", "")
    text = pron.apply(text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]


class KokoroClient:
    def __init__(self, cfg: Config, cache_dir: Path, http: httpx.Client | None = None):
        self.cfg = cfg
        self.cache_dir = cache_dir
        self.http = http or httpx.Client(base_url=cfg.services.kokoro_url, timeout=120)
        cache_dir.mkdir(parents=True, exist_ok=True)

    def synth(self, text: str, voice: str) -> bytes:
        """Return raw 16-bit mono PCM at SAMPLE_RATE. Cached by (voice, speed, text)."""
        speed = self.cfg.voices.speed
        key = hashlib.sha256(f"{voice}\x00{speed}\x00{text}".encode()).hexdigest()[:24]
        path = self.cache_dir / f"{key}.pcm"
        if path.exists():
            return path.read_bytes()
        payload = {"model": "kokoro", "input": text, "voice": voice, "response_format": "pcm",
                   "speed": speed, "stream": False}
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = self.http.post("/v1/audio/speech", json=payload)
                r.raise_for_status()
                pcm = r.content
                if len(pcm) % 2:
                    pcm = pcm[:-1]
                path.write_bytes(pcm)
                return pcm
            except httpx.HTTPError as e:
                last = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"kokoro failed for {text[:60]!r}: {last}")
