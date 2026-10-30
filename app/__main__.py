"""CLI entry point: python -m app <command>."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

from app.config import Config, load_config
from app.llm import LLMError, OllamaClient, prepare_models
from app.orchestrator import Orchestrator, new_state
from app.safety import TopicRejected, check_topic
from app.state import DebateState, Phase
from app.tools.search import CacheMiss, DiskCache, SearxResearcher
from app.tools.tts import KokoroClient


def wait_for(name: str, url: str, timeout_s: float = 300) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            if httpx.get(url, timeout=5).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() > deadline:
            sys.exit(f"{name} is not reachable at {url}")
        print(f"waiting for {name} at {url} ...")
        time.sleep(3)


def ready_models(cfg: Config, names: list[str] | None = None) -> None:
    try:
        prepare_models(cfg, names)
    except LLMError as e:
        sys.exit(str(e))


def build(cfg: Config, *, search: bool, audio: bool, replay: bool) -> Orchestrator:
    s = cfg.services
    ready_models(cfg)
    researcher = None
    if search:
        if not replay:
            wait_for("searxng", f"{s.searxng_url}/healthz")
        researcher = SearxResearcher(cfg, DiskCache(s.cache_dir, replay=replay))
    tts = None
    if audio:
        wait_for("kokoro", f"{s.kokoro_url}/health", timeout_s=600)
        tts = KokoroClient(cfg, s.cache_dir / "tts")
    return Orchestrator(cfg, OllamaClient(cfg), researcher, tts)


def run_new(cfg: Config, topic: str, args, seed_state: DebateState | None = None) -> DebateState:
    try:
        check_topic(topic, cfg, None)  # denylist first: a refused topic never wakes the model servers
    except TopicRejected as e:
        sys.exit(f"Refused: {e}")
    orch = build(cfg, search=not args.no_search, audio=not args.no_audio, replay=args.replay)
    try:
        check_topic(topic, cfg, orch.llm)
    except TopicRejected as e:
        sys.exit(f"Refused: {e}")
    state = new_state(cfg, topic)
    if seed_state is not None:
        state.queries = dict(seed_state.queries)
        state.counter_claim = seed_state.counter_claim
    print(f"run dir: {state.run_dir}")
    state.save()
    try:
        orch.run(state)
    except CacheMiss as e:
        sys.exit(f"{e}\nRun the debate once online to populate the cache.")
    print(f"done: {state.run_dir}")
    return state


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="tech-debate")
    sub = p.add_subparsers(dest="cmd", required=True)

    def flags(sp):
        sp.add_argument("--no-audio", action="store_true", help="skip Kokoro and MP3 rendering")
        sp.add_argument("--no-search", action="store_true", help="debate without web evidence")
        sp.add_argument("--replay", action="store_true", help="use only cached search results")

    d = sub.add_parser("debate", help="run a debate on TOPIC")
    d.add_argument("topic")
    flags(d)
    flags(sub.add_parser("demo", help="run the canned demo topic"))
    r = sub.add_parser("replay", help="re-run RUN_DIR's topic and queries from the search cache only")
    r.add_argument("run_dir", type=Path)
    flags(r)
    res = sub.add_parser("resume", help="continue an interrupted run")
    res.add_argument("run_dir", type=Path)
    flags(res)
    ren = sub.add_parser("render", help="rebuild transcript, captions and audio for RUN_DIR")
    ren.add_argument("run_dir", type=Path)
    ren.add_argument("--no-audio", action="store_true")
    ct = sub.add_parser("check-topic", help="run only the topic filter")
    ct.add_argument("topic")

    args = p.parse_args(argv)
    cfg = load_config()

    if args.cmd == "debate":
        run_new(cfg, args.topic, args)
    elif args.cmd == "demo":
        run_new(cfg, cfg.demo_topic, args)
    elif args.cmd == "replay":
        args.replay = True
        old = DebateState.load(args.run_dir)
        run_new(cfg, old.topic, args, seed_state=old)
    elif args.cmd == "resume":
        state = DebateState.load(args.run_dir)
        build(cfg, search=not args.no_search, audio=not args.no_audio, replay=args.replay).run(state)
    elif args.cmd == "render":
        state = DebateState.load(args.run_dir)
        tts = None
        if not args.no_audio:
            wait_for("kokoro", f"{cfg.services.kokoro_url}/health", timeout_s=600)
            tts = KokoroClient(cfg, cfg.services.cache_dir / "tts")
        orch = Orchestrator(cfg, llm=None, researcher=None, tts=tts)  # type: ignore[arg-type]
        orch.render(state)
        if Phase.RENDER not in state.phases_done:
            state.phases_done.append(Phase.RENDER)
        state.save()
    elif args.cmd == "check-topic":
        try:
            check_topic(args.topic, cfg, None)
            ready_models(cfg, [cfg.models.judge.name])  # only the judge classifies topics
            check_topic(args.topic, cfg, OllamaClient(cfg))
            print("OK: allowed")
        except TopicRejected as e:
            sys.exit(f"Refused: {e}")


if __name__ == "__main__":
    main()
