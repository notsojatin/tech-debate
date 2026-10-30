# Web UI: fix plan

> **Status: all 16 fixes implemented and re-verified in cloud mode on 2026-10-30.**
> - **Tests:** 60 pass, including new tests for cross-origin, 404s and run IDs, warm-up `num_ctx`, cancel mid-warm-up / mid-turn / between judge passes, and live-clip backfill and pruning.
> - **Live check:**
>   - `make up MODE=cloud` rebuilt the app image by itself.
>   - A cross-origin POST gets 403, and `/api/nope` gets 404.
>   - First chat per model after warm-up took 1.6–2.7 s, and rebuttal round 2 after a resume took 18 s, down from 60 s.
>   - Cancel during a turn stopped after one model call (7 s).
>   - After the cancel, the screen matched `state.json`. Resume finished with 8 turns and all 10 live clips.
> - **Not exercised live:**
>   - A fully cold warm-up: the GPU instances were still warm from the previous test.
>   - The UI's reconnect after a dropped connection: only built and type-checked.

These fixes come from reviewing the uncommitted web UI changes and from a live test in cloud mode on 2026-10-30. That test ran a debate with the Pro and Con models swapped, cancelled it partway through rebuttals, then resumed it to the end.

## What already works

- **Tests and build:** 53 Python tests pass, and `npm run build` succeeds.
- **Cloud routing with swapped roles:** qwen3:14b, playing Pro, went to its own qwen service, and gpt-oss:20b, playing Con, went to the gpt-oss service.
- **Live updates:** events stream in order, and each turn's live audio clip is ready about 10 s after the turn finishes.
- **Cancel and resume:** cancel stopped the run about 2 s after the request. Resume then finished it with 8 turns and no duplicates, and wrote the MP3, captions and transcript. The final render took only 21 s because it reused the cached voice clips.
- **UI:** the run list, phase timings, evidence ledger, score table (with the real criterion names) and MP3 player all render, with no console errors.
- **Seeking:** the MP3 supports byte-range requests (HTTP 206), so the player can jump around.

## Fixes, in priority order

### P0: security, cost and broken upgrades

1. **Any website can start debates.**
   - **Problem:** `app/server.py` adds `CORSMiddleware(allow_origins=["*"])`. A cross-origin POST to `/api/debates` gets `access-control-allow-origin: *` (verified). There's no authentication, so any page you visit could start debates on your Cloud Run GPUs.
   - **Fix:** remove the CORS middleware. The Vite dev server already proxies `/api`, so the browser only ever sees one origin. Also reject POSTs whose `Origin` header isn't the server's own host.
   - **Test:** a cross-origin POST is rejected with 403.
2. **`make serve` listens on the whole network.**
   - **Problem:** `serve --host` defaults to `0.0.0.0`.
   - **Fix:** default to `127.0.0.1`. The Docker image passes `--host 0.0.0.0` explicitly, and Compose already publishes the port on `127.0.0.1` only.
3. **`make up` starts a stale app image.**
   - **Problem:** it builds only `$(SERVICES)`, then runs `docker compose up -d --no-deps app` without `--build`. On an existing checkout the old image crash-loops with `invalid choice: 'serve'` (seen in this test).
   - **Fix:** add `--build` to that line.

### P1: correctness

4. **Warm-up loads every model twice.** *(Bug from the Cloud Run work, not the web UI.)*
   - **Problem:** `prepare_models` in `app/llm.py` warms each model with `/api/generate` without `options.num_ctx`. Ollama loads it at its default context size, then reloads it at 8192 on the first real request. Measured: each model's first chat after warm-up took 47–63 s, and later ones took 2–9 s. The same double reload added about 40 s to rebuttal round 2 after resume.
   - **Fix:** send `options: {num_ctx: cfg.llm.num_ctx}` in the warm-up request.
   - **Test:** the warm-up request includes `num_ctx`.
