# tech-debate

Two open models debate a tech topic using real web evidence. A third model judges, and Kokoro reads the whole thing aloud. You get an MP3, captions and a cited transcript.

Everything runs locally with one command. No API keys and no accounts are needed.

| Service | Role |
|---|---|
| **Ollama** | runs the models, with JSON-schema structured output |
| **SearXNG** | self-hosted meta-search (JSON API) |
| **Kokoro** (via Kokoro-FastAPI) | text-to-speech on CPU or GPU |
| **app** | Python orchestrator (debate state machine, evidence ledger, judge, audio stitching) plus the web UI on port 8000 |
| **model-init** | one-shot container that pulls the pinned models on first start |

Default lineup (edit `config/debate.yaml`):

| Role | Model | Voice |
|---|---|---|
| Pro (for) | `qwen3:4b` | `am_michael` |
| Con (against) | `gemma3:4b` | `bf_emma` |
| Judge + narrator | `llama3.2:3b` | `bm_george` |

## Quickstart

```bash
git clone <this repo> && cd tech-debate
docker compose up          # cpu profile: pulls models, then serves the web UI
```

Open http://localhost:8000, pick a motion and the models, and press **Start Debate** (see [Web UI](#web-ui)). Runs land in `out/<timestamp>-<slug>/`.

For repeated use, the Makefile is nicer:

```bash
make up                                   # start services + pull models + web UI (MODE auto-detected)
make demo                                 # canned topic, from the command line
make debate TOPIC="Rust is better than Go for command-line tools"
make replay RUN=out/<run-dir>             # same topic + queries, search served from cache only
make render RUN=out/<run-dir>             # rebuild transcript/SRT/MP3, no LLM calls
make down
```

### Modes

| `MODE` | Ollama | Kokoro | When to use it |
|---|---|---|---|
| `cpu` (default for bare `docker compose up`) | container | CPU container | Works anywhere with Docker |
| `gpu` | container with NVIDIA GPU | GPU container | Linux/WSL with an NVIDIA card and the NVIDIA Container Toolkit |
| `host` (auto-picked on macOS when `ollama` is installed) | **your own Ollama** | CPU container | Apple Silicon. Docker on macOS can't use Metal, so native Ollama is several times faster |
| `cloud` | **Cloud Run GPUs**, one private service per model, scale-to-zero | CPU container | Bigger models (up to ~20B) without local hardware. See [gcp/README.md](gcp/README.md) |

With `make`, set the mode with `make up MODE=gpu` and so on. With plain compose, set it with `COMPOSE_PROFILES=gpu docker compose up`.

In host mode, model-init pulls the models into your local Ollama. On Linux, host mode needs Ollama listening on the Docker bridge: `OLLAMA_HOST=0.0.0.0 ollama serve`.

## Web UI

`make up` (or `docker compose up`) serves it at **http://localhost:8000**:
- **Choose:** a preset or custom motion, and which model plays Pro, Con and Judge.
- **Watch it live:** a phase stepper, the research queries and evidence ledger, turn cards with quoted rebuttal targets and retry badges, then the two-pass verdict.
- **Live audio:** each turn is voiced as soon as it's accepted and plays while the next turn is being written. When the debate ends, the player switches to the stitched MP3, with a transcript you can click to jump to any sentence.
- **History:** every run in `out/` is listed, with cancel and resume.

The server only listens on `127.0.0.1`. It refuses state-changing requests from other websites, because debates in cloud mode cost GPU time.

**Running it on the host instead of in Docker:**

```bash
make serve                       # API + built UI on 127.0.0.1:8000 (needs `npm run build` in web/ first)
cd web && npm ci && npm run dev  # UI dev server on :5173, proxying /api to :8000
```

The command-line tools (`make debate`, `make demo`, `make replay`, `make render`) work as before and share the same `out/` folder.

## What you get

```
out/20261029-153000-monorepos-are-better-than-polyrepos/
  debate.mp3        stitched audio (narrator intro, all turns, verdict)
  debate.srt        one caption per spoken sentence, speaker-tagged
  debate.wav        lossless master
  transcript.md     turns, quoted rebuttal targets, footnoted sources, score table
  judge.json        both judge passes, averaged scores, position-consistency flag
  evidence.json     the evidence ledger (E1, E2, …) with URLs and snippets
  state.json        full checkpoint; `make resume` / `make render` read it
```

## How a debate runs

It's a fixed state machine, not free-form agents chatting, so it stays on topic and always ends.

```
0. Topic gate  → denylist + model check that the topic is about tech
1. Research    → each side writes 3 queries → SearXNG → fetch top pages → trafilatura
                 → best-matching passage stored in the evidence ledger as E1, E2…
2. Openings    → Pro, then Con (≤120 words, must cite ledger IDs)
3. Rebuttals   → 2 rounds; each must quote the opponent verbatim and attack that line
4. Closings    → one sentence each
5. Judge       → rubric JSON, run twice with sides anonymised and order swapped, averaged
6. Render      → per-sentence TTS → WAV/MP3 + SRT + transcript.md
```

Each turn is requested as structured JSON (Ollama `format` with a JSON schema) and **validated in code**:
- **Citations** must be IDs that exist in the ledger. Models never write URLs.
- **Rebuttal quotes** must appear (near-)verbatim in the opponent's last turn.
- **Concessions** ("I agree", "fair point", …) are rejected.
- **New points** are checked against that side's earlier points and rejected if they are near-duplicates.
- **Word limits** are enforced.
- **Text read aloud** must be plain sentences. Inline IDs like `(E3)` are moved into `cites` automatically. Tags such as `<evidence>` cause a retry.
- **Stance:** the judge model checks that every turn argues its assigned side. Small models drift; Gemma started defending monorepos while arguing against them.

