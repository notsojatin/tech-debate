# MODE: auto | cpu | gpu | host | cloud
#   auto  -> host on macOS when the ollama CLI is installed (Metal), else cpu.
#   cloud -> models on Cloud Run (see gcp/README.md); needs `make cloud-proxy` running.
MODE ?= auto
ifeq ($(MODE),auto)
  ifeq ($(shell uname -s),Darwin)
    ifneq ($(shell command -v ollama),)
      override MODE := host
    else
      override MODE := cpu
    endif
  else
    override MODE := cpu
  endif
endif

ifeq ($(MODE),host)
  export COMPOSE_PROFILES := host
  export OLLAMA_URL := http://host.docker.internal:11434
  SERVICES := kokoro searxng
else ifeq ($(MODE),cloud)
  export COMPOSE_PROFILES := host
  export DEBATE_PROFILE := cloud
  export MODEL_INIT_PULL := 0
  export OLLAMA_URL := http://host.docker.internal:11441
  export OLLAMA_URL_PRO := http://host.docker.internal:11441
  export OLLAMA_URL_CON := http://host.docker.internal:11442
  export OLLAMA_URL_JUDGE := http://host.docker.internal:11443
  SERVICES := kokoro searxng
else ifeq ($(MODE),gpu)
  export COMPOSE_PROFILES := gpu
  export OLLAMA_URL := http://ollama:11434
  SERVICES := ollama-gpu kokoro-gpu searxng
else
  export COMPOSE_PROFILES := cpu
  export OLLAMA_URL := http://ollama:11434
  SERVICES := ollama kokoro searxng
endif

RUN_APP := docker compose run --rm app
TOPIC ?=
RUN ?=

.PHONY: up down logs demo debate replay resume render check-topic serve lock-models test build ps \
	cloud-setup cloud-sync-models cloud-deploy cloud-proxy cloud-status cloud-down

up: ## start services, pull models, and launch the Web UI on http://localhost:8000
	@echo "mode: $(MODE)"
	@if [ "$(MODE)" = "host" ] && ! curl -sf http://localhost:11434/api/version >/dev/null; then \
	  echo "Host Ollama is not running. Start the Ollama app or run 'ollama serve', or use MODE=cpu."; exit 1; fi
	@if [ "$(MODE)" = "cloud" ]; then for p in 11441 11442 11443; do nc -z localhost $$p 2>/dev/null || { \
	  echo "Cloud proxy on :$$p is not running. Run 'make cloud-proxy' in another terminal first."; exit 1; }; done; fi
	docker compose up -d --build $(SERVICES)
	docker compose run --rm model-init
	docker compose up -d --build --no-deps app
	@echo "Web UI running at http://localhost:8000"

serve: ## run FastAPI + Web UI server directly on the host
	OLLAMA_URL=$${OLLAMA_URL:-http://localhost:11434} SEARXNG_URL=$${SEARXNG_URL:-http://localhost:8888} KOKORO_URL=$${KOKORO_URL:-http://localhost:8880} \
	  uv run python -m app serve

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=100

build:
	docker compose build

demo: ## one canned topic, end to end
	$(RUN_APP) demo

debate: ## make debate TOPIC="Rust is better than Go for CLIs"
	@test -n "$(TOPIC)" || (echo 'usage: make debate TOPIC="..."' && exit 1)
	$(RUN_APP) debate "$(TOPIC)"

replay: ## same topic and queries, search served from cache only: make replay RUN=out/<run>
	@test -n "$(RUN)" || (echo 'usage: make replay RUN=out/<run-dir>' && exit 1)
	$(RUN_APP) replay "/app/$(RUN)"

resume:
	@test -n "$(RUN)" || (echo 'usage: make resume RUN=out/<run-dir>' && exit 1)
	$(RUN_APP) resume "/app/$(RUN)"

render: ## rebuild transcript/SRT/MP3 without calling the LLMs
	@test -n "$(RUN)" || (echo 'usage: make render RUN=out/<run-dir>' && exit 1)
	$(RUN_APP) render "/app/$(RUN)"

check-topic:
	$(RUN_APP) check-topic "$(TOPIC)"

lock-models: ## record current model digests in models.lock
	docker compose run --rm -e WRITE_MODEL_LOCK=1 model-init

test:
	uv run pytest -q

# ---- Cloud Run (gcp/README.md). These create or change billable GCP resources.
cloud-setup:        ## APIs, model bucket, service accounts, Private Google Access
	gcp/setup.sh

cloud-sync-models:  ## pull the cloud lineup into the bucket via Cloud Build
	gcp/sync-models.sh

cloud-deploy:       ## one private GPU service per model, min 0 / max 1
	gcp/deploy.sh

cloud-proxy:        ## authenticated local tunnels on :11441-11443 (foreground)
	gcp/proxy.sh

cloud-status:       ## settings, auth check and recent instance counts
	gcp/status.sh --instances

cloud-down:         ## delete the services (asks first); gcp/teardown.sh --all also removes the bucket
	gcp/teardown.sh
