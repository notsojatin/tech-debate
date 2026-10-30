#!/usr/bin/env bash
# One-time, idempotent project setup: APIs, model bucket, service accounts, Private Google Access.
source "$(dirname "$0")/lib.sh"

log "Project $PROJECT_ID, region $REGION"

log "Enabling APIs"
gc services enable run.googleapis.com cloudbuild.googleapis.com storage.googleapis.com \
  compute.googleapis.com iam.googleapis.com monitoring.googleapis.com

log "Model bucket gs://$BUCKET"
if gcloud storage buckets describe "gs://$BUCKET" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "exists"
else
  gcloud storage buckets create "gs://$BUCKET" --project "$PROJECT_ID" --location "$REGION" \
    --uniform-bucket-level-access --public-access-prevention
fi

ensure_sa() {  # name, display name
  if gc iam service-accounts describe "$1@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1; then
    echo "service account $1 exists"
  else
    gc iam service-accounts create "$1" --display-name "$2"
  fi
}
log "Service accounts"
ensure_sa tech-debate-ollama "tech-debate: Cloud Run model servers (read-only bucket access)"
ensure_sa tech-debate-build "tech-debate: Cloud Build model sync (writes the bucket)"
ensure_sa tech-debate-invoker "tech-debate: calls the model services (used by gcp/proxy.sh)"

log "Bucket permissions (bucket-scoped only)"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --project "$PROJECT_ID" \
  --member "serviceAccount:$RUNTIME_SA" --role roles/storage.objectViewer --quiet >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --project "$PROJECT_ID" \
  --member "serviceAccount:$BUILD_SA" --role roles/storage.objectAdmin --quiet >/dev/null
gc projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$BUILD_SA" \
  --role roles/logging.logWriter --condition None --quiet >/dev/null
echo "runtime SA: objectViewer on the bucket; build SA: objectAdmin on the bucket + logWriter"

# Whoever runs the proxy may act as the invoker SA (on that SA only). Defaults to the active gcloud account.
: "${PROXY_USER:=$(gcloud config get-value account 2>/dev/null)}"
log "Letting $PROXY_USER act as $INVOKER_SA (Token Creator on that service account only)"
gc iam service-accounts add-iam-policy-binding "$INVOKER_SA" \
  --member "user:$PROXY_USER" --role roles/iam.serviceAccountTokenCreator --quiet >/dev/null
echo "the invoker SA gets run.invoker on each service in gcp/deploy.sh"

log "Private Google Access on subnet $SUBNET ($REGION)"
gc compute networks subnets update "$SUBNET" --region "$REGION" --enable-private-ip-google-access
gc compute networks subnets describe "$SUBNET" --region "$REGION" --format "value(privateIpGoogleAccess)"

log "Done. Next: gcp/sync-models.sh"
