#!/usr/bin/env bash
# Open an authenticated local tunnel to each role's private Cloud Run service:
#   pro -> localhost:$PROXY_PORT_PRO, con -> :$PROXY_PORT_CON, judge -> :$PROXY_PORT_JUDGE
# Requests are signed with ID tokens of $INVOKER_SA (impersonated by your gcloud login), see authproxy.py.
# Runs in the foreground; Ctrl-C closes all tunnels. Opening a tunnel does not start an instance:
# only requests do, and instances scale back to zero (at most ~10 min idle) on their own.
source "$(dirname "$0")/lib.sh"

mappings=()
while read -r role model <&3; do
  port="$(proxy_port "$role")"
  svc="$(service_name "$model")"
  if nc -z localhost "$port" 2>/dev/null; then
    echo "port $port is already in use (another proxy running?)" >&2
    exit 1
  fi
  url="$(gc run services describe "$svc" --region "$REGION" --format 'value(status.url)')"
  [[ -n "$url" ]] || { echo "$svc is not deployed; run gcp/deploy.sh" >&2; exit 1; }
  mappings+=("$role=$port=$url")
  echo "$role  $model  ->  http://localhost:$port  ($svc)"
done 3< <(models_by_role)

log "Starting tunnels as $INVOKER_SA. In another terminal: make up MODE=cloud && make debate MODE=cloud TOPIC=\"...\""
cd "$ROOT" && exec uv run --quiet python gcp/authproxy.py --sa "$INVOKER_SA" --timeout "$REQUEST_TIMEOUT" "${mappings[@]}"