5. **Cancel only takes effect between turns.**
   - **Problem:** `_check_cancel` runs between phases and turns, but not inside `agents.run_turn` (between retries, or before the side-check), inside `judge.judge` (between its two passes), or inside `prepare_models` (up to 15 min on cold GPUs). A turn in progress always runs to completion, and so does warm-up.
   - **Fix:** pass `cancel_check` into those places. In `prepare_models`, check it in the polling loop, and run the warm-up request in a thread so a cancel stops waiting on it.
   - **Test:** a cancel during a retry stops before the next attempt.
6. **Resume leaves gaps in the live audio.**
   - **Problem:** when a run is cancelled, voice clips still waiting in the queue are skipped, and resume only makes clips for new turns. In this test `turn_03_rebuttal_1_con.wav` never existed, so the live player skips that turn.
   - **Fix:** at the start of `Orchestrator.run`, when live audio is on, queue a clip for any finished turn (plus the intro and verdict) whose `segments/*.wav` file is missing.
7. **The run screen disagrees with the saved file after a cancel.**
   - **Problem:** `get_debate_detail` returns the in-memory state, which still holds the half-finished turn (5 turns), while `state.json` has 4. After a resume, the 5th turn disappears from the screen.
   - **Fix:** on cancel, reload the state from disk into the run's record before broadcasting `debate_cancelled`.
8. **Unknown `/api/...` paths return 200 with HTML.**
   - **Problem:** the browser-app fallback route catches everything.
   - **Fix:** return 404 JSON for any path starting with `api/` inside `serve_spa`.
   - **Test:** `GET /api/nope` returns 404.
9. **Run IDs aren't checked.**
   - **Problem:** `run_id` is joined straight onto `out_dir`. Nothing leaked in testing, but it isn't validated.
   - **Fix:** require `^[0-9]{8}-[0-9]{6}-[a-z0-9-]+$` (the format `new_state` creates) on every `{run_id}` route, and make segment filenames match `^[a-z0-9_]+\.wav$`.
10. **Events can be lost when a page connects.**
    - **Problem:** `/events` takes the snapshot and only then subscribes to updates, so anything that happens in between is missed.
    - **Fix:** subscribe first, then take the snapshot.
11. **`debate_done` is sent twice.**
    - **Problem:** the orchestrator sends it, then the worker sends it again with `state`. The stream closes on the first one, so the copy that carries the state never arrives.
    - **Fix:** keep only the worker's version, so the orchestrator's `on_event` doesn't send it.
12. **A dropped live connection never comes back.**
    - **Problem:** `es.onerror` in `web/src/App.tsx` closes the connection for good.
    - **Fix:** while the run is still active, reconnect with backoff, and use the snapshot to catch up.

### P2: UX and housekeeping

13. **No warm-up progress for 2–3 minutes.**
    - **Problem:** `prepare_models` only logs once every model is ready, so the screen sits on "waiting for 3 model servers" the whole time.
    - **Fix:** log each model as it becomes ready (inside `ready()`), and show those lines on the screen.
14. **README:**
    - The only change so far is an empty row added to the licenses table. Remove it.
    - Document the web UI: `make up` → http://localhost:8000, `make serve`, and the dev setup with `npm run dev`.
    - Bare `docker compose up` now starts the server instead of producing the demo debate, so update the quickstart (`make demo` still produces the demo).
15. **Version pinning.**
    - Pin the build stage to an exact `node:22.x.y-slim` version, in line with the repo's pin-everything rule.
    - Add `web/tsconfig.tsbuildinfo` to `.gitignore`. It's a build artifact and is currently untracked but not ignored.
16. **Two app instances at import.**
    - **Problem:** `app = create_app()` at module level builds a second `DebateManager` (and loads the config) whenever `app.server` is imported, including by `serve`.
    - **Fix:** create it lazily, or drop it and point uvicorn at a factory.

## Verification

- `make test`, including new tests for fixes 1, 4, 5, 8 and 9.
- Rebuild without `--build` habits (`make up MODE=cloud` on a stale image) and confirm the server starts.
- One cloud debate:
  - First chat per model under 10 s after warm-up.
  - Cancel during a retry stops within one model call.
  - Resume backfills the missing clip.
  - A cross-origin POST gets 403.