A rejected turn is retried with the errors fed back. After 3 tries the turn is cleaned, meaning bad citations and URLs are removed, then accepted with a warning that shows up in the transcript.

Other guardrails:
- **Thinking off:** Qwen3 is called with `think: false`, and any `<think>` blocks are stripped as well, so the TTS never reads reasoning aloud.
- **Untrusted pages:** fetched text is truncated, angle brackets are removed, and it's wrapped in `<evidence>` tags. The prompt tells the models that evidence is untrusted data and that instructions inside it must be ignored.
- **Small context:** `num_ctx` is fixed at 8192. Debaters see a running "points already made" list instead of the whole transcript.
- **Judge position bias:** the judge sees Side A/B labels, never model names, and runs once with each side first. `judge.json` records whether both passes picked the same winner.
- **Search cache:** results and pages are cached on disk in `cache/`. Public engines rate-limit, and the cache also powers `make replay` for recording takes.

## Hardware

| | Minimum | Notes |
|---|---|---|
| RAM | 16 GB machine | In `cpu` mode, give Docker Desktop **≥ 10 GB** (one 4B model ≈ 4–5 GB plus Kokoro ≈ 1–2 GB). Ollama loads one model at a time. |
| Disk | ~15 GB free | models ≈ 8 GB (`qwen3:4b` 2.5 GB, `gemma3:4b` 3.3 GB, `llama3.2:3b` 2.0 GB) + images ≈ 6 GB |
| Time per debate | see below | measured with the demo topic, excluding first-time downloads |

Measured on an Apple M-series laptop (8 cores, 16 GB) with the demo topic:

| Setup | LLM phases | Audio render | Total |
|---|---|---|---|
| `host` mode (native Ollama, Metal) | ≈ 6–10 min | ≈ 3 min | ≈ 9–13 min |
| `cpu` mode (all in Docker, 5 vCPU / 12.5 GB) | ≈ 16 min | ≈ 2.5 min | ≈ 19.5 min |
| `cloud` mode (20B/14B/12B on 3× L4, from cold) | ≈ 3 min warm-up + ≈ 3.7 min | ≈ 1.6 min | ≈ 9 min |

- **First-time setup:** the first `make up` in `cpu` mode took about 14 minutes, almost all of it model downloads. That depends on your connection.
- **Output:** a debate produces about 5–6 minutes of audio.
- **Retries:** most of the run-to-run variation comes from turns that fail validation and are retried.
- **Per-phase numbers:** `state.json` → `timings_s` has them for any run.

## Reproducibility, honestly

The **setup** is pinned: image tags, model tags, `uv.lock` for Python, a fixed seed and fixed temperatures. The exact **output** is not guaranteed. LLM sampling differs across hardware and Ollama builds, and web search results change from day to day.

Some notes on pinning:
- **Model tags can move.** Ollama tags are mutable, so `make lock-models` records the digests you pulled in `models.lock`. model-init warns when a tag has moved, and `STRICT_MODELS=1` makes it fail instead.
- **Recording repeatable takes:** run once online, then `make replay RUN=…`. That reuses the same queries and serves search from the cache.

## Topic filter

Topics suggested in comments go through `config/topic_filter.yaml`: a denylist (politics, religion, violence, sexual content, named politicians, …), then a model check that the topic is really about technology. Anything rejected never reaches the debaters. Edit the list to suit your channel.

## Configuration

`config/debate.yaml` holds:
- models per role, temperature, and the `think_capable` flag
- seed and `num_ctx`
- rebuttal rounds, word limits, retries
- research breadth
- voices, speed, pause lengths

`config/pronunciations.yaml` maps jargon to how it should be spoken (`K8s` → "Kubernetes", `SQS` → "S-Q-S"). Other all-caps acronyms are spelled out automatically, except the ones on its `say_as_word` list.

## Development

```bash
uv sync
make test                          # unit tests, no services needed
make up MODE=host                  # then run the app directly on the host:
OLLAMA_URL=http://localhost:11434 SEARXNG_URL=http://localhost:8888 KOKORO_URL=http://localhost:8880 \
  uv run python -m app debate "Tabs are better than spaces"
```

You need `ffmpeg` on your PATH for MP3 output when running outside Docker. Without it you get `debate.wav` only.

## Licenses

This repository is MIT-licensed (see `LICENSE`). The components it pulls in have their own terms:

| Component | License | Notes |
|---|---|---|
| Ollama | MIT | |
| Qwen3 | Apache-2.0 | |
| gpt-oss (cloud lineup) | Apache-2.0 | |
| Gemma 3 | Gemma Terms of Use | Use restrictions apply; read them before publishing output commercially |
| Llama 3.2 | Llama 3.2 Community License + Acceptable Use Policy | Includes attribution requirements ("Built with Llama") |
| Kokoro-82M weights | Apache-2.0 | |
| Kokoro-FastAPI | Apache-2.0 | |
| SearXNG | AGPL-3.0 | Used unmodified as a separate container; this repo only mounts a settings file |
| trafilatura | Apache-2.0 | |
| ffmpeg (Debian build in the app image) | LGPL-2.1+ / GPL | |

Fetched web pages remain their authors' content. The transcript only stores short snippets, with links back to the sources.
