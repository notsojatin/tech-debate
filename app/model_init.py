"""Init container: wait for Ollama, pull any missing models, and check digests against models.lock."""

from __future__ import annotations

import json
import os
import sys
import time

import httpx

from app.config import ROOT, load_config

LOCK = ROOT / "models.lock"


def wait(http: httpx.Client, timeout_s: float = 600) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            v = http.get("/api/version").json()["version"]
            print(f"ollama {v} is up at {http.base_url}")
            return
        except (httpx.HTTPError, ValueError, KeyError):
            print("waiting for ollama ...")
            time.sleep(3)
    sys.exit("ollama never came up")


def pull(http: httpx.Client, name: str) -> None:
    if http.post("/api/show", json={"model": name}).status_code == 200:
        print(f"{name}: present")
        return
    print(f"{name}: pulling")
    last = ""
    with http.stream("POST", "/api/pull", json={"model": name, "stream": True}, timeout=None) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            msg = json.loads(line)
            if "error" in msg:
                sys.exit(f"{name}: {msg['error']}")
            status = msg.get("status", "")
            if msg.get("total"):
                pct = int(100 * msg.get("completed", 0) / msg["total"])
                status = f"{status} {pct // 10 * 10}%"
            if status != last:
                print(f"  {name}: {status}")
                last = status
    print(f"{name}: done")


def digests(http: httpx.Client) -> dict[str, str]:
    return {m["name"]: m["digest"] for m in http.get("/api/tags").json().get("models", [])}


def main() -> None:
    cfg = load_config()
    http = httpx.Client(base_url=cfg.services.ollama_url, timeout=60)
    wait(http)
    names = cfg.models.unique_names()
    for name in names:
        pull(http, name)

    have = digests(http)
    current = {n: have.get(n, "") for n in names}
    locked = json.loads(LOCK.read_text()) if LOCK.exists() and LOCK.read_text().strip() else {}
    drift = {n: (locked[n], d) for n, d in current.items() if n in locked and locked[n] != d}
    for n, (old, new) in drift.items():
        print(f"WARNING: {n} digest {new[:12]} differs from models.lock {old[:12]} (the tag moved upstream)")
    if drift and os.environ.get("STRICT_MODELS") == "1":
        sys.exit("STRICT_MODELS=1 and model digests drifted")
    if os.environ.get("WRITE_MODEL_LOCK") == "1":
        LOCK.write_text(json.dumps({**locked, **current}, indent=2) + "\n")
        print(f"wrote {LOCK}")
    print("models ready")


if __name__ == "__main__":
    main()
