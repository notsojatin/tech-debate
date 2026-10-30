#!/usr/bin/env bash
# Pull the cloud lineup into gs://$BUCKET/ollama via Cloud Build, then check digests against models.lock.
# Set WRITE_MODEL_LOCK=1 to record new digests in models.lock.
source "$(dirname "$0")/lib.sh"

models="$(unique_models | tr '\n' ' ' | sed 's/ $//')"
log "Syncing models to gs://$BUCKET/ollama: $models"
gc builds submit --no-source --region "$REGION" \
  --config "$GCP_DIR/models/cloudbuild.yaml" \
  --service-account "projects/$PROJECT_ID/serviceAccounts/$BUILD_SA" \
  --substitutions "^|^_MODELS=$models|_BUCKET=$BUCKET|_OLLAMA_IMAGE=$OLLAMA_IMAGE|_CLOUD_SDK_IMAGE=$CLOUD_SDK_IMAGE"

log "Checking digests against models.lock"
gcloud storage cat "gs://$BUCKET/digests.txt" --project "$PROJECT_ID" | (cd "$ROOT" && uv run --quiet python -c '
import json, os, sys
lock_path = "models.lock"
lock = json.load(open(lock_path))
got = dict(line.split() for line in sys.stdin if line.strip())
for model, digest in got.items():
    old = lock.get(model)
    state = "new" if old is None else ("ok" if old == digest else "DRIFT (tag moved upstream)")
    print(f"  {model:<16} {digest[:12]}  {state}")
if os.environ.get("WRITE_MODEL_LOCK") == "1":
    lock.update(got)
    open(lock_path, "w").write(json.dumps(lock, indent=2) + "\n")
    print("wrote models.lock")
')
log "Done. Next: gcp/deploy.sh"
