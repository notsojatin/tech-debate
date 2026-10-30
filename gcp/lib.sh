# Shared helpers for the gcp/ scripts. Source it; don't run it.
set -euo pipefail

GCP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$GCP_DIR/.." && pwd)"

# Load .env.local / .env without overriding variables already set in the caller's environment.
for _env_file in "$ROOT/.env.local" "$ROOT/.env"; do
  if [[ -f "$_env_file" ]]; then
    while IFS= read -r _line || [[ -n "$_line" ]]; do
      [[ "$_line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
      _k="${BASH_REMATCH[1]}"
      _v="${BASH_REMATCH[2]}"
      _v="${_v#"${_v%%[![:space:]]*}"}"
      _v="${_v%"${_v##*[![:space:]]}"}"
      if [[ -z "${!_k+x}" ]]; then
        export "$_k=$_v"
      fi
    done < "$_env_file"
  fi
done
unset _env_file _line _k _v

# shellcheck source=config.env
source "$GCP_DIR/config.env"

if [[ -n "${BASH_SOURCE[1]:-}" && -z "$PROJECT_ID" ]]; then
  echo "error: PROJECT_ID is not set. Set it in .env.local, the environment, or via 'gcloud config set project <id>'." >&2
  exit 1
fi

RUNTIME_SA="tech-debate-ollama@${PROJECT_ID}.iam.gserviceaccount.com"
BUILD_SA="tech-debate-build@${PROJECT_ID}.iam.gserviceaccount.com"
# The proxy calls the services as this account (its ID tokens carry each service URL as audience).
INVOKER_SA="tech-debate-invoker@${PROJECT_ID}.iam.gserviceaccount.com"

log() { printf '\033[1m==> %s\033[0m\n' "$*"; }
gc() { gcloud --project "$PROJECT_ID" "$@"; }

# gpt-oss:20b -> tech-debate-gpt-oss-20b (Cloud Run names: lowercase letters, digits, hyphens)
service_name() {
  printf 'tech-debate-%s\n' "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9\n' '-')"
}

# "<cpu> <memory>" for a model, from the "<N>b" in its tag; unknown sizes get the large tier.
size_tier() {
  local n=""
  if [[ "$1" =~ :([0-9]+(\.[0-9]+)?)b$ ]]; then n="${BASH_REMATCH[1]}"; fi
  if [[ -n "$n" ]] && awk -v n="$n" -v max="$SMALL_MAX_B" 'BEGIN { exit !(n <= max) }'; then
    echo "$SMALL_CPU $SMALL_MEMORY"
  else
    echo "$LARGE_CPU $LARGE_MEMORY"
  fi
}

# "role model" lines for the cloud lineup, read from config/debate.yaml + the cloud overlay.
models_by_role() { (cd "$ROOT" && uv run --quiet python -m app.config "$DEBATE_PROFILE_CLOUD"); }

unique_models() { models_by_role | awk '{print $2}' | awk '!seen[$0]++'; }

proxy_port() {
  local var="PROXY_PORT_$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')"
  echo "${!var}"
}
