# MODE: auto | cpu | gpu | host
#   auto -> host on macOS when the ollama CLI is installed (Metal), else cpu.
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

.PHONY: up down logs demo debate replay resume render check-topic lock-models test build ps

up: ## start services and pull models
	@echo "mode: $(MODE)"
	@if [ "$(MODE)" = "host" ] && ! curl -sf http://localhost:11434/api/version >/dev/null; then \
	  echo "Host Ollama is not running. Start the Ollama app or run 'ollama serve', or use MODE=cpu."; exit 1; fi
	docker compose up -d --build $(SERVICES)
	docker compose run --rm model-init

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
