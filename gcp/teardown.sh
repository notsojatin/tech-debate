#!/usr/bin/env bash
# Delete the cloud model services. With --all, also delete the model bucket and service accounts.
# Private Google Access on the subnet is left on (it is harmless and may be used by other workloads).
source "$(dirname "$0")/lib.sh"

all=0
[[ "${1:-}" == "--all" ]] && all=1

services=()
while read -r _ model; do services+=("$(service_name "$model")"); done < <(models_by_role)
echo "This deletes Cloud Run services in $PROJECT_ID/$REGION: ${services[*]}"
[[ "$all" -eq 1 ]] && echo "and the bucket gs://$BUCKET (all model files) plus the tech-debate-ollama/-build/-invoker service accounts"
read -r -p "Type 'delete' to continue: " answer
[[ "$answer" == "delete" ]] || { echo "aborted"; exit 1; }

for svc in $(printf '%s\n' "${services[@]}" | awk '!seen[$0]++'); do
  gc run services delete "$svc" --region "$REGION" --quiet || true
done
if [[ "$all" -eq 1 ]]; then
  gcloud storage rm --recursive "gs://$BUCKET" --project "$PROJECT_ID" || true
  gc iam service-accounts delete "$RUNTIME_SA" --quiet || true
  gc iam service-accounts delete "$BUILD_SA" --quiet || true
  gc iam service-accounts delete "$INVOKER_SA" --quiet || true
fi
log "Done"
