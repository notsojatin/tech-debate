"""FastAPI server for the Tech Debate web application (REST + SSE + static SPA)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import render
from app.config import ROLES, Config, ROOT, cfg_for_state, load_config
from app.llm import ChatClient, LLMError, OllamaClient, prepare_models
from app.orchestrator import DebateCancelled, Orchestrator, new_state, phase_plan
from app.safety import TopicRejected, check_topic
from app.state import MAX_REBUTTAL_ROUNDS, DebateState, Phase
from app.tools.search import DiskCache, Researcher, SearxResearcher
from app.tools.tts import KokoroClient

WEB_DIST = ROOT / "web" / "dist"
RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[a-z0-9-]+$")      # as created by orchestrator.new_state
SEGMENT_RE = re.compile(r"^[a-z0-9_]+\.wav$")
# Browser origins allowed to make state-changing requests besides the server's own (the Vite dev server).
DEV_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}


class CreateDebateReq(BaseModel):
    topic: str
    models: dict[str, str] | None = None
    rebuttal_rounds: int | None = Field(None, ge=1, le=MAX_REBUTTAL_ROUNDS)  # None: the configured default
    speech_length: Literal["short", "standard", "long"] | None = None
    no_search: bool = False
    no_audio: bool = False
    replay: bool = False


class ResumeDebateReq(BaseModel):
    no_search: bool = False
    no_audio: bool = False
    replay: bool = False


@dataclass
class ActiveRun:
    run_id: str
    state: DebateState
    cfg: Config
    loop: asyncio.AbstractEventLoop
    status: str = "running"  # running | cancelling | cancelled | done | error
    error: str | None = None
    current_step: dict[str, Any] = field(default_factory=lambda: {"type": "starting", "message": "Starting debate..."})
    segments: list[dict[str, Any]] = field(default_factory=list)
    cancel_requested: bool = False
    subscribers: set[asyncio.Queue] = field(default_factory=set)

    def broadcast(self, event: dict[str, Any]) -> None:
        payload = {**event, "timestamp": round(time.time(), 3)}
        etype = payload.get("type", "")
        if etype == "segment_audio_ready":
            # ?v= busts the browser cache when a resumed run re-synthesizes a clip under the same name.
            seg_entry = {
                **payload,
                "url": f"/api/debates/{self.run_id}/audio/segments/{payload['filename']}?v={int(payload['timestamp'] * 1000)}",
            }
            self.segments = [s for s in self.segments if s["segment_id"] != seg_entry["segment_id"]] + [seg_entry]
            payload = seg_entry
        elif etype not in ("evidence_added",):
            self.current_step = payload

        def _push() -> None:
            for q in list(self.subscribers):
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass

        try:
            self.loop.call_soon_threadsafe(_push)
        except RuntimeError:
            pass


def _parse_run_timestamp(run_id: str) -> str:
    m = re.match(r"^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})-", run_id)
    if m:
        y, mo, d, hh, mm, ss = m.groups()
        return f"{y}-{mo}-{d}T{hh}:{mm}:{ss}"
    return datetime.now().isoformat(timespec="seconds")


def _wait_http(name: str, url: str, cancel_check: Callable[[], bool], timeout_s: float = 120) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        if cancel_check():
            raise DebateCancelled("Cancelled while waiting for service")
        try:
            if httpx.get(url, timeout=5).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() > deadline:
            raise RuntimeError(f"{name} is not reachable at {url}")
        time.sleep(2)


class DebateManager:
    def __init__(
        self,
        cfg: Config | None = None,
        *,
        llm_factory: Callable[[Config], ChatClient] | None = None,
        researcher_factory: Callable[[Config, bool], Researcher | None] | None = None,
        tts_factory: Callable[[Config], KokoroClient | None] | None = None,
        skip_service_wait: bool = False,
    ):
        self.cfg = cfg or load_config()
        self.llm_factory = llm_factory
        self.researcher_factory = researcher_factory
        self.tts_factory = tts_factory
        self.skip_service_wait = skip_service_wait
        self._lock = threading.Lock()
        self.active: ActiveRun | None = None

    def run_dir(self, run_id: str) -> Path:
        """Directory of a run, or 404 for anything that is not a well-formed run id with a state.json."""
        run_dir = self.cfg.services.out_dir / run_id
        if not RUN_ID_RE.match(run_id) or not (run_dir / "state.json").exists():
            raise HTTPException(status_code=404, detail=f"Debate '{run_id}' not found")
        return run_dir

    def is_busy(self) -> bool:
        with self._lock:
            return self.active is not None and self.active.status in ("running", "cancelling")

    def list_debates(self) -> list[dict[str, Any]]:
        out_dir = self.cfg.services.out_dir
        if not out_dir.exists():
            return []
        items: list[dict[str, Any]] = []
        active = self.active
        for d in sorted(out_dir.iterdir(), key=lambda p: p.name, reverse=True):
            if not d.is_dir() or not (d / "state.json").exists():
                continue
            try:
                st = active.state if (active and active.run_id == d.name) else DebateState.load(d)
            except Exception:
                continue
            status = self._status_for(d.name, st)
            has_audio = (d / "debate.mp3").exists() or (d / "debate.wav").exists()
            items.append({
                "id": d.name,
                "topic": st.topic,
                "created_at": _parse_run_timestamp(d.name),
                "models": st.models,
                "phases_done": [p.value for p in st.phases_done],
                "status": status,
                "winner": st.judge.get("winner") if st.judge else None,
                "totals": st.judge.get("totals") if st.judge else None,
                "rebuttal_rounds": st.rebuttal_rounds or self.cfg.debate.rebuttal_rounds,
                "turn_count": len(st.turns),
                "evidence_count": len(st.ledger.items),
                "has_audio": has_audio,
            })
        return items

    def _status_for(self, run_id: str, state: DebateState) -> str:
        active = self.active
        if active and active.run_id == run_id:
            return active.status
        if Phase.DONE in state.phases_done:
            return "done"
        return "interrupted"

    def get_debate_detail(self, run_id: str) -> dict[str, Any]:
        run_dir = self.run_dir(run_id)
        active = self.active if (self.active and self.active.run_id == run_id) else None
        state = active.state if active else DebateState.load(run_dir)
        run_cfg = active.cfg if active else cfg_for_state(self.cfg, state)
        status = self._status_for(run_id, state)

        has_mp3 = (run_dir / "debate.mp3").exists()
        has_wav = (run_dir / "debate.wav").exists()
        srt_cues: list[dict[str, Any]] = []
        srt_path = run_dir / "debate.srt"
        if srt_path.exists():
            srt_cues = render.parse_srt(srt_path.read_text(encoding="utf-8"))

        if active:
            segments = list(active.segments)
        else:
            segments = self._scan_segments(run_id, run_dir)

        return {
            "id": run_id,
            "status": status,
            "error": active.error if active else None,
            "current_step": active.current_step if active else None,
            "state": json.loads(state.model_dump_json()),
            "phases_plan": [p.value for p in phase_plan(run_cfg)],
            "rebuttal_rounds": run_cfg.debate.rebuttal_rounds,
            "speech_length": run_cfg.debate.speech_length,
            "has_mp3": has_mp3,
            "has_wav": has_wav,
            "audio_url": f"/api/debates/{run_id}/audio/master" if (has_mp3 or has_wav) else None,
            "srt_cues": srt_cues,
            "segments": segments,
        }

    def _scan_segments(self, run_id: str, run_dir: Path) -> list[dict[str, Any]]:
        seg_dir = run_dir / "segments"
        if not seg_dir.is_dir():
            return []
        out: list[dict[str, Any]] = []
        for wav in sorted(seg_dir.glob("*.wav")):
            if not SEGMENT_RE.match(wav.name):
                continue
            stem = wav.stem
            speaker = "narrator"
            turn_index: int | None = None
            m = re.match(r"^turn_(\d+)_(.+)_(pro|con)$", stem)
            if m:
                turn_index = int(m.group(1))
                speaker = m.group(3)
            out.append({
                "segment_id": stem,
                "filename": wav.name,
                "speaker": speaker,
                "turn_index": turn_index,
                "url": f"/api/debates/{run_id}/audio/segments/{wav.name}?v={int(wav.stat().st_mtime * 1000)}",
            })
        return out

    def start_new(self, req: CreateDebateReq, loop: asyncio.AbstractEventLoop) -> dict[str, Any]:
        topic = req.topic.strip()
        try:
            run_cfg = self.cfg.with_role_models(req.models) if req.models else self.cfg
            run_cfg = run_cfg.with_debate_settings(req.rebuttal_rounds, req.speech_length)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        # Fast synchronous denylist gate before spawning background thread.
        try:
            check_topic(topic, run_cfg, None)
        except TopicRejected as e:
            raise HTTPException(status_code=422, detail=str(e))

        with self._lock:
            if self.active is not None and self.active.status in ("running", "cancelling"):
                raise HTTPException(
                    status_code=409,
                    detail=f"Another debate ('{self.active.run_id}') is currently running.",
                )
            state = new_state(run_cfg, topic)
            state.save()
            run_id = state.run_dir.name
            active = ActiveRun(run_id=run_id, state=state, cfg=run_cfg, loop=loop)
            self.active = active

        t = threading.Thread(
            target=self._worker_run,
            args=(active, not req.no_search, not req.no_audio, req.replay, True),
            daemon=True,
        )
        t.start()
        return self.get_debate_detail(run_id)

    def resume_existing(self, run_id: str, req: ResumeDebateReq, loop: asyncio.AbstractEventLoop) -> dict[str, Any]:
        run_dir = self.run_dir(run_id)
        state = DebateState.load(run_dir)
        if Phase.DONE in state.phases_done:
            return self.get_debate_detail(run_id)

        run_cfg = cfg_for_state(self.cfg, state)

        with self._lock:
            if self.active is not None and self.active.status in ("running", "cancelling"):
                raise HTTPException(
                    status_code=409,
                    detail=f"Another debate ('{self.active.run_id}') is currently running.",
                )
            active = ActiveRun(
                run_id=run_id,
                state=state,
                cfg=run_cfg,
                loop=loop,
                segments=self._scan_segments(run_id, run_dir),
            )
            self.active = active

        t = threading.Thread(
            target=self._worker_run,
            args=(active, not req.no_search, not req.no_audio, req.replay, False),
            daemon=True,
        )
        t.start()
        return self.get_debate_detail(run_id)

    def cancel(self, run_id: str) -> dict[str, Any]:
        self.run_dir(run_id)
        with self._lock:
            if not self.active or self.active.run_id != run_id:
                raise HTTPException(status_code=404, detail=f"Debate '{run_id}' is not actively running")
            self.active.cancel_requested = True
            self.active.status = "cancelling"
            self.active.broadcast({"type": "debate_cancelling", "message": "Stopping after current step..."})
        return self.get_debate_detail(run_id)

    def _worker_run(
        self,
        active: ActiveRun,
        use_search: bool,
        use_audio: bool,
        replay: bool,
        run_topic_llm_check: bool,
    ) -> None:
        cfg = active.cfg
        state = active.state
        cancel_check = lambda: active.cancel_requested  # noqa: E731

        def raise_if_cancelled() -> None:
            if active.cancel_requested:
                raise DebateCancelled("Debate cancelled by user")

        try:
            llm = self.llm_factory(cfg) if self.llm_factory else OllamaClient(cfg)
            if not self.skip_service_wait and self.llm_factory is None:
                active.broadcast({"type": "service_status", "service": "ollama", "message": "Waiting for model servers..."})
                prepare_models(
                    cfg,
                    log=lambda msg: active.broadcast({"type": "service_log", "message": msg.strip()}),
                    check=raise_if_cancelled,
                )

            if run_topic_llm_check and not state.phases_done:
                active.broadcast({"type": "topic_gate", "status": "checking", "message": "Verifying technology motion..."})
                check_topic(state.topic, cfg, llm)
                active.broadcast({"type": "topic_gate", "status": "passed", "message": "Topic approved"})

            researcher: Researcher | None = None
            if use_search:
                if self.researcher_factory is not None:
                    researcher = self.researcher_factory(cfg, replay)
                else:
                    if not replay and not self.skip_service_wait:
                        active.broadcast({"type": "service_status", "service": "searxng", "message": "Checking SearXNG search engine..."})
                        _wait_http("searxng", f"{cfg.services.searxng_url}/healthz", cancel_check)
                    researcher = SearxResearcher(cfg, DiskCache(cfg.services.cache_dir, replay=replay))

            tts: KokoroClient | None = None
            if use_audio:
                if self.tts_factory is not None:
                    tts = self.tts_factory(cfg)
                else:
                    if not self.skip_service_wait:
                        active.broadcast({"type": "service_status", "service": "kokoro", "message": "Checking Kokoro TTS service..."})
                        _wait_http("kokoro", f"{cfg.services.kokoro_url}/health", cancel_check, timeout_s=300)
                    tts = KokoroClient(cfg, cfg.services.cache_dir / "tts")

            orch = Orchestrator(
                cfg,
                llm,
                researcher,
                tts,
                log=lambda msg: None,
                on_event=active.broadcast,
                cancel_check=cancel_check,
                live_tts=True,
            )
            orch.run(state)
            active.status = "done"
            active.broadcast({"type": "debate_done", "status": "done", "state": json.loads(state.model_dump_json())})

        except DebateCancelled:
            # Drop the half-finished phase: show exactly what resume will continue from (state.json),
            # and delete live clips that belong to turns that were discarded with it.
            active.state = DebateState.load(state.run_dir)
            render.prune_live_segments(active.state)
            active.segments = self._scan_segments(active.run_id, state.run_dir)
            active.status = "cancelled"
            active.broadcast({"type": "debate_cancelled", "status": "cancelled", "message": "Debate cancelled"})
        except TopicRejected as e:
            active.status = "error"
            active.error = f"Topic refused: {e}"
            active.broadcast({"type": "debate_error", "status": "error", "error": active.error})
            # If rejected at topic gate before any phase ran, remove the empty run directory so it doesn't clutter history.
            if not state.phases_done and state.run_dir.exists():
                shutil.rmtree(state.run_dir, ignore_errors=True)
        except Exception as e:
            active.status = "error"
            active.error = str(e)
            active.broadcast({"type": "debate_error", "status": "error", "error": active.error})


def create_app(manager: DebateManager | None = None) -> FastAPI:
    mgr = manager or DebateManager()
    app = FastAPI(title="Tech Debate API", version="0.1.0")
    app.state.manager = mgr

    @app.middleware("http")
    async def same_origin_writes(request: Request, call_next):
        # No CORS: other websites must not be able to start debates (they cost GPU time). Browsers always
        # send Origin on cross-site POSTs; reject any that is not this server or the Vite dev server.
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            own = {f"http://{request.headers.get('host', '')}", f"https://{request.headers.get('host', '')}"}
            if origin and origin not in own and origin not in DEV_ORIGINS:
                return JSONResponse({"detail": "Cross-origin requests are not allowed"}, status_code=403)
        return await call_next(request)

    @app.get("/api/models")
    def get_models() -> dict[str, Any]:
        cfg = mgr.cfg
        profile = os.environ.get("DEBATE_PROFILE") or ("cloud" if cfg.services.ollama_urls else "local")
        curated = [
            {
                "name": m.name,
                "label": render.spoken_model(m.name),
                "think": m.think,
                "temperature": m.temperature,
            }
            for m in cfg.curated_models()
        ]
        defaults = {r: cfg.models.for_role(r).name for r in ROLES}
        presets = list(cfg.preset_topics) if cfg.preset_topics else [cfg.demo_topic]
        debate_options = {
            "rebuttal_rounds": {"min": 1, "max": MAX_REBUTTAL_ROUNDS, "default": cfg.debate.rebuttal_rounds},
            "speech_lengths": {name: w.model_dump() for name, w in cfg.debate.speech_lengths.items()},
            "default_speech_length": cfg.debate.speech_length,
        }
        return {
            "profile": profile,
            "models": curated,
            "defaults": defaults,
            "demo_topic": cfg.demo_topic,
            "preset_topics": presets,
            "debate_options": debate_options,
            "active_run_id": mgr.active.run_id if mgr.is_busy() and mgr.active else None,
        }

    @app.get("/api/debates")
    def list_debates() -> list[dict[str, Any]]:
        return mgr.list_debates()

    @app.get("/api/debates/{run_id}")
    def get_debate(run_id: str) -> dict[str, Any]:
        return mgr.get_debate_detail(run_id)

    @app.post("/api/debates", status_code=201)
    async def create_debate(req: CreateDebateReq) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        return mgr.start_new(req, loop)

    @app.post("/api/debates/{run_id}/resume")
    async def resume_debate(run_id: str, req: ResumeDebateReq | None = None) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        return mgr.resume_existing(run_id, req or ResumeDebateReq(), loop)

    @app.post("/api/debates/{run_id}/cancel")
    def cancel_debate(run_id: str) -> dict[str, Any]:
        return mgr.cancel(run_id)

    @app.get("/api/debates/{run_id}/events")
    async def stream_debate_events(run_id: str):
        mgr.run_dir(run_id)
        active = mgr.active if (mgr.active and mgr.active.run_id == run_id) else None
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        # Subscribe before taking the snapshot so no event falls in between; the client drops duplicates.
        if active and active.status in ("running", "cancelling"):
            active.subscribers.add(queue)
        detail = mgr.get_debate_detail(run_id)

        async def event_generator():
            try:
                yield f"event: snapshot\ndata: {json.dumps(detail)}\n\n"
                if not active or active.status not in ("running", "cancelling"):
                    return
                while True:
                    try:
                        evt = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        if active.status not in ("running", "cancelling"):
                            break
                        continue
                    yield f"data: {json.dumps(evt)}\n\n"
                    if evt.get("type") in ("debate_done", "debate_error", "debate_cancelled"):
                        break
            finally:
                if active:
                    active.subscribers.discard(queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/debates/{run_id}/audio/master")
    def get_master_audio(run_id: str):
        run_dir = mgr.run_dir(run_id)
        mp3 = run_dir / "debate.mp3"
        if mp3.exists():
            return FileResponse(mp3, media_type="audio/mpeg", filename=f"{run_id}.mp3")
        wav = run_dir / "debate.wav"
        if wav.exists():
            return FileResponse(wav, media_type="audio/wav", filename=f"{run_id}.wav")
        raise HTTPException(status_code=404, detail="Master audio not yet rendered")

    @app.get("/api/debates/{run_id}/audio/segments/{filename}")
    def get_segment_audio(run_id: str, filename: str):
        if not SEGMENT_RE.match(filename):
            raise HTTPException(status_code=400, detail="Invalid filename")
        seg_path = mgr.run_dir(run_id) / "segments" / filename
        if not seg_path.exists():
            raise HTTPException(status_code=404, detail="Segment audio not found")
        return FileResponse(seg_path, media_type="audio/wav", filename=filename)

    if WEB_DIST.is_dir():
        assets_dir = WEB_DIST / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}")
        def serve_spa(full_path: str):
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found")
            candidate = (WEB_DIST / full_path).resolve()
            if full_path and candidate.is_file() and str(candidate).startswith(str(WEB_DIST.resolve())):
                return FileResponse(candidate)
            return FileResponse(WEB_DIST / "index.html")

    return app

